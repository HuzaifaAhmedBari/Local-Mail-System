#!/usr/bin/env python3
"""tools/rtt_count.py PCAP - SMTP round trips in a capture of one TCP connection, plus session time."""
import subprocess, sys


def rounds(pcap, port=25):
    out = subprocess.run(['tshark', '-r', pcap, '-Y', 'tcp.port==%d' % port, '-T', 'fields', '-e', 'frame.time_epoch',
                          '-e', 'tcp.srcport', '-e', 'tcp.len'], capture_output=True, text=True).stdout.splitlines()
    pk = [l.split('\t') for l in out if l.strip()]
    if not pk:
        return 0, 0.0
    bursts, last = 0, None
    for t, sp, ln in pk:
        if int(ln or 0) == 0:
            continue
        client = int(sp) != port
        if client and last is not True:
            bursts += 1
        last = client
    return bursts + 1, float(pk[-1][0]) - float(pk[0][0])


if __name__ == '__main__':
    r, s = rounds(sys.argv[1])
    print('round trips: %d session: %.3f s' % (r, s))
