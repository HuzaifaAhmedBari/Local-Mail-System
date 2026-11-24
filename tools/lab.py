#!/usr/bin/env python3
"""tools/lab.py - control logic for the Local Mail System lab.

Standard library only, so `make doctor` works with the system python3 and
`make check` works without root. Anything that touches namespaces, bridges or
containerlab calls need_root() first.
"""
import argparse, base64, csv, glob, json, os, platform, re, shlex, shutil
import subprocess as sp, signal, sys, time, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def P(*a):
    return os.path.join(ROOT, *a)


def load_env(path=None):
    env = {}
    with open(path or P('config.env')) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip()
    return env


ENV = load_env()
os.environ.update(ENV)          # containerlab expands ${NODE_IMAGE} etc. from the environment
LAB = ENV['LAB']
BRIDGES = {'br-alpha': '10.10.1.99/24', 'br-beta': '10.10.2.99/24', 'br-svc': None}
USERS = {'alice': 2001, 'bob': 2002}
HOMES = {'alpha': 'data/alpha-home', 'beta': 'data/beta-home'}
INBOX_BOB = P('data/beta-home/bob/Maildir/new')
INBOX_ALICE = P('data/alpha-home/alice/Maildir/new')
NODE_IPS = {'alpha': ENV['ALPHA_IP'], 'beta': ENV['BETA_IP'], 'mx2': ENV['MX2_IP'], 'dns': ENV['DNS_IP']}
SERVICES = {'alpha': [25, 587, 143], 'beta': [25, 143], 'mx2': [25], 'dns': [53]}
HOSTS_TAG = '# mail-lab'
PCAPS = ['01_dns', '02_smtp_plain', '03_smtp_starttls', '04_imap', '05_spf_dkim']


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
def need_root():
    if os.geteuid() != 0:
        sys.exit('This command needs root: use make, or sudo -E venv/bin/python tools/lab.py <command>')


def sh(cmd, check=True, input=None, timeout=None):
    """Run a host command, return merged stdout+stderr as text."""
    if isinstance(cmd, str):
        cmd = shlex.split(cmd)
    cp = sp.run(cmd, input=input, stdout=sp.PIPE, stderr=sp.STDOUT, text=True,
                errors='replace', timeout=timeout, cwd=ROOT)
    if check and cp.returncode:
        raise RuntimeError('command failed (%d): %s\n%s' % (cp.returncode, ' '.join(cmd), cp.stdout))
    return cp.stdout


def stream(cmd, check=True):
    """Run a host command with its output shown live."""
    if isinstance(cmd, str):
        cmd = shlex.split(cmd)
    rc = sp.call(cmd, cwd=ROOT)
    if check and rc:
        raise RuntimeError('command failed (%d): %s' % (rc, ' '.join(cmd)))
    return rc


def cname(node):
    return 'clab-%s-%s' % (LAB, node)


def x(node, cmd, input=None, timeout=300):
    """docker exec in a node. Returns CompletedProcess (stdout holds stdout+stderr)."""
    if isinstance(cmd, str):
        cmd = shlex.split(cmd)
    return sp.run(['docker', 'exec', '-i', cname(node)] + list(cmd),
                  input='' if input is None else input, stdout=sp.PIPE, stderr=sp.STDOUT,
                  text=True, errors='replace', timeout=timeout)


def d(node, cmd, input=None, timeout=300):
    """docker exec that raises on failure and returns the output text."""
    cp = x(node, cmd, input, timeout)
    if cp.returncode:
        raise RuntimeError('%s: command failed (%d): %s\n%s' % (node, cp.returncode, cmd, cp.stdout))
    return cp.stdout


def pw(user):
    return ENV[user.upper() + '_PASS']


def ensure_netns(node):
    link = '/run/netns/' + cname(node)
    if os.path.exists(link):
        return
    pid = sh(['docker', 'inspect', '-f', '{{.State.Pid}}', cname(node)]).strip()
    os.makedirs('/run/netns', exist_ok=True)
    os.symlink('/proc/%s/ns/net' % pid, link)


def ns(node, *cmd, check=True):
    """Run a host binary inside a container's network namespace."""
    ensure_netns(node)
    return sh(['ip', 'netns', 'exec', cname(node)] + list(cmd), check=check)


def ctl(node, *args):
    return d(node, ['python3', '/lab/nodes/ctl_node.py', node] + list(args))


def wait_files(path, n=1, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        if os.path.isdir(path) and len(os.listdir(path)) >= n:
            return True
        time.sleep(0.25)
    return False


def newest(path):
    f = sorted(glob.glob(path + '/*'), key=os.path.getmtime)
    return f[-1] if f else None


def send(n=1, tag='M', plain=False, port=587, server='mail.alpha.test', user='alice',
         per_conn=1, keylog=None, sender='alice@alpha.test', to='bob@beta.test', out=None):
    """Send n messages with tools/mailclient.py from clienta."""
    cmd = ['python3', '/lab/tools/mailclient.py', '--server', server, '--port', str(port),
           '--sender', sender, '--to', to, '--count', str(n), '--per-conn', str(per_conn), '--run', tag]
    if user:
        cmd += ['--user', user, '--password', pw(user)]
    if plain:
        cmd.append('--plain')
    if keylog:
        cmd += ['--keylog', keylog]
    if out:
        cmd += ['--out', out]
    return d('clienta', cmd)


# --------------------------------------------------------------------------
# generated material: PKI, DKIM key, DNS zone (section 6, 7, 9)
# --------------------------------------------------------------------------
def pki(force=False):
    pd = P('build/pki')
    os.makedirs(pd, exist_ok=True)
    ca_key, ca_crt = pd + '/ca.key', pd + '/ca.crt'
    if force or not os.path.exists(ca_crt):
        sh(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', ca_key, '-out', ca_crt,
            '-days', '825', '-subj', '/CN=Mail Lab CA',
            '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign'])
    hosts = [('mail.alpha.test', ['alpha.test'], ENV['ALPHA_IP']),
             ('mail.beta.test', ['beta.test'], ENV['BETA_IP']),
             ('mx2.beta.test', [], ENV['MX2_IP'])]
    for fqdn, extra, ip in hosts:
        crt, key, csr = '%s/%s.crt' % (pd, fqdn), '%s/%s.key' % (pd, fqdn), '%s/%s.csr' % (pd, fqdn)
        if os.path.exists(crt) and not force:
            continue
        sh(['openssl', 'req', '-newkey', 'rsa:2048', '-nodes', '-keyout', key, '-out', csr, '-subj', '/CN=' + fqdn])
        ext = pd + '/' + fqdn + '.ext'
        san = ','.join(['DNS:' + fqdn] + ['DNS:' + e for e in extra] + ['IP:' + ip])
        open(ext, 'w').write('subjectAltName=%s\nbasicConstraints=CA:FALSE\n'
                             'keyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n' % san)
        sh(['openssl', 'x509', '-req', '-in', csr, '-CA', ca_crt, '-CAkey', ca_key, '-CAcreateserial',
            '-out', crt, '-days', '825', '-extfile', ext])
    if force or not os.path.exists(pd + '/dh.pem'):
        sh(['openssl', 'dhparam', '-dsaparam', '-out', pd + '/dh.pem', '2048'])   # -dsaparam: fast, lab only
    for f in glob.glob(pd + '/*'):
        os.chmod(f, 0o644)                                   # acceptable only inside this lab


