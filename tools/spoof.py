#!/usr/bin/env python3
"""tools/spoof.py - spoofing peer. forged: unauthorised IP, no signature. replay: altered copy of a signed message from alpha."""
import argparse, smtplib

ap = argparse.ArgumentParser()
ap.add_argument('--mode', choices=['forged', 'replay'], required=True)
ap.add_argument('--mail-from', default='alice@alpha.test')
ap.add_argument('--to', default='bob@beta.test')
ap.add_argument('--server', default='mail.beta.test')
ap.add_argument('--file')
ap.add_argument('--tag', default='spoof')
a = ap.parse_args()
if a.mode == 'forged':
    raw = ('From: %s\r\nTo: %s\r\nSubject: forged %s\r\nMessage-ID: <%s@forged.test>\r\n\r\nsend money\r\n'
           % (a.mail_from, a.to, a.tag, a.tag)).encode()
else:
    txt = open(a.file, 'rb').read().decode('latin1').replace('\r\n', '\n')
    head, body = txt.split('\n\n', 1)
    keep, skip = [], False
    for l in head.split('\n'):
        if l[:1] in ' \t':
            if not skip:
                keep.append(l)
            continue
        # A replay is a new SMTP submission.  Do not resend hop-local headers
        # from the captured Maildir copy, or Postfix will reject Delivered-To
        # as a forwarding loop before DKIM can evaluate the tampering.
        skip = l.lower().startswith(('authentication-results:', 'received-spf:',
                                     'return-path:', 'delivered-to:', 'x-original-to:', 'received:'))
        if not skip:
            keep.append(l)
    raw = ('\n'.join(keep) + '\n\n' + body + 'TAMPERED\n').replace('\n', '\r\n').encode('latin1')
with smtplib.SMTP(a.server, 25, timeout=60) as s:
    s.ehlo()
    s.sendmail(a.mail_from, [a.to], raw)
