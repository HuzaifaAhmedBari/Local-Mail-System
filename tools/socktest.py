#!/usr/bin/env python3
"""tools/socktest.py - socket and TLS probes that run inside the nodes (standard library only).

  socktest.py port HOST PORT          exit 0 if a TCP connection succeeds
  socktest.py banner HOST PORT        print the first line the server sends
  socktest.py smtptls HOST [PORT]     EHLO, STARTTLS, verify against the lab CA, print protocol
  socktest.py imaptls HOST [PORT]     same for IMAP (default 143)
"""
import imaplib, smtplib, socket, ssl, sys

CA = '/lab/build/pki/ca.crt'


def port(host, p):
    try:
        socket.create_connection((host, int(p)), timeout=3).close()
        return 0
    except OSError as e:
        print('connect %s:%s failed: %s' % (host, p, e))
        return 1


def banner(host, p):
    s = socket.create_connection((host, int(p)), timeout=5)
    print(s.recv(300).decode('latin1').strip().splitlines()[0])
    s.close()
    return 0


def report(sock, host):
    print('Protocol version: %s' % sock.version())
    print('Cipher: %s' % sock.cipher()[0])
    subj = dict(x[0] for x in sock.getpeercert()['subject'])
    print('Peer: %s' % subj.get('commonName'))
    print('Verification: OK')                     # create_default_context raised already if it was not
    return 0 if sock.version() == 'TLSv1.3' else 1


def smtptls(host, p=25):
    ctx = ssl.create_default_context(cafile=CA)
    s = smtplib.SMTP(host, int(p), timeout=15)
    s.ehlo()
    if not s.has_extn('starttls'):
        print('server does not offer STARTTLS')
        return 1
    s.starttls(context=ctx)
    rc = report(s.sock, host)
    s.quit()
    return rc


def imaptls(host, p=143):
    ctx = ssl.create_default_context(cafile=CA)
    m = imaplib.IMAP4(host, int(p))
    m.starttls(ssl_context=ctx)
    rc = report(m.sock, host)
    m.logout()
    return rc


if __name__ == '__main__':
    if len(sys.argv) < 3 or sys.argv[1] not in ('port', 'banner', 'smtptls', 'imaptls'):
        sys.exit(__doc__)
    try:
        sys.exit(globals()[sys.argv[1]](*sys.argv[2:]))
    except (OSError, ssl.SSLError, smtplib.SMTPException, imaplib.IMAP4.error) as e:
        print('error: %s' % e)
        sys.exit(2)
