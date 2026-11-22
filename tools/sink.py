#!/usr/bin/env python3
"""tools/sink.py [PORT] - minimal aiosmtpd sink that accepts and discards mail (network-only baseline)."""
import sys, time
from aiosmtpd.controller import Controller


class H:
    async def handle_DATA(self, server, session, envelope):
        return '250 OK'


c = Controller(H(), hostname='0.0.0.0', port=int(sys.argv[1]) if len(sys.argv) > 1 else 2525)
c.start()
try:
    while True:
        time.sleep(3600)
except KeyboardInterrupt:
    c.stop()
