# Local Mail System

This computer-networks project runs a two-domain mail network in WSL 2 Ubuntu with Docker Engine and Containerlab. It includes DNS, Postfix, Dovecot, OpenDKIM, SPF, two FRRouting routers, network impairments, experiments, captures and evidence.

The steps below describe the WSL Ubuntu setup that was used successfully.

## 1. Install WSL Ubuntu

In Windows PowerShell, if needed, run `wsl --install -d Ubuntu-24.04` and `wsl --update`. Open Ubuntu and confirm WSL 2 with `uname -a`.

Keep the project on the Linux filesystem, for example `/home/<user>/local-mail-system`, not under `/mnt/c`. Avoid spaces in the path.

## 2. Install Docker inside WSL

Docker Desktop on Windows is not required for this setup. Docker Engine runs inside Ubuntu WSL.

Run: `sudo apt update`, `sudo apt install -y docker.io docker-compose-plugin`, `sudo service docker start`, and `sudo usermod -aG docker "$USER"`.

Close and reopen Ubuntu, then verify with `docker --version`, `docker info`, and `docker run --rm hello-world`. If Docker gives a permission error, reopen Ubuntu after the group change.

## 3. Install dependencies

Run `sudo apt update` and:

`sudo DEBIAN_FRONTEND=noninteractive apt install -y git make curl jq build-essential autoconf automake libtool pkg-config gettext libmilter-dev libssl-dev libbsd-dev zlib1g-dev python3 python3-venv python3-pip docker.io tshark tcpdump iproute2 dnsutils swaks bridge-utils inotify-tools graphviz poppler-utils xz-utils wireshark`

Install Containerlab with `curl -sL https://get.containerlab.dev | sudo bash`, then verify with `containerlab version`.

Enable packet capture with `sudo setcap cap_net_raw,cap_net_admin+eip /usr/bin/dumpcap` and verify with `getcap /usr/bin/dumpcap`.

## 4. Put the project in WSL

Clone it with `cd ~`, `git clone https://github.com/HuzaifaAhmedBari/Local-Mail-System.git local-mail-system`, and `cd ~/local-mail-system`.

For Windows editing, open the WSL copy directly with `code ~/local-mail-system`. If editing a Windows copy, copy changed files into WSL, for example `cp /mnt/c/Users/<windows-user>/local-mail-system/README.md ~/local-mail-system/README.md`.

## 5. Build and diagnose

The main Python controller is `tools/lab.py`. Run `cd ~/local-mail-system`, `python3 tools/lab.py build`, and `make doctor`.

`build` creates the virtual environment, installs requirements, builds the mail-node image and pulls the FRR image. `doctor` checks Docker, Containerlab, packet tools, `tc`, memory, disk and the Docker daemon.

## 6. Start and test

Run `make up`, then `make test`. Startup should end with `lab is up. Try: make demo`. Tests should end with `45/45 checks passed`.

The tests cover routing, sockets, DNS, SMTP, backup MX, queues, TLS, SPF, DKIM signing, DKIM verification and replay handling.

## 7. Demo and network conditions

Run `make demo` to show authenticated submission, relay, delivery, SPF/DKIM results, latency and queue behavior.

Apply 100 ms delay and 2% loss in each direction with `sudo -E venv/bin/python tools/lab.py cond 100 2`. Add a rate limit with `sudo -E venv/bin/python tools/lab.py cond 100 2 10`. Clear conditions with `sudo -E venv/bin/python tools/lab.py clear`.

## 8. Experiments and tables

Run `make experiments` and then `make tables`. The full experiments may take one to three hours.

Individual groups are `sudo -E venv/bin/python tools/orchestrate.py latency`, `rtt`, `throughput`, or `auth`. Outputs are saved in `results/csv/`, `results/tables/`, `results/graphs/` and `results/summary.md`.

## 9. Captures and evidence

With the lab running, run `make capture` and `make evidence`.

The five captures are saved in `captures/01_dns.pcapng`, `captures/02_smtp_plain.pcapng`, `captures/03_smtp_starttls.pcapng`, `captures/04_imap.pcapng`, and `captures/05_spf_dkim.pcapng`.

The capture helper writes temporarily under `/tmp` because `dumpcap` runs as the `wireshark` user and may not be able to traverse `/home`; it copies completed files back into `captures/`. Text evidence is written to `evidence/auto/`, key logs to `captures/keylogs/`, and annotated images to `captures/screenshots/`.

## 10. Validate and package

Run `make check`. Successful output ends with `check: 0 MISS, 0 FAIL`.

Run `make package` to create `/home/<user>/CN_Local_Mail_System_Submission.zip`. Copy it to Windows with `cp ../CN_Local_Mail_System_Submission.zip /mnt/c/Users/<windows-user>/Downloads/`.

## 11. Stop and restart

Stop the lab with `make down`. A clean restart is `make down`, `make up`, and `make test`.

## 12. Troubleshooting

For Docker permission errors, run `sudo service docker start`, ensure the user is in the `docker` group, and reopen Ubuntu.

For missing `ensurepip`, run `sudo apt install -y python3-venv python3.12-venv`, `rm -rf venv`, and `python3 tools/lab.py build`.

For empty captures, run `sudo setcap cap_net_raw,cap_net_admin+eip /usr/bin/dumpcap`, `sudo ip netns exec clab-mail-r1 tshark -D`, `make down`, `make up`, and `make capture`.

For DNS, routing or mail failures, run `make down`, `make up`, and `make test`. If Windows edits appear stale, edit the `/home` copy with VS Code or explicitly copy files from `/mnt/c`.

## 13. Project map

`tools/lab.py` is the main Python controller and CLI. `tools/stagetests.py` contains 45 behavioral tests. `tools/orchestrate.py` runs experiments. `tools/make_tables.py` creates tables and graphs. `tools/mailclient.py` is the timed SMTP client.

`nodes/start_node.py` configures services inside containers. `nodes/ctl_node.py` controls runtime TLS, auth and selector changes. `docker/Dockerfile.node` builds the mail image. `topology.clab.yml` defines Containerlab. `config.env` stores addresses and constants.

The Dockerfile and Containerlab YAML remain because they are native inputs to those systems. Operational control is Python through `tools/lab.py`.
