# Local Mail System (CS3001 Computer Networks, Fall 2026)

Individual project by Huzai. The implementation, experiments, captures and validation were completed in WSL Ubuntu.

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
    curl -sL https://get.containerlab.dev | sudo bash
    python3 tools/labctl.py build                # venv, node image, FRR image

## 4. Bring the lab up
    make doctor && make build && make up
    make test            # stage tests: network, sockets, dns, mail, tls, auth (all must PASS)

Typical order for a full run: make up, make test, make demo, make capture, make evidence, make experiments,
make tables, then the manual work (screenshots, diagram, report), make scaffold if README/disclosure are missing,
make check, make package. make down stops everything.

## 5. Run the POC
    make demo      # expected: spf=pass and dkim=pass for alice to bob; spf=fail for the forged mail
For Thunderbird: sudo -E venv/bin/python tools/labctl.py hostaccess, import build/pki/ca.crt, then
configure alice (mail.alpha.test, IMAP 143 and SMTP 587, STARTTLS) and bob (mail.beta.test, IMAP 143).

## 6. Reproduce the experiments
    make experiments    # 1 to 3 hours; or: sudo -E venv/bin/python tools/orchestrate.py latency|rtt|throughput|auth|quick
    make tables         # CSVs in results/csv, tables in results/tables, graphs in results/graphs, results/summary.md

## 7. Captures
    make capture        # captures/*.pcapng, packet lists in evidence/auto/, key log in captures/keylogs/
    make evidence       # routing tables, traceroute, logs, headers in evidence/auto/

## 8. Repository map
tools/lab.py and tools/labctl.py (control), tools/stagetests.py (tests), tools/orchestrate.py (experiments),
tools/make_tables.py, tools/mailclient.py, imapclient.py, spoof.py, sink.py, loadgen.py, watcher.py,
parse_headers.py, rtt_count.py, socktest.py, nodes/start_node.py and nodes/ctl_node.py (run inside containers),
docker/Dockerfile.node, topology.clab.yml, config.env. There are no shell scripts.

## 9. Troubleshooting
netem missing (use native Ubuntu or a VM), stale containers or bridges (make down), clock jumps (restart the lab),
ports in use (make down), Thunderbird certificate errors (import build/pki/ca.crt; use host names, not IPs).

## 10. Team, contribution statement and AI use
This individual project was implemented, tested and documented by Huzai. AI use is described in AI_DISCLOSURE.md.
