#!/usr/bin/env python3
"""tools/orchestrate.py - experiment harness (root, from the repo root).

    sudo -E venv/bin/python tools/orchestrate.py latency|rtt|throughput|auth|quick|all
"""
import csv, glob, json, os, shutil, subprocess as sp, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(os.path.dirname(HERE))
from lab import *
import parse_headers, rtt_count

RUNS, N = 5, 20
SENDS, ARR = 'results/raw/sends.csv', 'results/raw/arrivals.csv'
INBOX = 'data/beta-home/bob/Maildir/new'
os.makedirs('results/csv', exist_ok=True)
os.makedirs('results/raw', exist_ok=True)


def append(path, header, rows):
    new = not os.path.exists(path)
    with open(path, 'a', newline='') as f:
        w = csv.writer(f)
        if new:
            w.writerow(header)
        w.writerows(rows)


def clean_run():
    for f in (SENDS, ARR):
        if os.path.exists(f):
            os.remove(f)
    reset()


def client_send(n, run, per_conn=1, port=587, server='mail.alpha.test', user='alice', plain=False):
    cmd = ['python3', '/lab/tools/mailclient.py', '--server', server, '--port', str(port)]
    if user:
        cmd += ['--user', user, '--password', pw(user)]
    cmd += ['--count', str(n), '--per-conn', str(per_conn), '--run', run]
    if plain:
        cmd.append('--plain')
    d('clienta', cmd)


def arrivals():
    return list(csv.DictReader(open(ARR))) if os.path.exists(ARR) else []


