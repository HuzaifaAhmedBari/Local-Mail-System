#!/usr/bin/env python3
"""nodes/start_node.py NODE - runs inside every non-router container (containerlab exec).

Sets the address and default gateway, then writes configuration and starts the
daemons for the node's role: dnsmasq, unbound, Postfix, Dovecot, OpenDKIM, SPF agent.
Postfix is configured with postconf argument lists, so there is no shell quoting.
"""
import os, shutil, subprocess as sp, sys

N = sys.argv[1]
E = dict(l.strip().split('=', 1) for l in open('/lab/config.env') if '=' in l and not l.startswith('#'))
ADDR = {'clienta': (E['CLIENTA_IP'], E['R1_ALPHA']), 'alpha': (E['ALPHA_IP'], E['R1_ALPHA']),
        'clientb': (E['CLIENTB_IP'], E['R2_BETA']), 'beta': (E['BETA_IP'], E['R2_BETA']),
        'dns': (E['DNS_IP'], E['R1_SVC']), 'mx2': (E['MX2_IP'], E['R1_SVC']),
        'attacker': (E['ATTACKER_IP'], E['R1_SVC'])}


def run(*cmd):
    sp.run(cmd, stdout=sp.DEVNULL, stderr=sp.DEVNULL)


def write(path, text):
    with open(path, 'w') as f:
        f.write(text)


def daemon(cmd, log):
    sp.Popen(cmd, stdout=open(log, 'w'), stderr=sp.STDOUT, start_new_session=True)


def pc(flag, *settings):
    sp.run(['postconf', flag] + list(settings), check=True)       # argument list: no shell quoting


# ---- address and default gateway (drop the management default route so traffic crosses the routers) ----
ip, gw = ADDR[N]
run('ip', 'addr', 'add', ip + '/24', 'dev', 'eth1')
run('ip', 'link', 'set', 'eth1', 'up')
run('ip', 'route', 'del', 'default')
run('ip', 'route', 'add', 'default', 'via', gw, 'dev', 'eth1')


# ---- DNS (section 6) ----
def direct_dns():
    write('/etc/resolv.conf', 'nameserver %s\n' % E['DNS_IP'])


def cfg_dns():
    shutil.copy('/lab/build/dns/dnsmasq.conf', '/etc/dnsmasq.conf')
    direct_dns()
    daemon(['dnsmasq', '-k', '-C', '/etc/dnsmasq.conf'], '/var/log/dnsmasq.out')


def cfg_unbound():                      # local caching resolver on alpha and beta
    write('/etc/unbound/unbound.conf', '''server:
    interface: 127.0.0.1
    access-control: 127.0.0.0/8 allow
    do-not-query-localhost: no
    cache-min-ttl: 300
    local-zone: "test." transparent
    chroot: ""
    username: ""
    use-syslog: no
    logfile: "/var/log/unbound.log"
    pidfile: "/run/unbound.pid"
forward-zone:
    name: "."
    forward-addr: %s
''' % E['DNS_IP'])
    run('unbound', '-c', '/etc/unbound/unbound.conf')
    write('/etc/resolv.conf', 'nameserver 127.0.0.1\n')


# ---- TLS files (section 7) ----
def tls_files(host):
    os.makedirs('/etc/lab-tls', exist_ok=True)
    for src, dst in ((host + '.crt', 'cert.pem'), (host + '.key', 'key.pem'),
                     ('ca.crt', 'ca.pem'), ('dh.pem', 'dh.pem')):
        shutil.copy('/lab/build/pki/' + src, '/etc/lab-tls/' + dst)
        os.chmod('/etc/lab-tls/' + dst, 0o644)


# ---- Postfix (section 8) ----
def postfix_base(fqdn, domain):
    tls_files(fqdn)
    write('/etc/postfix/main.cf', '''compatibility_level = 3.6
myhostname = %s
mydomain = %s
myorigin = %s
mynetworks = 127.0.0.0/8
inet_interfaces = all
inet_protocols = ipv4
home_mailbox = Maildir/
alias_maps =
alias_database =
maillog_file = /var/log/mail.log
biff = no
smtp_host_lookup = dns
smtp_dns_support_level = enabled
smtpd_tls_cert_file = /etc/lab-tls/cert.pem
smtpd_tls_key_file = /etc/lab-tls/key.pem
smtpd_tls_CAfile = /etc/lab-tls/ca.pem
smtp_tls_CAfile = /etc/lab-tls/ca.pem
smtpd_tls_security_level = may
smtp_tls_security_level = may
smtpd_tls_loglevel = 1
smtp_tls_loglevel = 1
queue_run_delay = 10s
minimal_backoff_time = 10s
maximal_backoff_time = 60s
smtp_connect_timeout = 5s
default_destination_concurrency_limit = 50
smtpd_client_connection_count_limit = 200
''' % (fqdn, domain, domain))


def cfg_postfix_alpha():
    postfix_base('mail.alpha.test', 'alpha.test')
    pc('-e', 'mydestination = alpha.test, localhost',
       'smtpd_relay_restrictions = permit_mynetworks, permit_sasl_authenticated, reject_unauth_destination',
       'smtpd_sasl_type = dovecot', 'smtpd_sasl_path = private/auth',
       'smtpd_milters = inet:127.0.0.1:8891', 'non_smtpd_milters = $smtpd_milters',
       'milter_default_action = accept', 'milter_protocol = 6')
    pc('-M', 'submission/inet=submission inet n - n - - smtpd')
    pc('-P', 'submission/inet/smtpd_tls_security_level=encrypt',
       'submission/inet/smtpd_tls_auth_only=yes',
       'submission/inet/smtpd_sasl_auth_enable=yes',
       'submission/inet/smtpd_relay_restrictions=permit_sasl_authenticated,reject',
       'submission/inet/milter_macro_daemon_name=ORIGINATING')
    pc('-F', '*/*/chroot=n')
    run('postfix', 'start')


