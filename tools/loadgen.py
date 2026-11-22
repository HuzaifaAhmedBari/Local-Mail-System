#!/usr/bin/env python3
"""tools/loadgen.py - send N messages over C concurrent submission connections; prints timing as JSON."""
import argparse, csv, json, sys, time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, '/lab/tools')
import mailclient

ap = argparse.ArgumentParser()
ap.add_argument('--n', type=int, default=100)
ap.add_argument('--c', type=int, default=5)
ap.add_argument('--run', default='r0')
ap.add_argument('--server', default='mail.alpha.test')
ap.add_argument('--port', type=int, default=587)
ap.add_argument('--user', default='alice')
ap.add_argument('--password', default='')
ap.add_argument('--to', default='bob@beta.test')
ap.add_argument('--out', default='/lab/results/raw/sends.csv')
a = ap.parse_args()
share = [a.n // a.c + (1 if k < a.n % a.c else 0) for k in range(a.c)]
t0 = time.time_ns()


def work(k):
    if share[k] == 0:
        return []
    return mailclient.send_batch(a.server, a.port, a.user, a.password, 'alice@alpha.test', a.to,
                                 share[k], '%sw%d' % (a.run, k), 0)


with ThreadPoolExecutor(a.c) as ex:
    res = list(ex.map(work, range(a.c)))
t1 = time.time_ns()
rows = [r for rr in res for r in rr]
with open(a.out, 'a', newline='') as f:
    csv.writer(f).writerows(rows)
print(json.dumps({'t_start_ns': t0, 't_end_ns': t1, 'sent': len(rows)}))