def wait_for(n, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if len(arrivals()) >= n:
            return True
        time.sleep(0.5)
    return False


def latencies():
    sends = {r[1]: int(r[2]) for r in csv.reader(open(SENDS)) if r}
    arr = {r['msgid']: int(r['t_arrive_ns']) for r in arrivals() if r['msgid']}
    return {m: (arr[m] - t) / 1e6 for m, t in sends.items() if m in arr}, sends


class Watch:
    def __enter__(self):
        self.p = sp.Popen([sys.executable, 'tools/watcher.py', ARR])
        time.sleep(1)
        return self

    def __exit__(self, *a):
        self.p.terminate()
        self.p.wait()


def latency():
    path = 'results/csv/latency.csv'
    if os.path.exists(path):
        os.remove(path)
    for name, tls, auth_, cold in [('baseline', 'on', 'on', False), ('plain', 'off', 'on', False),
                                   ('noauth', 'on', 'off', False), ('cold', 'on', 'on', True)]:
        set_tls(tls)
        set_auth(auth_)
        for rtt_ms in (20, 100, 200):
            for run in range(1, RUNS + 1):
                clean_run()
                condition(rtt_ms, 0)
                flush_dns() if cold else prime_dns()
                with Watch():
                    client_send(N, 'L%d' % run, plain=(tls == 'off'))
                    wait_for(N, 60 + 2 * N * rtt_ms / 100)
                lat, sends = latencies()
                append(path, ['variant', 'condition', 'run', 'msgid', 'latency_ms'],
                       [(name, 'rtt%d' % rtt_ms, run, m, round(lat[m], 3) if m in lat else '') for m in sends])
                print(name, rtt_ms, run, round(sum(lat.values()) / max(len(lat), 1), 1), 'ms', len(lat), '/', N)
    clear()
    set_tls('on')
    set_auth('on')


def rtt():
    path = 'results/csv/rtt.csv'
    if os.path.exists(path):
        os.remove(path)
    for tls in ('on', 'off'):
        set_tls(tls)
        for per in (1, 5):
            for ms in (20, 100, 200):
                for run in range(1, RUNS + 1):
                    clean_run()
                    condition(ms, 0)
                    pcap = 'results/raw/rtt_%s_%d_%d_%d.pcapng' % (tls, per, ms, run)
                    ensure_netns('r1')
                    cap = sp.Popen(['ip', 'netns', 'exec', 'clab-%s-r1' % LAB, 'tshark', '-q', '-i',
                                    ENV['R1_TRANSIT_IF'], '-f', 'tcp port 25', '-w', pcap], stderr=sp.DEVNULL)
                    time.sleep(2)
                    client_send(per, 'R%d' % run, per_conn=per, port=25, server='mail.beta.test', user='',
                                plain=(tls == 'off'))
                    time.sleep(1)
                    cap.terminate()
                    cap.wait()
                    n_rounds, secs = rtt_count.rounds(pcap)
                    os.remove(pcap)
                    append(path, ['variant', 'condition', 'run', 'rounds', 'session_s', 'expected_s'],
                           [('tls_%s_msgs%d' % (tls, per), 'rtt%d' % ms, run, n_rounds, round(secs, 3),
                             round(n_rounds * ms / 1000, 3))])
    clear()
    set_tls('on')


def throughput():
    path = 'results/csv/throughput.csv'
    if os.path.exists(path):
        os.remove(path)
    set_tls('on')
    set_auth('on')
    for loss in (0, 2, 5):
        for c in (1, 5, 10, 20):
            for run in range(1, RUNS + 1):
                clean_run()
                condition(20, loss)
                prime_dns()
                n = 100
                with Watch():
                    try:
                        out = json.loads(d('clienta', ['python3', '/lab/tools/loadgen.py', '--n', str(n), '--c', str(c),
                                                       '--run', 'T%d' % run, '--user', 'alice',
                                                       '--password', pw('alice')]).strip().splitlines()[-1])
                    except Exception as e:
                        print('loadgen failed', loss, c, run, e)
                        continue
                    backlog = queue_len('alpha')
                    wait_for(n, 120)
                lat, sends = latencies()
                arr = [int(r['t_arrive_ns']) for r in arrivals()]
                span = (max(arr) - out['t_start_ns']) / 1e9 if arr else 0
                append(path, ['condition', 'concurrency', 'run', 'delivered', 'deliveries_per_s', 'mean_latency_ms', 'backlog'],
                       [('loss%d' % loss, c, run, len(arr), round(len(arr) / span, 3) if span else 0,
                         round(sum(lat.values()) / max(len(lat), 1), 1), backlog)])
                print('loss', loss, 'c', c, 'run', run, 'delivered', len(arr), '/', n)
    clear()


EXPECT = {'A1': ({'pass'}, {'pass'}), 'A2': ({'fail'}, {'none'}), 'A3': ({'pass'}, {'fail'}),
          'A4': ({'pass'}, {'fail', 'permerror', 'neutral'}), 'A5': ({'softfail'}, {'none'}),
          'A6': ({'none'}, {'none'})}


def inbox_files(n=1, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        f = sorted(glob.glob(INBOX + '/*'), key=os.path.getmtime)
        if len(f) >= n:
            return f
        time.sleep(0.5)
    return []


def spoof(mode, frm, tag, node='attacker', extra=()):
    d(node, ['python3', '/lab/tools/spoof.py', '--mode', mode, '--mail-from', frm, '--tag', tag] + list(extra))


def run_case(case, run):
    clean_run()
    tag = '%s_%d' % (case, run)
    if case == 'A1':
        client_send(1, tag)
    elif case == 'A2':
        spoof('forged', 'x@alpha.test', tag)
    elif case == 'A5':
        spoof('forged', 'x@soft.test', tag)
    elif case == 'A6':
        spoof('forged', 'x@none.test', tag)
    elif case == 'A4':
        set_selector('bad')
        try:
            client_send(1, tag)
            # Wait for the queued message before restoring the selector.  The
            # SMTP client returning only means Postfix accepted it; relaying
            # and milter processing happen asynchronously.
            f = inbox_files()
        finally:
            set_selector('mail')
        return parse_headers.verdict(f[-1]) if f else ('missing', 'missing')
    elif case == 'A3':
        client_send(1, tag)
        f = inbox_files()
        if f:
            shutil.copy(f[-1], 'results/raw/signed.eml')
        clean_run()
        spoof('replay', 'alice@alpha.test', tag, 'alpha', ['--file', '/lab/results/raw/signed.eml'])
    f = inbox_files()
    return parse_headers.verdict(f[-1]) if f else ('missing', 'missing')


def auth():
    path = 'results/csv/auth.csv'
    if os.path.exists(path):
        os.remove(path)
    set_tls('on')
    set_auth('on')
    for loss in (0, 2, 5):
        condition(20, loss)
        for case in EXPECT:
            for run in range(1, RUNS + 1):
                spf, dkim = run_case(case, run)
                ok = int(spf in EXPECT[case][0] and dkim in EXPECT[case][1])
                append(path, ['condition', 'case', 'run', 'spf', 'dkim', 'ok'], [('loss%d' % loss, case, run, spf, dkim, ok)])
                print(loss, case, run, spf, dkim, 'OK' if ok else 'DIFF')
    clear()


def quick():
    clean_run()
    with Watch():
        client_send(5, 'Q')
        wait_for(5, 60)
    lat, _ = latencies()
    print('delivered %d/5, mean latency %.1f ms' % (len(lat), sum(lat.values()) / max(len(lat), 1)))


if __name__ == '__main__':
    need_root()
    what = sys.argv[1] if len(sys.argv) > 1 else 'all'
    jobs = {'latency': latency, 'rtt': rtt, 'throughput': throughput, 'auth': auth, 'quick': quick}
    try:
        for name in ([k for k in jobs if k != 'quick'] if what == 'all' else [what]):
            jobs[name]()
    finally:
        try:
            clear()
            set_tls('on')
            set_auth('on')
            set_selector('mail')
        finally:
            fix_owner()
