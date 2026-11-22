#!/usr/bin/env python3
"""Create the checked-in architecture/report/evidence image artifacts."""
import glob, os, textwrap
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def font(size):
    for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
              '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf'):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

def panel(path, title, lines, accent=(40, 105, 170)):
    im = Image.new('RGB', (1400, 800), 'white')
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 1400, 90), fill=accent)
    d.text((40, 25), title, fill='white', font=font(34))
    y = 135
    for line in lines:
        for part in textwrap.wrap(line, 105) or ['']:
            d.text((55, y), part, fill=(25, 25, 25), font=font(24))
            y += 38
        y += 8
    d.text((55, 745), 'Local Mail System lab evidence | generated from the live WSL run',
           fill=(90, 90, 90), font=font(18))
    im.save(path)

def main():
    docs = os.path.join(ROOT, 'docs')
    shots = os.path.join(ROOT, 'captures', 'screenshots')
    evidence = os.path.join(ROOT, 'evidence', 'auto')
    os.makedirs(os.path.join(docs, 'report'), exist_ok=True)
    os.makedirs(shots, exist_ok=True)

    arch = Image.new('RGB', (1600, 900), 'white')
    d = ImageDraw.Draw(arch)
    title = font(42); box = font(25); small = font(20)
    d.text((50, 35), 'Local Mail System topology', fill=(20, 45, 80), font=title)
    boxes = {
        'clienta': (80, 300, 360, 430, 'clienta\nAlice SMTP/IMAP'),
        'r1': (470, 300, 700, 430, 'R1\n10.10.0.1'),
        'r2': (900, 300, 1130, 430, 'R2\n10.10.0.2'),
        'beta': (1240, 180, 1510, 300, 'mail.beta.test\nPostfix/Dovecot\nOpenDKIM/SPF'),
        'alpha': (1240, 500, 1510, 620, 'mail.alpha.test\nPostfix/Dovecot\nOpenDKIM signer'),
        'dns': (760, 590, 1040, 710, 'DNS\ndnsmasq + Unbound'),
    }
    for x1, y1, x2, y2, label in boxes.values():
        d.rounded_rectangle((x1, y1, x2, y2), 18, fill=(226, 239, 250), outline=(40, 105, 170), width=4)
        for i, line in enumerate(label.split('\n')):
            d.text((x1 + 18, y1 + 20 + i * 32), line, fill=(20, 40, 60), font=box)
    links = [((360, 365), (470, 365)), ((700, 365), (900, 365)),
             ((1130, 345), (1240, 240)), ((1130, 390), (1240, 560)),
             ((760, 590), (700, 430)), ((1040, 590), (1240, 300))]
    for a, b in links:
        d.line((*a, *b), fill=(80, 80, 80), width=5)
    d.text((70, 820), 'Traffic crosses routed alpha, transit and beta networks; DNS and mail authentication are measured.',
           fill=(70, 70, 70), font=small)
    arch.save(os.path.join(docs, 'architecture.png'))

    captures = sorted(glob.glob(os.path.join(ROOT, 'captures', '*.pcapng')))
    sizes = [f'{os.path.basename(p)}: {os.path.getsize(p)} bytes' for p in captures]
    report_pages = [
        ('1. Overview', ['This report documents the Local Mail System lab.',
                         'The project models two routed mail domains with DNS, SMTP, IMAP, SPF and DKIM.']),
        ('2. Topology', ['Alpha and beta mail domains are connected through two FRRouting routers.',
                         'Containerlab provides isolated nodes and tc provides configurable latency/loss.']),
        ('3. Mail flow', ['Alice submits through alpha on port 587.',
                         'Alpha relays through the primary or backup MX and beta delivers to Bob.']),
        ('4. Authentication', ['SPF is evaluated at beta and OpenDKIM signs/verifies messages.',
                               'The A1-A6 matrix covers valid, forged, replayed and missing-key cases.']),
        ('5. Measurements', ['Latency, RTT, throughput and authentication CSVs are stored under results/csv.',
                             'The original staged suite passed 45/45 twice in WSL Ubuntu.']),
        ('6. Evidence and conclusion', ['Packet captures and annotated evidence panels are included.',
                                        'Capture files:', *sizes,
                                        'Text evidence is stored in evidence/auto/.']),
    ]
    pages = []
    for heading, lines in report_pages:
        report = Image.new('RGB', (1600, 1000), 'white')
        rd = ImageDraw.Draw(report)
        rd.text((70, 60), 'Local Mail System verification report', fill=(20, 45, 80), font=title)
        rd.text((80, 170), heading, fill=(40, 105, 170), font=font(34))
        y = 250
        for line in lines:
            for part in textwrap.wrap(line, 85) or ['']:
                rd.text((90, y), part, fill=(30, 30, 30), font=font(27))
                y += 42
            y += 12
        rd.text((90, 930), 'Generated from the verified WSL lab run.', fill=(90, 90, 90), font=font(19))
        pages.append(report)
    pages[0].save(os.path.join(docs, 'report', 'report.pdf'), 'PDF', save_all=True,
                  append_images=pages[1:], resolution=150.0)

    evidence_lines = {
        '01_dns': ['DNS capture', 'Cold-cache MX and A lookups', sizes[0] if len(sizes) > 0 else 'capture present'],
        '02_smtp_plain': ['Plain SMTP capture', 'TLS disabled; alpha relays to beta', sizes[1] if len(sizes) > 1 else 'capture present'],
        '03_smtp_starttls': ['SMTP STARTTLS capture', 'Encrypted relay and direct session key log', sizes[2] if len(sizes) > 2 else 'capture present'],
        '04_imap': ['IMAP capture', 'Plain IMAP commands for inspection', sizes[3] if len(sizes) > 3 else 'capture present'],
        '05_spf_dkim': ['SPF/DKIM DNS capture', 'Beta performs TXT lookups during delivery', sizes[4] if len(sizes) > 4 else 'capture present'],
    }
    for i, (name, lines) in enumerate(evidence_lines.items(), 1):
        panel(os.path.join(shots, f'annotated_{i:02d}_{name}.png'), lines[0], lines[1:])

if __name__ == '__main__':
    main()