def dkim_key(force=False):
    kd = P('build/keys/alpha')
    os.makedirs(kd, exist_ok=True)
    priv = kd + '/mail.private'
    if force or not os.path.exists(priv):
        # OpenDKIM 2.11 is more reliable with traditional PKCS#1 RSA keys
        # than with OpenSSL 3's default PKCS#8 output.
        sh(['openssl', 'genrsa', '-traditional', '-out', priv, '2048'])
    os.chmod(priv, 0o644)                                    # needed: key sits on a bind mount
    der = sp.run(['openssl', 'rsa', '-in', priv, '-pubout', '-outform', 'DER'],
                 stdout=sp.PIPE, stderr=sp.DEVNULL, check=True).stdout
    return base64.b64encode(der).decode()


def dns_conf(p):
    e = ENV
    full = 'v=DKIM1; k=rsa; p=' + p
    chunks = ','.join('"%s"' % full[i:i + 200] for i in range(0, len(full), 200))   # TXT strings are <=255 bytes
    lines = ['no-resolv', 'no-hosts', 'bind-interfaces', 'listen-address=' + e['DNS_IP'],
             'cache-size=0', 'local-ttl=60', 'log-queries', 'log-facility=-',
             'local=/alpha.test/beta.test/soft.test/none.test/',
             'host-record=mail.alpha.test,' + e['ALPHA_IP'],
             'host-record=mail.beta.test,' + e['BETA_IP'],
             'host-record=mx2.beta.test,' + e['MX2_IP'],
             'host-record=soft.test,10.10.3.98', 'host-record=none.test,10.10.3.99',
             'mx-host=alpha.test,mail.alpha.test,10',
             'mx-host=beta.test,mail.beta.test,10',
             'mx-host=beta.test,mx2.beta.test,20',
             'txt-record=alpha.test,"v=spf1 ip4:%s -all"' % e['ALPHA_IP'],
             'txt-record=beta.test,"v=spf1 ip4:%s ip4:%s -all"' % (e['BETA_IP'], e['MX2_IP']),
             'txt-record=soft.test,"v=spf1 ~all"',
             'txt-record=mail._domainkey.alpha.test,' + chunks, '']
    os.makedirs(P('build/dns'), exist_ok=True)
    open(P('build/dns/dnsmasq.conf'), 'w').write('\n'.join(lines))


def gen(force=False):
    """Create the lab CA, server certificates, DH parameters, DKIM key and DNS zone under build/."""
    pki(force)
    dns_conf(dkim_key(force))
    for f in glob.glob(P('build/dns/*')):
        os.chmod(f, 0o644)


# --------------------------------------------------------------------------
# state: mailboxes and queues
# --------------------------------------------------------------------------
def _own(path, uid, mode):
    os.chown(path, uid, uid)
    os.chmod(path, mode)


def maildirs():
    """Recreate every Maildir (empty) with the right owner."""
    need_root()
    for node, home in HOMES.items():
        os.makedirs(P(home), exist_ok=True)
        for user, uid in USERS.items():
            base = P(home, user)
            os.makedirs(base, exist_ok=True)
            _own(base, uid, 0o755)
            md = base + '/Maildir'
            if os.path.exists(md):
                shutil.rmtree(md)
            os.makedirs(md)
            _own(md, uid, 0o700)
            for sub in ('new', 'cur', 'tmp'):
                os.makedirs(md + '/' + sub)
                _own(md + '/' + sub, uid, 0o700)


def reset():
    """Empty the Postfix queues on alpha, beta and mx2 and recreate all Maildirs."""
    for n in ('alpha', 'beta', 'mx2'):
        x(n, ['postsuper', '-d', 'ALL'])
    maildirs()


def queue_len(node='alpha'):
    out = x(node, ['postqueue', '-p']).stdout
    m = re.search(r'in (\d+) Requests?', out)
    return int(m.group(1)) if m else 0


# --------------------------------------------------------------------------
# switches (TLS, SPF/DKIM checks, DKIM selector) and DNS cache
# --------------------------------------------------------------------------
def set_tls(mode):
    assert mode in ('on', 'off')
    for n in ('alpha', 'beta', 'mx2'):
        ctl(n, 'tls', mode)


def set_auth(mode):
    assert mode in ('on', 'off')
    ctl('beta', 'auth', mode)


def set_selector(sel):
    """'bad' makes alpha sign with a selector that has no DNS record (case A4); 'mail' restores it."""
    assert sel in ('bad', 'mail')
    ctl('alpha', 'selector', sel)


def flush_dns():
    for n in ('alpha', 'beta'):
        ctl(n, 'restart-unbound')


PRIME = [('MX', 'beta.test'), ('MX', 'alpha.test'), ('A', 'mail.beta.test'), ('A', 'mx2.beta.test'),
         ('A', 'mail.alpha.test'), ('TXT', 'alpha.test'), ('TXT', 'beta.test'), ('TXT', 'soft.test'),
         ('TXT', 'none.test'), ('TXT', 'mail._domainkey.alpha.test')]


