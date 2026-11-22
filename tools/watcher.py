#!/usr/bin/env python3
"""tools/watcher.py OUT.csv - host-side inotify watcher: when does each message land in bob's Maildir?"""
import os, re, signal, sys, time
from inotify_simple import INotify, flags

D = 'data/beta-home/bob/Maildir/new'
stop = []
signal.signal(signal.SIGTERM, lambda *a: stop.append(1))
signal.signal(signal.SIGINT, lambda *a: stop.append(1))
i = INotify()
i.add_watch(D, flags.MOVED_TO | flags.CREATE)
seen = set()
with open(sys.argv[1], 'w') as out:
    out.write('msgid,t_arrive_ns,file\n')
    while not stop:
        for ev in i.read(timeout=300):
            t = time.time_ns()
            if ev.name in seen:
                continue
            seen.add(ev.name)
            head = ''
            for _ in range(50):
                try:
                    head = open(os.path.join(D, ev.name), 'rb').read(8192).decode('latin1')
                    break
                except OSError:
                    time.sleep(0.01)
            m = re.search(r'^Message-ID:\s*(<[^>]+>)', head, re.M | re.I)
            out.write('%s,%d,%s\n' % (m.group(1) if m else '', t, ev.name))
            out.flush()
