#!/usr/bin/env python3
"""nodes/ctl_node.py NODE COMMAND [ARG]

Runs inside a container (called by tools/lab.py through docker exec). It replaces
the shell scripts of the old guide:
  tls on|off            Postfix and Dovecot TLS policy (set_tls)
  auth on|off           beta: SPF policy service and DKIM verifying milter (set_auth)
  selector bad|mail     alpha: DKIM selector used for signing (case A4)
  restart-unbound       empty the local DNS cache (cold cache)
"""
import os, re, subprocess as sp, sys, time

node, cmd = sys.argv[1], sys.argv[2]
arg = sys.argv[3] if len(sys.argv) > 3 else ''
DEVNULL = sp.DEVNULL


def run(*c):
    return sp.run(c, stdout=DEVNULL, stderr=DEVNULL).returncode


def pc(flag, *settings):
    sp.run(['postconf', flag] + list(settings), check=True)


def daemon(c, log):
    sp.Popen(c, stdout=open(log, 'a'), stderr=sp.STDOUT, start_new_session=True)


def restart_unbound():
    run('pkill', '-x', 'unbound')
    time.sleep(0.4)
    if os.path.exists('/run/unbound.pid'):
        os.remove('/run/unbound.pid')
    run('unbound', '-c', '/etc/unbound/unbound.conf')
    for _ in range(50):                      # wait until it answers (name is not cached by the lab zones)
        if sp.run(['dig', '+time=1', '+tries=1', '+short', '@127.0.0.1', 'A', 'warmup.test'],
                  stdout=DEVNULL, stderr=DEVNULL).returncode == 0:
            return
        time.sleep(0.1)


def restart_opendkim():
    # Selector changes happen while Postfix is live.  OpenDKIM can leave its
    # milter socket in use briefly after SIGTERM; starting the replacement
    # immediately then fails with smfi_opensocket().  Kill the old instance
    # decisively and wait until it is gone before cleaning/recreating state.
    run('pkill', '-9', '-x', 'opendkim')
    for _ in range(50):
        if run('pgrep', '-x', 'opendkim') != 0:
            break
        time.sleep(0.1)
    for stale in ('/run/opendkim/opendkim.pid', '/run/opendkim/opendkim.sock'):
        if os.path.exists(stale):
            os.remove(stale)
    daemon(['opendkim', '-f', '-x', '/etc/opendkim.conf'], '/var/log/opendkim.log')
    # Do not let the test race the new milter startup.
    for _ in range(50):
        ready = sp.run(['sh', '-c', "ss -ltn | grep -q '127.0.0.1:8891'"],
                       stdout=DEVNULL, stderr=DEVNULL)
        if ready.returncode == 0:
            return
        time.sleep(0.1)


if cmd == 'tls':
    on = arg == 'on'
    level = 'may' if on else 'none'
    pc('-e', 'smtpd_tls_security_level=' + level, 'smtp_tls_security_level=' + level)
    if node == 'alpha':
        pc('-P', 'submission/inet/smtpd_tls_security_level=' + ('encrypt' if on else 'none'),
           'submission/inet/smtpd_tls_auth_only=' + ('yes' if on else 'no'))
    if node in ('alpha', 'beta'):
        open('/etc/dovecot/tls_mode.conf', 'w').write(
            'ssl = required\ndisable_plaintext_auth = yes\n' if on else 'ssl = no\ndisable_plaintext_auth = no\n')
        run('doveadm', 'reload')
    run('postfix', 'reload')
    time.sleep(1)

elif cmd == 'auth' and node == 'beta':
    if arg == 'on':
        pc('-e', 'smtpd_milters=inet:127.0.0.1:8891',
           'smtpd_recipient_restrictions=reject_unlisted_recipient, permit_mynetworks, '
           'reject_unauth_destination, '
           'check_policy_service unix:private/policy-spf')
    else:
        pc('-e', 'smtpd_milters=', 'smtpd_recipient_restrictions=permit_mynetworks, reject_unauth_destination')
    run('postfix', 'reload')
    time.sleep(1)

elif cmd == 'selector' and node == 'alpha':
    conf = open('/etc/opendkim.conf').read()
    conf = re.sub(r'^Selector .*$', 'Selector ' + arg, conf, flags=re.M)
    open('/etc/opendkim.conf', 'w').write(conf)
    restart_opendkim()

elif cmd == 'restart-unbound':
    restart_unbound()

else:
    sys.exit('unknown command %s %s for node %s' % (cmd, arg, node))