def prime_dns():
    for n in ('alpha', 'beta'):
        for t, name in PRIME:
            x(n, ['dig', '+short', '+time=3', '+tries=1', t, name])


# --------------------------------------------------------------------------
# network impairments (section 11)
# --------------------------------------------------------------------------
def _transit():
    return [('r1', ENV['R1_TRANSIT_IF']), ('r2', ENV['R2_TRANSIT_IF'])]


def clear():
    for r, i in _transit():
        ns(r, 'tc', 'qdisc', 'del', 'dev', i, 'root', check=False)


def condition(rtt, loss=0, rate=None):
    """Half of the delay on each transit interface; loss per direction; optional tbf rate (Mbit)."""
    clear()
    rtt, loss = float(rtt), float(loss)
    for r, i in _transit():
        cmd = ['tc', 'qdisc', 'add', 'dev', i, 'root', 'handle', '1:', 'netem', 'delay', '%gms' % (rtt / 2)]
        if loss:
            cmd += ['loss', '%g%%' % loss]
        ns(r, *cmd)
        if rate:
            ns(r, 'tc', 'qdisc', 'add', 'dev', i, 'parent', '1:1', 'handle', '10:', 'tbf',
               'rate', '%gmbit' % float(rate), 'burst', '%dkbit' % max(32, int(12 * float(rate))),
               'latency', '400ms')


# --------------------------------------------------------------------------
# bring-up and tear-down
# --------------------------------------------------------------------------
def configure_routers():
    r = ENV
    plan = {'r1': [('eth1', r['R1_ALPHA'] + '/24'), ('eth2', r['R1_SVC'] + '/24'), ('eth3', r['R1_TRANSIT'] + '/30')],
            'r2': [('eth1', r['R2_BETA'] + '/24'), ('eth2', r['R2_TRANSIT'] + '/30')]}
    for router, ifs in plan.items():
        for ifn, cidr in ifs:
            ns(router, 'ip', 'addr', 'replace', cidr, 'dev', ifn)
            ns(router, 'ip', 'link', 'set', ifn, 'up')
        ns(router, 'sysctl', '-w', 'net.ipv4.ip_forward=1')
    end = time.time() + 90
    while time.time() < end:                                  # static routes appear once the next hop is reachable
        if '10.10.2.0/24' in x('r1', ['vtysh', '-c', 'show ip route']).stdout and \
           '10.10.1.0/24' in x('r2', ['vtysh', '-c', 'show ip route']).stdout and \
           '10.10.3.0/24' in x('r2', ['vtysh', '-c', 'show ip route']).stdout:
            return
        time.sleep(1)
    print('WARNING: FRR static routes are not installed yet; check docker exec %s vtysh -c "show ip route"' % cname('r1'))


def wait_ready(timeout=120):
    end = time.time() + timeout
    for node, ports in SERVICES.items():
        for p in ports:
            while True:
                cp = x(node, ['python3', '/lab/tools/socktest.py', 'port', NODE_IPS[node], str(p)])
                if cp.returncode == 0:
                    break
                if time.time() > end:
                    raise RuntimeError('%s port %d did not come up; check /var/log in the container '
                                       '(docker exec %s ls /var/log)' % (node, p, cname(node)))
                time.sleep(1)
        print('  %-6s ready (%s)' % (node, ', '.join(map(str, ports))))


def up():
    need_root()
    if sp.call(['docker', 'image', 'inspect', ENV['NODE_IMAGE']], stdout=sp.DEVNULL, stderr=sp.DEVNULL):
        raise RuntimeError('node image missing: run make build first')
    gen()
    maildirs()
    for br in BRIDGES:                                        # containerlab bridge nodes must already exist
        if not os.path.exists('/sys/class/net/' + br):
            sh(['ip', 'link', 'add', 'name', br, 'type', 'bridge'])
        sh(['ip', 'link', 'set', br, 'up'])
    nf = '/proc/sys/net/bridge/bridge-nf-call-iptables'       # keep Docker's iptables out of L2 traffic
    if os.path.exists(nf):
        open(nf, 'w').write('0')
    stream(['containerlab', 'deploy', '-t', 'topology.clab.yml', '--reconfigure'])
    configure_routers()
    print('waiting for services ...')
    wait_ready()
    print('lab is up. Try: make demo')


def unhost():
    if os.geteuid() != 0 or not os.path.exists('/etc/hosts'):
        return
    keep = [l for l in open('/etc/hosts') if HOSTS_TAG not in l]
    open('/etc/hosts', 'w').write(''.join(keep))


def host_access():
    """Give the host an address on each LAN bridge and names for the servers (for Thunderbird)."""
    need_root()
    for br, addr in BRIDGES.items():
        if addr:
            sh(['ip', 'addr', 'replace', addr, 'dev', br])
    unhost()
    txt = open('/etc/hosts').read()
    if txt and not txt.endswith('\n'):
        txt += '\n'
    txt += '%s mail.alpha.test %s\n%s mail.beta.test %s\n%s mx2.beta.test %s\n' % (
        ENV['ALPHA_IP'], HOSTS_TAG, ENV['BETA_IP'], HOSTS_TAG, ENV['MX2_IP'], HOSTS_TAG)
    open('/etc/hosts', 'w').write(txt)
    print('host reachable as 10.10.1.99 and 10.10.2.99; /etc/hosts updated; import build/pki/ca.crt into Thunderbird')


def down():
    need_root()
    stream(['containerlab', 'destroy', '-t', 'topology.clab.yml', '--cleanup'], check=False)
    unhost()
    for br in BRIDGES:
        sh(['ip', 'link', 'del', br], check=False)


# --------------------------------------------------------------------------
# build, doctor, version pinning
# --------------------------------------------------------------------------
def build():
    if not os.path.isdir(P('venv')):
        stream(['python3', '-m', 'venv', 'venv'])
    pip = P('venv/bin/pip')
    if os.path.exists(P('requirements.lock')):
        stream([pip, 'install', '-r', 'requirements.lock'])
    else:
        stream([pip, 'install', '-r', 'requirements.txt'])
        open(P('requirements.lock'), 'w').write(sh([pip, 'freeze']))      # pins what was installed
    stream(['docker', 'build', '-t', ENV['NODE_IMAGE'], '-f', 'docker/Dockerfile.node', 'docker'])
    stream(['docker', 'pull', ENV['FRR_IMAGE']])
    print('build done')


