#!/usr/bin/env python3
"""tools/imapclient.py - IMAP check (runs in clientb): login, list, search, fetch headers, flag change."""
import argparse, imaplib, ssl

ap = argparse.ArgumentParser()
ap.add_argument('--server', default='mail.beta.test')
ap.add_argument('--user', default='bob')
ap.add_argument('--password', default='bob-lab-pass')
ap.add_argument('--plain', action='store_true')
ap.add_argument('--show-headers', action='store_true')
ap.add_argument('--keylog')
a = ap.parse_args()
ctx = ssl.create_default_context(cafile='/lab/build/pki/ca.crt')
if a.keylog:
    ctx.keylog_filename = a.keylog
M = imaplib.IMAP4(a.server, 143)
if not a.plain:
    M.starttls(ssl_context=ctx)
M.login(a.user, a.password)
print('LIST', M.list()[1])
M.select('INBOX')
typ, data = M.search(None, 'ALL')
ids = data[0].split()
print('messages:', len(ids))
if ids:
    typ, d = M.fetch(ids[-1], '(BODY.PEEK[HEADER])')
    hdr = d[0][1].decode('latin1')
    if a.show_headers:
        show = False
        for l in hdr.splitlines():
            if l[:1] not in ' \t':
                show = l.lower().startswith(('authentication-results', 'dkim-signature', 'received-spf', 'subject'))
            if show:
                print(l)
    M.store(ids[-1], '+FLAGS', '(\\Seen)')
    print('FLAGS', M.fetch(ids[-1], '(FLAGS)')[1])
M.logout()