def cfg_postfix_beta():
    postfix_base('mail.beta.test', 'beta.test')
    write('/etc/postfix/lab-local-recipients', 'bob OK\n')
    run('postmap', '/etc/postfix/lab-local-recipients')
    pc('-e', 'mydestination = beta.test, localhost',
       'local_recipient_maps = hash:/etc/postfix/lab-local-recipients',
       'smtpd_recipient_restrictions = reject_unlisted_recipient, permit_mynetworks, '
       'reject_unauth_destination, '
       'check_policy_service unix:private/policy-spf',
       'policy-spf_time_limit = 3600s', 'smtpd_milters = inet:127.0.0.1:8891',
       'milter_default_action = accept', 'milter_protocol = 6')
    pc('-M', 'policy-spf/unix=policy-spf unix - n n - 0 spawn user=nobody argv=/usr/bin/policyd-spf')
    pc('-F', '*/*/chroot=n')
    os.makedirs('/etc/postfix-policyd-spf-python', exist_ok=True)
    write('/etc/postfix-policyd-spf-python/policyd-spf.conf',
          'debugLevel = 1\nHELO_reject = False\nMail_From_reject = False\nPermError_reject = False\n'
          'TempError_Defer = False\nHeader_Type = AR\nAuthserv_Id = mail.beta.test\n')
    run('postfix', 'start')


def cfg_postfix_mx2():                  # backup MX: accepts beta.test mail, relays it to beta when it is back
    postfix_base('mx2.beta.test', 'beta.test')
    pc('-e', 'mydestination = localhost', 'relay_domains = beta.test',
       'transport_maps = hash:/etc/postfix/transport',
       'smtpd_relay_restrictions = permit_mynetworks, reject_unauth_destination')
    write('/etc/postfix/transport', 'beta.test smtp:[%s]\n' % E['BETA_IP'])
    run('postmap', '/etc/postfix/transport')
    pc('-F', '*/*/chroot=n')
    run('postfix', 'start')


# ---- Dovecot (section 8) ----
DOVECOT = '''protocols = imap
listen = *
log_path = /var/log/dovecot.log
mail_location = maildir:~/Maildir
auth_mechanisms = plain login
ssl_cert = </etc/lab-tls/cert.pem
ssl_key = </etc/lab-tls/key.pem
ssl_dh = </etc/lab-tls/dh.pem
namespace inbox {
  inbox = yes
}
passdb {
  driver = passwd-file
  args = scheme=PLAIN username_format=%n /etc/dovecot/users
}
userdb {
  driver = passwd
}
service imap-login {
  inet_listener imap {
    port = 143
  }
  inet_listener imaps {
    port = 0
  }
}
service auth {
  unix_listener /var/spool/postfix/private/auth {
    mode = 0660
    user = postfix
    group = postfix
  }
}
!include_try /etc/dovecot/tls_mode.conf
'''


def cfg_dovecot(host):
    tls_files(host)
    write('/etc/dovecot/users', 'alice:{PLAIN}%s\nbob:{PLAIN}%s\n' % (E['ALICE_PASS'], E['BOB_PASS']))
    write('/etc/dovecot/dovecot.conf', DOVECOT)
    write('/etc/dovecot/tls_mode.conf', 'ssl = required\ndisable_plaintext_auth = yes\n')   # rewritten by ctl_node.py
    run('dovecot')


# ---- OpenDKIM (section 9): 's' signs on alpha, 'v' verifies on beta ----
def cfg_opendkim(mode):
    os.makedirs('/run/opendkim', exist_ok=True)
    shutil.chown('/run/opendkim', 'opendkim', 'postfix')
    os.chmod('/run/opendkim', 0o775)
    run('pkill', '-9', '-x', 'opendkim')
    for stale in ('/run/opendkim/opendkim.pid', '/run/opendkim/opendkim.sock'):
        try:
            os.remove(stale)
        except FileNotFoundError:
            pass
    socket = 'inet:8891@127.0.0.1'
    conf = ('Mode %s\nSocket %s\nUserID opendkim\nUMask 000\nLogWhy yes\nPidFile /run/opendkim/opendkim.pid\nSyslog no\n'
            'RequireSafeKeys no\nCanonicalization relaxed/relaxed\nSignatureAlgorithm rsa-sha256\n'
            'AuthservID mail.beta.test\n' % (mode, socket))
    if mode == 's':
        conf += 'InternalHosts 10.10.1.0/24\nDomain alpha.test\nSelector mail\nKeyFile /lab/build/keys/alpha/mail.private\n'
    write('/etc/opendkim.conf', conf)
    daemon(['opendkim', '-f', '-x', '/etc/opendkim.conf'], '/var/log/opendkim.log')


if N == 'dns':
    cfg_dns()
elif N == 'alpha':
    cfg_unbound(); cfg_opendkim('s'); cfg_postfix_alpha(); cfg_dovecot('mail.alpha.test')
elif N == 'beta':
    cfg_unbound(); cfg_opendkim('v'); cfg_postfix_beta(); cfg_dovecot('mail.beta.test')
elif N == 'mx2':
    direct_dns(); cfg_postfix_mx2()
else:
    direct_dns()