def kernel_ok():
    sh(['ip', 'link', 'del', 'nt0'], check=False)
    try:
        sh(['ip', 'link', 'add', 'nt0', 'type', 'dummy'])
        sh(['tc', 'qdisc', 'add', 'dev', 'nt0', 'root', 'handle', '1:', 'netem', 'delay', '10ms', 'loss', '1%'])
        sh(['tc', 'qdisc', 'add', 'dev', 'nt0', 'parent', '1:1', 'handle', '10:', 'tbf', 'rate', '1mbit',
            'burst', '32kbit', 'latency', '400ms'])
        return True
    except Exception:
        return False
    finally:
        sh(['ip', 'link', 'del', 'nt0'], check=False)


def doctor():
    bad = [0]

    def show(tag, msg):
        print('[%s] %s' % (tag, msg))
        if tag == 'FAIL':
            bad[0] += 1

    show('OK' if os.geteuid() == 0 else 'FAIL', 'running as root (use sudo -E)')
    osr = dict(l.strip().split('=', 1) for l in open('/etc/os-release') if '=' in l)
    pretty = osr.get('PRETTY_NAME', '').strip('"')
    show('OK' if 'Ubuntu' in pretty else 'WARN', 'OS: %s, kernel %s' % (pretty, platform.release()))
    show('OK' if ' ' not in ROOT else 'FAIL', 'repo path has no spaces: ' + ROOT)
    show('OK' if not ROOT.startswith('/mnt/') else 'FAIL', 'repo is on the Linux filesystem (not /mnt/c)')
    for tool in ('docker', 'containerlab', 'tshark', 'tcpdump', 'ip', 'tc', 'dig', 'swaks', 'git'):
        show('OK' if shutil.which(tool) else 'FAIL', 'command: ' + tool)
    show('OK' if sp.call(['docker', 'info'], stdout=sp.DEVNULL, stderr=sp.DEVNULL) == 0 else 'FAIL', 'docker daemon reachable')
    if os.geteuid() == 0:
        show('OK' if kernel_ok() else 'FAIL', 'kernel supports tc netem and tbf (NETEM_TBF_OK)')
    mem = int(re.search(r'MemTotal:\s+(\d+)', open('/proc/meminfo').read()).group(1)) / 1048576
    show('OK' if mem >= 7.5 else 'WARN', 'RAM %.1f GB (8 GB minimum, 16 recommended)' % mem)
    free = shutil.disk_usage(ROOT).free / 1e9
    show('OK' if free >= 20 else 'WARN', 'free disk %.0f GB (20 GB needed)' % free)
    vp = P('venv/bin/python')
    if os.path.exists(vp):
        ok = sp.call([vp, '-c', 'import pandas, matplotlib, inotify_simple, pypdf'],
                     stdout=sp.DEVNULL, stderr=sp.DEVNULL) == 0
        show('OK' if ok else 'FAIL', 'venv has pandas, matplotlib, inotify_simple, pypdf')
    else:
        show('WARN', 'venv missing: run make build')
    for img in (ENV['NODE_IMAGE'], ENV['FRR_IMAGE']):
        have = sp.call(['docker', 'image', 'inspect', img], stdout=sp.DEVNULL, stderr=sp.DEVNULL) == 0
        show('OK' if have else 'WARN', 'image present: %s%s' % (img, '' if have else ' (run make build)'))
    print('doctor: %s' % ('all required checks passed' if not bad[0] else '%d check(s) failed' % bad[0]))
    return bad[0] == 0


def pin_versions():
    lines = ['# versions.lock - generated ' + time.strftime('%Y-%m-%d %H:%M:%S')]

    def add(k, v):
        lines.append('%s=%s' % (k, ' '.join(str(v).split())))

    osr = dict(l.strip().split('=', 1) for l in open('/etc/os-release') if '=' in l)
    add('os', osr.get('PRETTY_NAME', '').strip('"'))
    add('kernel', platform.release())
    cpu = re.search(r'model name\s*:\s*(.+)', open('/proc/cpuinfo').read())
    add('cpu', cpu.group(1) if cpu else platform.machine())
    add('cpu_threads', os.cpu_count())
    add('ram_gb', round(int(re.search(r'MemTotal:\s+(\d+)', open('/proc/meminfo').read()).group(1)) / 1048576, 1))
    add('python', platform.python_version())
    add('docker', sh(['docker', '--version'], check=False))
    out = sh(['containerlab', 'version'], check=False)
    m = re.search(r'version:\s*(\S+)', out)
    clab = m.group(1) if m else 'unknown'
    add('containerlab', clab)
    add('frr_image', ENV['FRR_IMAGE'])
    add('frr_digest', sh(['docker', 'image', 'inspect', ENV['FRR_IMAGE'], '--format', '{{index .RepoDigests 0}}'], check=False))
    add('node_image', ENV['NODE_IMAGE'])
    add('node_image_id', sh(['docker', 'image', 'inspect', ENV['NODE_IMAGE'], '--format', '{{.Id}}'], check=False))
    pk = sh(['docker', 'run', '--rm', ENV['NODE_IMAGE'], 'dpkg-query', '-W', '-f', '${Package}=${Version} ',
             'postfix', 'dovecot-core', 'opendkim', 'postfix-policyd-spf-python', 'dnsmasq', 'unbound', 'swaks',
             'python3-aiosmtpd'], check=False)
    add('node_packages', pk)
    open(P('versions.lock'), 'w').write('\n'.join(lines) + '\n')
    cfg = open(P('config.env')).read()
    if m and re.search(r'^CLAB_VERSION=unset', cfg, re.M):
        open(P('config.env'), 'w').write(re.sub(r'^CLAB_VERSION=unset', 'CLAB_VERSION=' + clab, cfg, flags=re.M))
    print('versions.lock written')


