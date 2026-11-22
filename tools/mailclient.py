#!/usr/bin/env python3
"""tools/mailclient.py - timed smtplib client (runs in clienta).

Latency starts at the instant the final CRLF.CRLF of DATA is sent.
--per-conn: messages per SMTP connection; --plain: skip STARTTLS; --keylog: TLS secrets for Wireshark.
"""
import argparse, csv, smtplib, ssl, time, uuid


class TimedSMTP(smtplib.SMTP):
    t_dot = 0

    def send(self, s):
        if isinstance(s, bytes) and s.endswith(b'\r\n.\r\n'):
            self.t_dot = time.time_ns()
        return super().send(s)


def build(sender, to, run, i, size):
    mid = '<%s-%d-%s@%s>' % (run, i, uuid.uuid4().hex[:8], sender.split('@')[1])
    # Keep each body line below Postfix's long-line folding threshold.  If a
    # milter signs one oversized line, cleanup can fold it after signing and
    # the receiver will (correctly) reject the changed body hash.
    body = '\r\n'.join('x' * 78 for _ in range((size + 77) // 78))
    body = body[:size + (size // 78)]
    raw = ('From: %s\r\nTo: %s\r\nSubject: lab %s %d\r\nMessage-ID: %s\r\nX-Run-Id: %s\r\nX-Send-Time: %d\r\n\r\n%s\r\n'
           % (sender, to, run, i, mid, run, time.time_ns(), body))
    return mid, raw.encode()


def send_batch(server, port, user, password, sender, to, n, run, start=0, size=2000, plain=False, keylog=None):
    ctx = ssl.create_default_context(cafile='/lab/build/pki/ca.crt')
    if keylog:
        ctx.keylog_filename = keylog
    s = TimedSMTP(server, port, timeout=60)
    s.ehlo()
    if not plain:
        s.starttls(context=ctx)
        s.ehlo()
    if user:
        s.login(user, password)
    rows = []
    for i in range(start, start + n):
        mid, raw = build(sender, to, run, i, size)
        s.sendmail(sender, [to], raw)
        rows.append((run, mid, s.t_dot))
    s.quit()
    return rows


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--server', default='mail.alpha.test')
    ap.add_argument('--port', type=int, default=587)
    ap.add_argument('--user', default='')
    ap.add_argument('--password', default='')
    ap.add_argument('--sender', default='alice@alpha.test')
    ap.add_argument('--to', default='bob@beta.test')
    ap.add_argument('--count', type=int, default=1)
    ap.add_argument('--per-conn', type=int, default=1)
    ap.add_argument('--run', default='r0')
    ap.add_argument('--size', type=int, default=2000)
    ap.add_argument('--plain', action='store_true')
    ap.add_argument('--keylog')
    ap.add_argument('--out', default='/lab/results/raw/sends.csv')
    a = ap.parse_args()
    rows = []
    for st in range(0, a.count, a.per_conn):
        rows += send_batch(a.server, a.port, a.user, a.password, a.sender, a.to,
                           min(a.per_conn, a.count - st), a.run, st, a.size, a.plain, a.keylog)
    with open(a.out, 'a', newline='') as f:
        csv.writer(f).writerows(rows)
