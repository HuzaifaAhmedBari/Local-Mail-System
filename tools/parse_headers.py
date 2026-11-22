#!/usr/bin/env python3
"""tools/parse_headers.py DIR - SPF and DKIM verdicts from stored messages."""
import glob, os, re, sys


def verdict(path):
    t = open(path, 'rb').read().decode('latin1').replace('\r\n', '\n')
    head = re.sub(r'\n[ \t]+', ' ', t.split('\n\n', 1)[0])
    spf = dkim = None
    for l in head.split('\n'):
        if not l.lower().startswith('authentication-results:'):
            continue
        for k, v, rest in re.findall(r'\b(spf|dkim)=(\w+)([^;]*)', l.lower()):
            if k == 'spf' and (spf is None or 'mailfrom' in rest):
                spf = v
            if k == 'dkim' and dkim is None:
                dkim = v
    if spf is None:
        m = re.search(r'^received-spf:\s*(\w+)', head, re.I | re.M)
        spf = m.group(1).lower() if m else 'none'
    # OpenDKIM reports no dkim= token when a signature is present but its
    # selector has no DNS key.  That is a permanent verification error, not
    # an unsigned message; normalize it for the lab's SPF/DKIM matrix.
    if dkim is None and re.search(r'^DKIM-Signature:', head, re.I | re.M):
        dkim = 'permerror'
    return spf, dkim or 'none'


if __name__ == '__main__':
    for f in sorted(glob.glob(sys.argv[1] + '/*'), key=os.path.getmtime):
        print(os.path.basename(f), *verdict(f))