def fix_owner():
    """Hand root-created output back to the user who ran sudo."""
    uid, gid = os.environ.get('SUDO_UID'), os.environ.get('SUDO_GID')
    if os.geteuid() != 0 or not uid:
        return
    uid, gid = int(uid), int(gid)
    for top in ('results', 'captures', 'evidence', 'build', 'versions.lock', 'config.env'):
        path = P(top)
        if os.path.isfile(path):
            os.lchown(path, uid, gid)
        for root, dirs, files in os.walk(path):
            for n in dirs + files:
                os.lchown(os.path.join(root, n), uid, gid)
        if os.path.exists(path):
            os.lchown(path, uid, gid)


# --------------------------------------------------------------------------
# packet captures (section 12) and evidence
# --------------------------------------------------------------------------
class Capture:
    """tshark in a router namespace (node=...) or on a host bridge (node=None)."""

    def __init__(self, pcap, iface, filt, node=None):
        self.pcap, self.iface, self.filt, self.node = pcap, iface, filt, node
        self.tmp_pcap = '/tmp/local-mail-system-' + os.path.basename(pcap)

    def __enter__(self):
        # dumpcap drops to the wireshark user, which cannot traverse the
        # private WSL home directory.  Capture in /tmp, then copy the finished
        # file back as root in __exit__.
        try:
            os.remove(self.tmp_pcap)
        except FileNotFoundError:
            pass
        cmd = ['tshark', '-q', '-i', self.iface, '-f', self.filt, '-w', self.tmp_pcap]
        if self.node:
            ensure_netns(self.node)
            cmd = ['ip', 'netns', 'exec', cname(self.node)] + cmd
        self.p = sp.Popen(cmd, stdout=sp.DEVNULL, stderr=sp.PIPE, text=True)
        time.sleep(2)
        return self

    def __exit__(self, *a):
        time.sleep(3)
        # tshark delegates capture to dumpcap.  SIGTERM can kill tshark
        # before dumpcap flushes the pcapng footer, leaving header-only files.
        # SIGINT is tshark's graceful stop signal and lets dumpcap flush.
        self.p.send_signal(signal.SIGINT)
        try:
            self.p.wait(timeout=10)
        except sp.TimeoutExpired:
            self.p.kill()
            self.p.wait()
        err = self.p.stderr.read().strip() if self.p.stderr else ''
        if self.p.returncode and err:
            print('  tshark failed (%d): %s' % (self.p.returncode, err[-500:]))
        if os.path.exists(self.tmp_pcap):
            shutil.copyfile(self.tmp_pcap, self.pcap)
            os.chmod(self.pcap, 0o644)
            os.remove(self.tmp_pcap)
        time.sleep(0.5)


def pcap_csv(pcap, out):
    cp = sp.run(['tshark', '-r', pcap, '-T', 'fields', '-E', 'header=y', '-E', 'separator=,', '-E', 'quote=d',
                 '-e', 'frame.number', '-e', 'frame.time_relative', '-e', 'ip.src', '-e', 'ip.dst',
                 '-e', '_ws.col.Protocol', '-e', '_ws.col.Info'], stdout=sp.PIPE, stderr=sp.DEVNULL, text=True)
    open(out, 'w').write(cp.stdout)


def captures():
    """Produce the five required .pcapng files and a packet list for each in evidence/."""
    need_root()
    os.makedirs(P('captures/keylogs'), exist_ok=True)
    os.makedirs(P('captures/screenshots'), exist_ok=True)
    os.makedirs(P('evidence'), exist_ok=True)
    cap = lambda name: P('captures', name + '.pcapng')
    clear()
    set_tls('on')
    set_auth('on')

    print('01 DNS (alpha asks MX and A, cold cache)')
    reset()
    flush_dns()
    with Capture(cap('01_dns'), 'eth2', 'port 53', 'r1'):
        for t, name in (('MX', 'beta.test'), ('A', 'mail.beta.test'), ('A', 'mx2.beta.test')):
            x('alpha', ['dig', '+tries=1', t, name])
            time.sleep(0.5)

    print('02 plain SMTP (TLS off, alpha relays to beta)')
    reset()
    set_tls('off')
    with Capture(cap('02_smtp_plain'), ENV['R1_TRANSIT_IF'], 'tcp port 25', 'r1'):
        send(1, 'C02', plain=True)
        wait_files(INBOX_BOB, 1, 30)
    set_tls('on')

    print('03 SMTP STARTTLS (relay on the wire, plus a direct session with a key log)')
    reset()
    keys = P('captures/keylogs/03_smtp_starttls.keys')
    if os.path.exists(keys):
        os.remove(keys)
    with Capture(cap('03_smtp_starttls'), ENV['R1_TRANSIT_IF'], 'tcp port 25', 'r1'):
        send(1, 'C03')
        send(1, 'C03d', server='mail.beta.test', port=25, user='',
             keylog='/lab/captures/keylogs/03_smtp_starttls.keys')
        wait_files(INBOX_BOB, 2, 30)

    print('04 IMAP (TLS off so commands are readable)')
    reset()
    send(1, 'C04')
    wait_files(INBOX_BOB, 1, 30)
    set_tls('off')
    with Capture(cap('04_imap'), 'br-beta', 'tcp port 143'):
        d('clientb', ['python3', '/lab/tools/imapclient.py', '--plain', '--show-headers'])
    set_tls('on')

    print('05 SPF and DKIM TXT lookups made by beta during delivery (cold cache)')
    reset()
    flush_dns()
    with Capture(cap('05_spf_dkim'), 'eth2', 'port 53', 'r1'):
        send(1, 'C05')
        wait_files(INBOX_BOB, 1, 30)

    for n in PCAPS:
        size = os.path.getsize(cap(n)) if os.path.exists(cap(n)) else 0
        if size:
            pcap_csv(cap(n), P('evidence', n + '.csv'))
        print('  %-18s %s' % (n + '.pcapng', '%d bytes' % size if size else 'EMPTY - check tshark permissions'))
    fix_owner()
    print('captures done. Open them with: wireshark captures/<name>.pcapng')


def head_lines(path, prefixes=('authentication-results', 'dkim-signature', 'received-spf', 'subject')):
    t = open(path, 'rb').read().decode('latin1').replace('\r\n', '\n').split('\n\n', 1)[0]
    t = re.sub(r'\n[ \t]+', ' ', t)
    return [l for l in t.split('\n') if l.lower().startswith(prefixes)]


