#!/usr/bin/env python3
"""tools/stagetests.py - automated stage tests (run from the repo root, as root).

    sudo -E venv/bin/python tools/stagetests.py network|sockets|dns|mail|tls|auth|all
"""
import os, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(os.path.dirname(HERE))
from lab import *
from lab import INBOX_BOB, INBOX_ALICE

RESULTS = []


def ok(name, cond, detail=''):
    print('[%s] %s%s' % ('PASS' if cond else 'FAIL', name, '\n       ' + detail.strip()[-300:] if detail and not cond else ''))
    RESULTS.append(bool(cond))
    return cond


def poll(fn, timeout=40, every=1.0):
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return True
        time.sleep(every)
    return False


def log_has(node, *needles):
    out = x(node, ['cat', '/var/log/mail.log']).stdout
    return all(n in out for n in needles)


def swaks(to='bob@beta.test', tls=False, port=587, subject='stage test'):
    cmd = ['swaks', '--server', 'mail.alpha.test', '--port', str(port), '--auth', 'LOGIN', '--auth-user', 'alice',
           '--auth-password', pw('alice'), '--from', 'alice@alpha.test', '--to', to,
           '--header', 'Subject: ' + subject, '--body', 'hello']
    return x('clienta', cmd + (['--tls'] if tls else []))


def start_postfix(*nodes):
    for n in nodes:
        x(n, ['postfix', 'start'])
    time.sleep(3)


# ---------------------------------------------------------------- stages
def network():
    print('--- stage 1: network')
    out = x('clienta', ['ping', '-c', '3', ENV['BETA_IP']]).stdout
    ok('clienta pings beta across both routers', ' 0% packet loss' in out, out)
    r1 = x('r1', ['vtysh', '-c', 'show ip route']).stdout
    ok('R1 route to 10.10.2.0/24 via 10.10.0.2', '10.10.2.0/24' in r1 and '10.10.0.2' in r1, r1)
    r2 = x('r2', ['vtysh', '-c', 'show ip route']).stdout
    ok('R2 routes to 10.10.1.0/24 and 10.10.3.0/24 via 10.10.0.1',
       all(s in r2 for s in ('10.10.1.0/24', '10.10.3.0/24', '10.10.0.1')), r2)
    tr = x('clienta', ['traceroute', '-n', ENV['BETA_IP']]).stdout
    hops = ' '.join(tr.splitlines()[1:])
    pos = [hops.find(h) for h in (ENV['R1_ALPHA'], ENV['R2_TRANSIT'], ENV['BETA_IP'])]
    ok('traceroute lists R1, R2, beta in order', all(p >= 0 for p in pos) and pos == sorted(pos), tr)


def sockets():
    print('--- stage: sockets')
    for node, ports in SERVICES_UNDER_TEST:
        for p in ports:
            cp = x('clienta', ['python3', '/lab/tools/socktest.py', 'port', node, str(p)])
            ok('clienta reaches %s:%d' % (node, p), cp.returncode == 0, cp.stdout)
    for host, p in (('mail.alpha.test', 25), ('mail.beta.test', 25), ('mx2.beta.test', 25)):
        cp = x('clienta', ['python3', '/lab/tools/socktest.py', 'banner', host, str(p)])
        ok('SMTP banner from %s' % host, cp.stdout.startswith('220'), cp.stdout)


SERVICES_UNDER_TEST = [(ENV['ALPHA_IP'], [25, 587, 143]), (ENV['BETA_IP'], [25, 143]),
                       (ENV['MX2_IP'], [25]), (ENV['DNS_IP'], [53])]


def dns():
    print('--- stage 2: DNS')
    dig = lambda node, *a: x(node, ['dig', '+short'] + list(a)).stdout
    mx = dig('alpha', 'MX', 'beta.test')
    ok('MX beta.test = 10 mail / 20 mx2', '10 mail.beta.test.' in mx and '20 mx2.beta.test.' in mx, mx)
    ok('A mail.beta.test = %s' % ENV['BETA_IP'], ENV['BETA_IP'] in dig('alpha', 'A', 'mail.beta.test'))
    spf = dig('alpha', 'TXT', 'alpha.test')
    ok('SPF record of alpha.test', 'v=spf1 ip4:%s -all' % ENV['ALPHA_IP'] in spf, spf)
    key = ''.join(re.findall(r'"([^"]*)"', dig('alpha', 'TXT', 'mail._domainkey.alpha.test')))
    ok('DKIM key record (several strings joined)', key.startswith('v=DKIM1') and 'p=' in key, key[:80])
    ok('soft.test publishes ~all', '~all' in dig('alpha', 'TXT', 'soft.test'))
    ok('none.test has no TXT answer', dig('alpha', 'TXT', 'none.test').strip() == '')
    tcp = x('clienta', ['dig', '@' + ENV['DNS_IP'], '+tcp', '+short', 'MX', 'beta.test']).stdout
    ok('DNS over TCP works', 'mail.beta.test.' in tcp, tcp)
    flush_dns()
    x('alpha', ['dig', 'MX', 'beta.test'])
    second = x('alpha', ['dig', 'MX', 'beta.test']).stdout
    m = re.search(r'Query time: (\d+) msec', second)
    ok('second lookup is served from the unbound cache (<= 2 ms)', m and int(m.group(1)) <= 2, second)


