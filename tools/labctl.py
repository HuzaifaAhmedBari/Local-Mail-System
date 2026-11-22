#!/usr/bin/env python3
"""tools/labctl.py - command line for the lab. Use through make, or:
    sudo -E venv/bin/python tools/labctl.py <command>
"""
import argparse, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lab


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name, helptext in (('doctor', 'check the host'), ('build', 'venv, node image, FRR image'),
                           ('up', 'start the lab'), ('down', 'stop the lab and remove bridges'),
                           ('capture', 'make the five .pcapng files'), ('evidence', 'write text evidence'),
                           ('check', 'submission check'), ('package', 'pin versions, check, zip'),
                           ('reset', 'empty queues and mailboxes'), ('flush-dns', 'cold DNS caches'),
                           ('prime-dns', 'warm DNS caches'), ('hostaccess', 'host address and /etc/hosts for Thunderbird'),
                           ('clear', 'remove netem/tbf'), ('chown', 'give outputs back to the sudo user'),
                           ('pin', 'write versions.lock'), ('scaffold', 'create README and disclosure templates')):
        sub.add_parser(name, help=helptext)
    p = sub.add_parser('demo', help='live demo, six steps')
    p.add_argument('--auto', action='store_true', help='do not pause between steps')
    p = sub.add_parser('tls', help='TLS on or off')
    p.add_argument('mode', choices=['on', 'off'])
    p = sub.add_parser('auth', help='SPF/DKIM verification on beta on or off')
    p.add_argument('mode', choices=['on', 'off'])
    p = sub.add_parser('selector', help='DKIM selector on alpha (bad = no DNS record)')
    p.add_argument('name', choices=['bad', 'mail'])
    p = sub.add_parser('cond', help='RTT in ms, loss in %% per direction, optional rate in Mbit')
    p.add_argument('rtt', type=float)
    p.add_argument('loss', type=float)
    p.add_argument('rate', type=float, nargs='?')
    a = ap.parse_args()

    root_cmds = {'up', 'down', 'capture', 'evidence', 'package', 'reset', 'flush-dns', 'prime-dns', 'hostaccess',
                 'clear', 'cond', 'tls', 'auth', 'selector', 'demo', 'pin'}
    if a.cmd in root_cmds:
        lab.need_root()
    if a.cmd == 'doctor':
        return 0 if lab.doctor() else 1
    if a.cmd == 'check':
        return 0 if lab.check() else 1
    simple = {'build': lab.build, 'up': lab.up, 'down': lab.down, 'capture': lab.captures,
              'evidence': lab.evidence, 'package': lab.package, 'reset': lab.reset, 'flush-dns': lab.flush_dns,
              'prime-dns': lab.prime_dns, 'hostaccess': lab.host_access, 'clear': lab.clear,
              'chown': lab.fix_owner, 'pin': lab.pin_versions, 'scaffold': lab.scaffold}
    if a.cmd in simple:
        simple[a.cmd]()
    elif a.cmd == 'demo':
        lab.demo(a.auto)
    elif a.cmd == 'tls':
        lab.set_tls(a.mode)
    elif a.cmd == 'auth':
        lab.set_auth(a.mode)
    elif a.cmd == 'selector':
        lab.set_selector(a.name)
    elif a.cmd == 'cond':
        lab.condition(a.rtt, a.loss, a.rate)
        print('condition applied: RTT %g ms, loss %g%% each way%s' % (a.rtt, a.loss, ', rate %g Mbit' % a.rate if a.rate else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