def evidence():
    need_root()
    out = P('evidence')
    os.makedirs(out, exist_ok=True)

    def save(name, text):
        open(os.path.join(out, name), 'w').write(text)

    save('r1_routes.txt', x('r1', ['vtysh', '-c', 'show ip route']).stdout)
    save('r2_routes.txt', x('r2', ['vtysh', '-c', 'show ip route']).stdout)
    save('traceroute.txt', x('clienta', ['traceroute', '-n', 'mail.beta.test']).stdout)
    save('ping.txt', x('clienta', ['ping', '-c', '5', 'mail.beta.test']).stdout)
    dig = ''
    for t, name in PRIME:
        dig += '$ dig +short %s %s\n%s\n' % (t, name, x('alpha', ['dig', '+short', t, name]).stdout)
    save('dns_checks.txt', dig)
    for n in ('alpha', 'beta', 'mx2'):
        save('maillog_%s.txt' % n, x(n, ['tail', '-n', '80', '/var/log/mail.log']).stdout)
        save('queue_%s.txt' % n, x(n, ['postqueue', '-p']).stdout)
        save('listen_%s.txt' % n, x(n, ['ss', '-ltn']).stdout)
    save('tc_qdisc.txt', ''.join('%s %s\n%s\n' % (r, i, ns(r, 'tc', 'qdisc', 'show', 'dev', i, check=False))
                                  for r, i in _transit()))
    f = newest(INBOX_BOB)
    save('headers_bob_latest.txt', '\n'.join(head_lines(f)) + '\n' if f else 'no message in bob Maildir\n')
    fix_owner()
    print('text evidence written to evidence/')


# --------------------------------------------------------------------------
# live demo (proposal 2.7)
# --------------------------------------------------------------------------
class Tee:
    def __init__(self, path):
        self.f, self.o = open(path, 'w'), sys.stdout

    def write(self, s):
        self.o.write(s)
        self.f.write(s)

    def flush(self):
        self.o.flush()
        self.f.flush()


def _wait_mid(mid, timeout=30):
    end = time.time() + timeout
    needle = mid.encode()
    while time.time() < end:
        for f in glob.glob(INBOX_BOB + '/*'):
            try:
                if needle in open(f, 'rb').read():
                    return time.time_ns()
            except OSError:
                pass
        time.sleep(0.01)
    return None


def _timed(tag):
    """Send one message; return delivery latency in ms (final DATA dot to file in bob's Maildir)."""
    local = P('results/raw/demo_sends.csv')
    os.makedirs(P('results/raw'), exist_ok=True)
    if os.path.exists(local):
        os.remove(local)
    send(1, tag, out='/lab/results/raw/demo_sends.csv')
    _, mid, t_dot = next(csv.reader(open(local)))
    t = _wait_mid(mid)
    return (t - int(t_dot)) / 1e6 if t else None


def demo(auto=False):
    need_root()
    sys.path.insert(0, P('tools'))
    import parse_headers
    os.makedirs(P('evidence'), exist_ok=True)
    real = sys.stdout
    sys.stdout = Tee(P('evidence/demo_run.txt'))
    auto = auto or os.environ.get('DEMO_AUTO') == '1' or not sys.stdin.isatty()

    def step(n, title):
        print('\n' + '=' * 70 + '\nSTEP %d: %s\n' % (n, title) + '=' * 70)
        if not auto:
            real.write('(press Enter to run) ')
            real.flush()
            input()

    try:
        clear()
        set_tls('on')
        set_auth('on')
        reset()
        step(1, 'Routing: show ip route on both routers and a traceroute across them')
        print(x('r1', ['vtysh', '-c', 'show ip route']).stdout)
        print(x('r2', ['vtysh', '-c', 'show ip route']).stdout)
        print(x('clienta', ['traceroute', '-n', 'mail.beta.test']).stdout)

        step(2, 'alice sends to bob (submission 587, STARTTLS, DKIM signing, MX relay); bob reads over IMAP')
        base = _timed('D2')
        print('delivered, latency %s ms' % ('%.1f' % base if base else 'NOT DELIVERED'))
        print(d('clientb', ['python3', '/lab/tools/imapclient.py', '--show-headers']))
        f = newest(INBOX_BOB)
        if f:
            print('verdict (spf, dkim): %s  <- expect (pass, pass)' % (parse_headers.verdict(f),))

        step(3, 'Forged message from the attacker (10.10.3.66) claiming alice@alpha.test')
        n_before = len(os.listdir(INBOX_BOB))
        d('attacker', ['python3', '/lab/tools/spoof.py', '--mode', 'forged', '--mail-from', 'alice@alpha.test', '--tag', 'demo3'])
        wait_files(INBOX_BOB, n_before + 1, 30)
        f = newest(INBOX_BOB)
        print('verdict (spf, dkim): %s  <- expect spf fail' % (parse_headers.verdict(f),))
        for l in head_lines(f):
            print('  ' + l)

        step(4, 'Add 100 ms RTT on the transit link and send again')
        condition(100, 0)
        prime_dns()
        slow = _timed('D4')
        print('latency with 100 ms RTT: %s ms (no delay: %s ms)' % (
            '%.1f' % slow if slow else 'n/a', '%.1f' % base if base else 'n/a'))
        clear()

        step(5, 'Saved packet traces')
        for n in PCAPS:
            print('  captures/%s.pcapng%s' % (n, '' if os.path.exists(P('captures', n + '.pcapng')) else '  (run make capture)'))
        print('Open one with: wireshark captures/03_smtp_starttls.pcapng')

        step(6, 'Clean up')
        clear()
        print('network conditions cleared; demo log saved to evidence/demo_run.txt')
    finally:
        sys.stdout = real
        fix_owner()


