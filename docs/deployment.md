# Deployment options (Phase 9)

| Option | Use when | How |
|---|---|---|
| Linux server (recommended) | A dedicated server at the site | Ubuntu 24.04 LTS or Debian 12, then `sudo ./install.sh` |
| Offline bundle | The site server has no internet | Build with `tools/package/make-release.sh <version>` where there is internet; copy `dist/hss-<version>/`; `sudo ./install.sh --offline images.tar.gz` |
| Virtual machine | The client has VMware, Proxmox or Hyper-V | A VM with Ubuntu 24.04 (8 vCPU, 16 GB, 200 GB disk, bridged network on the camera VLAN), then the Linux steps |
| Windows server (backup option) | Only Windows is allowed | Windows Server 2022 or Windows 11 Pro with WSL2 and Ubuntu 24.04, Docker Engine inside WSL2, then the Linux steps. Needs WSL2 mirrored networking so cameras and phones reach it. Not yet tested on site: use only if Linux is refused |
| Hosted | Several sites, one control room | Later: needs site connectors and tenant separation (planned after the pilot) |

## Server sizing

| Site | CPU | Memory | Disk (system, evidence, backups) | Network |
|---|---|---|---|---|
| Up to 7 NVRs, no server AI | 4 to 8 cores | 16 GB | 500 GB SSD | 1 Gbps wired to the camera VLAN |
| Up to 20 NVRs, no server AI | 8 cores | 32 GB | 1 TB SSD | 1 Gbps, 10 Gbps uplink preferred |
| With server AI (Tier S) | as above, plus an NVIDIA GPU (task 16) | +16 GB | +200 GB | |

Recordings stay on the NVRs; the server keeps events, snapshots, clips, evidence and backups.

## Install steps (Linux)

```bash
sudo apt-get install -y git
git clone https://github.com/striver-star/Smart-Surveillance.git ~/Smart-Surveillance
cd ~/Smart-Surveillance
sudo ./install.sh
```

The installer asks for the site name, time zone and the first administrator, then prints the console
address and where the certificate file is. Next: install the certificate on each PC and phone
(docs/console.md), sign in, and follow **Getting started**.

Upgrade: `sudo ./install.sh --upgrade` (takes a backup first, then updates and restarts).