def mail():
    print('--- stage 3: mail by MX (TLS off first)')
    clear()
    set_auth('on')
    set_tls('off')
    try:
        reset()
        cp = swaks()
        ok('submission on 587 accepted', cp.returncode == 0, cp.stdout)
        ok('delivered to bob', wait_files(INBOX_BOB, 1, 30))
        ok('alpha relayed to the primary MX', poll(lambda: log_has('alpha', 'status=sent', 'relay=mail.beta.test[10.10.2.25]:25'), 15))

        print('  backup MX')
        reset()
        x('beta', ['postfix', 'stop'])
        swaks(subject='backup mx')
        ok('alpha used the backup MX', poll(lambda: log_has('alpha', 'relay=mx2.beta.test[10.10.3.26]:25', 'status=sent'), 40))
        ok('message queued on mx2', poll(lambda: 'Mail queue is empty' not in x('mx2', ['postqueue', '-p']).stdout, 30))
        start_postfix('beta')
        x('mx2', ['postqueue', '-f'])
        ok('queued message drains into bob', wait_files(INBOX_BOB, 1, 40))

        print('  unknown user')
        reset()
        swaks(to='nobody@beta.test', subject='unknown user')
        ok('alpha logs bounced ... 550 5.1.1', poll(lambda: log_has('alpha', 'status=bounced', '550 5.1.1'), 40))
        ok('bounce lands in alice Maildir', wait_files(INBOX_ALICE, 1, 40))

        print('  unreachable MX')
        reset()
        x('beta', ['postfix', 'stop'])
        x('mx2', ['postfix', 'stop'])
        swaks(subject='unreachable')
        ok('alpha defers and keeps it queued', poll(lambda: queue_len('alpha') >= 1 and log_has('alpha', 'status=deferred'), 40))
        start_postfix('beta', 'mx2')
        x('alpha', ['postqueue', '-f'])
        ok('delivered after the MXes return', wait_files(INBOX_BOB, 1, 90))
    finally:
        start_postfix('beta', 'mx2')
        set_tls('on')


def tls():
    print('--- stage 4: TLS')
    set_tls('on')
    ca = '/lab/build/pki/ca.crt'
    for node, proto, target in (('clienta', 'smtp', 'mail.alpha.test:587'), ('clienta', 'smtp', 'mail.beta.test:25'),
                                ('clientb', 'imap', 'mail.beta.test:143')):
        out = x(node, ['openssl', 's_client', '-starttls', proto, '-connect', target, '-CAfile', ca, '-brief']).stdout
        ok('%s STARTTLS to %s: TLSv1.3 and Verification OK' % (proto, target),
           'TLSv1.3' in out and 'Verification: OK' in out, out)
    cp = x('clienta', ['python3', '/lab/tools/socktest.py', 'smtptls', 'mail.beta.test', '25'])
    ok('socktest smtptls', cp.returncode == 0, cp.stdout)
    refused = swaks()
    ok('TLS on: AUTH without STARTTLS is refused', refused.returncode != 0, refused.stdout)
    set_tls('off')
    reset()
    plain = swaks()
    ok('TLS off: AUTH on 587 works without --tls', plain.returncode == 0, plain.stdout)
    set_tls('on')
    refused = swaks()
    ok('TLS back on: plain AUTH refused again', refused.returncode != 0, refused.stdout)
    reset()


def auth():
    print('--- stage 5: SPF/DKIM matrix A1..A6 at 0% loss')
    import orchestrate as o
    set_tls('on')
    set_auth('on')
    clear()
    try:
        for case, (spf_ok, dkim_ok) in o.EXPECT.items():
            spf, dkim = o.run_case(case, 1)
            ok('%s: spf=%s dkim=%s (expected %s / %s)' % (case, spf, dkim, '|'.join(sorted(spf_ok)), '|'.join(sorted(dkim_ok))),
               spf in spf_ok and dkim in dkim_ok)
    finally:
        set_selector('mail')


STAGES = {'network': network, 'sockets': sockets, 'dns': dns, 'mail': mail, 'tls': tls, 'auth': auth}

if __name__ == '__main__':
    need_root()
    what = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if what != 'all' and what not in STAGES:
        sys.exit(__doc__)
    try:
        for name in (STAGES if what == 'all' else [what]):
            STAGES[name]()
    finally:
        clear()
        set_tls('on')
        set_auth('on')
        fix_owner()
    print('\n%d/%d checks passed' % (sum(RESULTS), len(RESULTS)))
    sys.exit(0 if all(RESULTS) else 1)