# --------------------------------------------------------------------------
# README / disclosure templates
# --------------------------------------------------------------------------
README = """# Local Mail System (CS3001 Computer Networks, Fall 2026)

Group [fill in]. Built by: [fill in - state the real contributions of each person].

## 1. Overview
Two mail domains (alpha.test, beta.test) with their own DNS (dnsmasq), Postfix, Dovecot, OpenDKIM and SPF,
two FRRouting routers (containerlab), tc netem/tbf impairments, Python tools, tshark captures and experiments.
Architecture diagram: docs/architecture.png. Proposal: docs/proposal.pdf. Report: docs/report/report.pdf.

## 2. Requirements
Ubuntu 22.04/24.04 (native or VM, not stock WSL), 8 GB RAM (16 recommended), 20 GB disk, internet for the
first build, sudo. The kernel must support tc netem and tbf. The repo path must contain no spaces.

## 3. One-time setup
    sudo apt update
    sudo DEBIAN_FRONTEND=noninteractive apt install -y git make curl jq build-essential python3 python3-venv python3-pip docker.io tshark tcpdump iproute2 dnsutils swaks bridge-utils inotify-tools graphviz poppler-utils xz-utils wireshark
    sudo usermod -aG docker,wireshark $USER      # then log out and back in
    curl -sL https://get.containerlab.dev -o clab_install.sh && sudo bash clab_install.sh
    make build                                    # venv, node image, FRR image

## 4. Bring the lab up
    make doctor && make build && make up
    make test            # stage tests: network, sockets, dns, mail, tls, auth (all must PASS)

Typical order for a full run: make up, make test, make demo, make capture, make evidence, make experiments,
make tables, then the manual work (screenshots, diagram, report), make scaffold if README/disclosure are missing,
make check, make package. make down stops everything.

## 5. Run the POC
    make demo      # expected: spf=pass and dkim=pass for alice to bob; spf=fail for the forged mail
For Thunderbird: sudo -E venv/bin/python tools/lab.py hostaccess, import build/pki/ca.crt, then
configure alice (mail.alpha.test, IMAP 143 and SMTP 587, STARTTLS) and bob (mail.beta.test, IMAP 143).

## 6. Reproduce the experiments
    make experiments    # 1 to 3 hours; or: sudo -E venv/bin/python tools/orchestrate.py latency|rtt|throughput|auth|quick
    make tables         # CSVs in results/csv, tables in results/tables, graphs in results/graphs, results/summary.md

## 7. Captures
    make capture        # captures/*.pcapng, packet lists in evidence/, key log in captures/keylogs/
    make evidence       # routing tables, traceroute, logs, headers in evidence/

## 8. Repository map
tools/lab.py (control), tools/stagetests.py (tests), tools/orchestrate.py (experiments),
tools/make_tables.py, tools/mailclient.py, imapclient.py, spoof.py, loadgen.py, watcher.py,
parse_headers.py, rtt_count.py, socktest.py, nodes/start_node.py and nodes/ctl_node.py (run inside containers),
docker/Dockerfile.node, topology.clab.yml, config.env. There are no shell scripts.

## 9. Troubleshooting
netem missing (use native Ubuntu or a VM), stale containers or bridges (make down), clock jumps (restart the lab),
ports in use (make down), Thunderbird certificate errors (import build/pki/ca.crt; use host names, not IPs).

## 10. Team, contribution statement and AI use
[fill in]. AI use is described in AI_DISCLOSURE.md.
"""

DISCLOSURE = """# AI-use disclosure (CS3001 Computer Networks, Fall 2026)

Group [fill in]. Written by [fill in].

## 1. Tools used
[fill in: tool name and version, for example Claude (model, date range)]

## 2. What each tool was used for
[fill in: planning, drafting configuration and scripts, debugging, report drafting - list only what really happened]
The implementation guide and the Python control tools (tools/lab.py, stagetests.py, socktest.py,
nodes/ctl_node.py) were drafted with AI assistance.

## 3. My own work
[fill in: what you wrote, decided, ran, measured and understood without AI]

## 4. How AI-supplied material was checked
[fill in: for every AI-supplied command, configuration or paragraph, which stage test or measurement checked it,
and what you changed or rejected. See the stage-test output and experiment results.]

## 5. Responsibility
[fill in: statement that you are responsible for the submitted work]
"""


def scaffold():
    made = []
    for path, text in (('README.md', README), ('AI_DISCLOSURE.md', DISCLOSURE)):
        if not os.path.exists(P(path)) or os.path.getsize(P(path)) == 0:
            os.makedirs(os.path.dirname(P(path)), exist_ok=True)
            open(P(path), 'w').write(text)
            made.append(path)
    print('created: %s' % (', '.join(made) if made else 'nothing (files already exist)'))


# --------------------------------------------------------------------------
# submission check and package (section 15)
# --------------------------------------------------------------------------
def _csv_ok(path):
    rows = list(csv.DictReader(open(path)))
    conds = sorted({r['condition'] for r in rows})
    short = [c for c in conds if len({r['run'] for r in rows if r['condition'] == c}) < 3]
    return len(conds), short


def check():
    res = {'MISS': 0, 'FAIL': 0}

    def rep(tag, msg):
        print('[%s] %s' % (tag, msg))
        if tag in res:
            res[tag] += 1

    for f in ('README.md', 'AI_DISCLOSURE.md', 'Makefile', 'config.env', 'topology.clab.yml', 'versions.lock',
              'requirements.lock', 'docs/proposal.pdf', 'docs/architecture.png', 'docs/report/report.pdf',
              'results/summary.md', 'docker/Dockerfile.node', 'nodes/start_node.py', 'nodes/ctl_node.py',
              'evidence/demo_run.txt'):
        rep('OK' if os.path.exists(P(f)) else 'MISS', f)
    for f in ('lab', 'stagetests', 'socktest', 'mailclient', 'imapclient', 'watcher', 'spoof',
              'loadgen', 'parse_headers', 'rtt_count', 'orchestrate', 'make_tables'):
        rep('OK' if os.path.exists(P('tools', f + '.py')) else 'MISS', 'tools/%s.py' % f)
    scripts = [f for f in glob.glob(P('**/*.sh'), recursive=True) if '/venv/' not in f and '/build/' not in f]
    rep('OK' if not scripts else 'FAIL', 'no shell scripts in the repo' + (': ' + ', '.join(scripts) if scripts else ''))
    pc = glob.glob(P('captures/*.pcapng'))
    rep('OK' if len(pc) >= 5 and all(os.path.getsize(f) > 0 for f in pc) else 'MISS',
        '%d non-empty .pcapng files in captures/ (need 5)' % len(pc))
    for n in PCAPS:
        if not os.path.exists(P('captures', n + '.pcapng')):
            rep('MISS', 'captures/%s.pcapng' % n)
    shots = glob.glob(P('captures/screenshots/*.png'))
    rep('OK' if len(shots) >= 5 else 'MISS', '%d annotated screenshots (need at least 5, ten recommended)' % len(shots))
    graphs = glob.glob(P('results/graphs/*.png'))
    rep('OK' if len(graphs) >= 4 else 'MISS', '%d graphs (need at least 4)' % len(graphs))
    for name in ('latency', 'rtt', 'throughput', 'auth'):
        path = P('results/csv', name + '.csv')
        if not os.path.exists(path):
            rep('MISS', 'results/csv/%s.csv' % name)
            continue
        n, short = _csv_ok(path)
        rep('OK' if n >= 3 and not short else 'FAIL',
            '%s.csv: %d conditions%s' % (name, n, '; fewer than 3 runs in ' + ','.join(short) if short else ', 3+ runs each'))
    rp = P('docs/report/report.pdf')
    if os.path.exists(rp):
        try:
            from pypdf import PdfReader
            pages = len(PdfReader(rp).pages)
            rep('OK' if 6 <= pages <= 10 else 'FAIL', 'report is %d pages (6 to 10)' % pages)
        except ImportError:
            rep('FAIL', 'pypdf missing: run with venv/bin/python')
    for f in ('README.md', 'AI_DISCLOSURE.md'):
        if os.path.exists(P(f)):
            rep('FAIL' if '[fill in' in open(P(f)).read().lower() else 'OK', 'no [fill in] left in ' + f)
    print('check: %d MISS, %d FAIL' % (res['MISS'], res['FAIL']))
    return res['MISS'] == 0 and res['FAIL'] == 0

