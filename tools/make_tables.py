#!/usr/bin/env python3
"""tools/make_tables.py - tables, graphs and results/summary.md from results/csv/*.csv (run: make tables)."""
import os
import pandas as pd, matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
C, T, G = 'results/csv/', 'results/tables/', 'results/graphs/'
for p in (T, G):
    os.makedirs(p, exist_ok=True)
num = lambda s, pre: s.str.replace(pre, '', regex=False).astype(int)
summary = ['# Experiment summary (mean and standard deviation across runs)\n']


def md(df):
    cols = list(df.columns)
    rows = ['| ' + ' | '.join(cols) + ' |', '|' + '---|' * len(cols)]
    rows += ['| ' + ' | '.join(str(r[c]) for c in cols) + ' |' for _, r in df.iterrows()]
    return '\n'.join(rows)


def add(name, title, df, note=''):
    df.to_csv(T + name + '.csv', index=False)
    summary.append('\n## %s\n\n%s\n\n%s\n' % (title, note, md(df)))


def finish(ax, fig, name, xlabel, ylabel, title):
    ax.set_xlabel(xlabel); ax.set_ylabel(ylabel); ax.set_title(title); ax.grid(alpha=0.3); ax.legend()
    fig.tight_layout(); fig.savefig(G + name, dpi=200); plt.close(fig)


# 1. delivery latency: mean per run first, then mean and std across the runs; delivered ratio shown too
L = pd.read_csv(C + 'latency.csv')
runs = L.groupby(['variant', 'condition', 'run']).latency_ms.mean().reset_index()
t = runs.groupby(['variant', 'condition']).latency_ms.agg(['mean', 'std', 'count']).round(2).reset_index()
ratio = L.groupby(['variant', 'condition']).latency_ms.apply(lambda s: s.notna().mean()).round(3).reset_index(name='delivered_ratio')
t = t.merge(ratio, on=['variant', 'condition'])
t['rtt_ms'] = num(t.condition, 'rtt')
t = t.sort_values(['variant', 'rtt_ms'])
add('latency', 'Delivery latency (ms)', t.drop(columns='rtt_ms'),
    'Per-run mean of 20 messages; delivered_ratio is the share of messages that arrived.')
fig, ax = plt.subplots()
for v, g in t.groupby('variant'):
    ax.errorbar(g.rtt_ms, g['mean'], yerr=g['std'], marker='o', capsize=3, label=v)
finish(ax, fig, 'latency.png', 'RTT on the transit link (ms)', 'delivery latency (ms)', 'Delivery latency vs RTT')

# 2. SMTP round trips and session time against rounds x RTT
R = pd.read_csv(C + 'rtt.csv')
t = R.groupby(['variant', 'condition']).agg(rounds=('rounds', 'mean'), session_mean_s=('session_s', 'mean'),
                                            session_std_s=('session_s', 'std'),
                                            rounds_x_rtt_s=('expected_s', 'mean')).round(3).reset_index()
t['rtt_ms'] = num(t.condition, 'rtt')
t = t.sort_values(['variant', 'rtt_ms'])
add('rtt', 'SMTP round trips and session time', t.drop(columns='rtt_ms'), 'rounds_x_rtt_s is the prediction: round trips times RTT.')
fig, ax = plt.subplots()
for v, g in t.groupby('variant'):
    ln = ax.errorbar(g.rtt_ms, g.session_mean_s, yerr=g.session_std_s, marker='o', capsize=3, label=v + ' measured')
    ax.plot(g.rtt_ms, g.rounds_x_rtt_s, '--', color=ln[0].get_color(), label=v + ' rounds x RTT')
finish(ax, fig, 'rtt.png', 'RTT (ms)', 'session time (s)', 'SMTP session time vs rounds x RTT')

# 3. throughput, latency and queue backlog under loss (three graphs)
H = pd.read_csv(C + 'throughput.csv')
t = H.groupby(['condition', 'concurrency']).agg(rate_mean=('deliveries_per_s', 'mean'), rate_std=('deliveries_per_s', 'std'),
                                                latency_mean_ms=('mean_latency_ms', 'mean'), latency_std_ms=('mean_latency_ms', 'std'),
                                                backlog_mean=('backlog', 'mean'), backlog_std=('backlog', 'std'),
                                                delivered_mean=('delivered', 'mean'), runs=('run', 'count')).round(2).reset_index()
add('throughput', 'Throughput, latency and queue backlog under loss', t, 'Loss is applied per direction on both transit interfaces.')
for col, err, name, ylabel in (('rate_mean', 'rate_std', 'throughput_rate.png', 'messages delivered per second'),
                               ('backlog_mean', 'backlog_std', 'throughput_backlog.png', 'messages still queued on alpha when sending ended'),
                               ('latency_mean_ms', 'latency_std_ms', 'throughput_latency.png', 'mean delivery latency (ms)')):
    fig, ax = plt.subplots()
    for cnd, g in t.groupby('condition'):
        ax.errorbar(g.concurrency, g[col], yerr=g[err], marker='o', capsize=3, label=cnd)
    finish(ax, fig, name, 'concurrent connections', ylabel, ylabel + ' vs concurrency')

# 4. SPF/DKIM verdicts
A = pd.read_csv(C + 'auth.csv')
t = A.groupby(['condition', 'case']).agg(match_rate=('ok', 'mean'), runs=('run', 'count')).round(2).reset_index()
add('auth', 'SPF/DKIM verdicts', t, 'match_rate is the share of runs whose verdict equals the expected one.')
seen = A.groupby(['condition', 'case']).agg(spf=('spf', lambda s: ','.join(sorted(set(s)))),
                                            dkim=('dkim', lambda s: ','.join(sorted(set(s))))).reset_index()
add('auth_observed', 'Observed verdict strings', seen)
fig, ax = plt.subplots()
t.pivot(index='case', columns='condition', values='match_rate').plot.bar(ax=ax)
ax.set_ylim(0, 1.05); ax.set_xlabel('test case'); ax.set_ylabel('share of runs with the expected verdict')
ax.set_title('SPF/DKIM verdicts vs packet loss'); ax.grid(alpha=0.3); fig.tight_layout(); fig.savefig(G + 'auth.png', dpi=200)
open('results/summary.md', 'w').write(''.join(summary))
print('tables, graphs and results/summary.md written')