def package():
    need_root()
    pin_versions()
    if not check():
        raise SystemExit('make check failed; fix the items above before packaging')
    uid = os.environ.get('SUDO_UID')
    g = ['git', '-c', 'safe.directory=*', '-c', 'user.name=' + (sh(['git', 'config', 'user.name'], check=False).strip() or 'Lab Student'),
         '-c', 'user.email=' + (sh(['git', 'config', 'user.email'], check=False).strip() or 'student@lab.test')]
    if not os.path.isdir(P('.git')):
        sh(g + ['init'])
    sh(g + ['add', '-A'])
    sh(g + ['commit', '-m', 'Submission snapshot'], check=False)
    files = [f for f in sh(g + ['ls-files']).splitlines() if os.path.isfile(P(f))]
    zp = os.path.abspath(P('..', 'CN_Local_Mail_System_Submission.zip'))
    with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(P(f), 'local-mail-system/' + f)
    if uid:
        os.chown(zp, int(uid), int(os.environ.get('SUDO_GID', uid)))
    fix_owner()
    print('wrote %s (%d files; build/, data/, venv/ excluded)' % (zp, len(files)))


__all__ = ['ENV', 'LAB', 'ROOT', 'P', 'sh', 'stream', 'x', 'd', 'pw', 'ns', 'ctl', 'send', 'wait_files', 'newest',
           'gen', 'maildirs', 'reset', 'queue_len', 'set_tls', 'set_auth', 'set_selector', 'flush_dns',
           'prime_dns', 'condition', 'clear', 'up', 'down', 'build', 'doctor', 'pin_versions', 'host_access',
           'captures', 'evidence', 'demo', 'scaffold', 'check', 'package', 'fix_owner', 'ensure_netns', 'need_root']


def main():
    """Single Python command-line entry point for all lab control actions."""
    ap = argparse.ArgumentParser(description='Local Mail System lab controller')
    sub = ap.add_subparsers(dest='cmd', required=True)
    simple = {
        'doctor': 'check the host', 'build': 'build the environment', 'up': 'start the lab',
        'down': 'stop the lab', 'capture': 'create packet captures', 'evidence': 'write evidence',
        'check': 'check submission completeness', 'package': 'create the submission zip',
        'reset': 'reset queues and mailboxes', 'flush-dns': 'clear DNS caches',
        'prime-dns': 'warm DNS caches', 'hostaccess': 'configure host access',
        'clear': 'remove network conditions', 'chown': 'restore output ownership',
        'pin': 'write dependency versions', 'scaffold': 'create templates',
    }
    for name, helptext in simple.items():
        sub.add_parser(name, help=helptext)
    p = sub.add_parser('demo', help='run the live demo')
    p.add_argument('--auto', action='store_true')
    p = sub.add_parser('tls', help='turn TLS on or off')
    p.add_argument('mode', choices=['on', 'off'])
    p = sub.add_parser('auth', help='turn beta authentication checks on or off')
    p.add_argument('mode', choices=['on', 'off'])
    p = sub.add_parser('selector', help='choose alpha DKIM selector')
    p.add_argument('name', choices=['bad', 'mail'])
    p = sub.add_parser('cond', help='apply RTT/loss/rate conditions')
    p.add_argument('rtt', type=float)
    p.add_argument('loss', type=float)
    p.add_argument('rate', type=float, nargs='?')
    a = ap.parse_args()
    root_cmds = set(simple) - {'doctor', 'build', 'check'} | {'demo', 'tls', 'auth', 'selector', 'cond'}
    if a.cmd in root_cmds:
        need_root()
    if a.cmd == 'doctor':
        return 0 if doctor() else 1
    if a.cmd == 'check':
        return 0 if check() else 1
    actions = {'build': build, 'up': up, 'down': down, 'capture': captures, 'evidence': evidence,
               'package': package, 'reset': reset, 'flush-dns': flush_dns, 'prime-dns': prime_dns,
               'hostaccess': host_access, 'clear': clear, 'chown': fix_owner, 'pin': pin_versions,
               'scaffold': scaffold}
    if a.cmd in actions:
        actions[a.cmd]()
    elif a.cmd == 'demo':
        demo(a.auto)
    elif a.cmd == 'tls':
        set_tls(a.mode)
    elif a.cmd == 'auth':
        set_auth(a.mode)
    elif a.cmd == 'selector':
        set_selector(a.name)
    elif a.cmd == 'cond':
        condition(a.rtt, a.loss, a.rate)
        print('condition applied: RTT %g ms, loss %g%% each way%s' %
              (a.rtt, a.loss, ', rate %g Mbit' % a.rate if a.rate else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
