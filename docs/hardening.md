# Hardening guide (Phase 8)

The console's **Security** page runs most of these checks every time it opens. This guide covers what
it can't see.

## Accounts and secrets

- Every administrator and the CSO use two-factor sign-in. Disable accounts nobody uses.
- Replace every `change-me` value in `.env` with `openssl rand -hex 32` (a new `HSS_WALL_TOKEN` must
  also go into each wall PC's agent config; a new `HSS_WA_TOKEN` needs `docker compose up -d whatsapp api`).
- Remove `HSS_ADMIN_TOKEN` from `.env` once no script uses it. Rotate the wall token that was shared
  in chat earlier.
- Changing the database password on a running system:
  ```bash
  docker compose exec db psql -U hss -d hss -c "ALTER USER hss PASSWORD '<new>'"
  ```
  then set the same `POSTGRES_PASSWORD` in `.env` and `docker compose up -d api`.
- NVRs: a dedicated limited user for HSS (docs/edge.md); change the NVR admin passwords from the
  defaults and keep them out of HSS.

## Network (VLANs)

| Network | What is on it | Reaches |
|---|---|---|
| Camera VLAN | NVRs and cameras | Nothing outside; NVR PoE ports keep cameras off the LAN |
| Security server VLAN | HSS server, wall PCs | Camera VLAN (ISAPI 80, RTSP 554), NTP |
| Office LAN | Console users | Server 443 only |
| Guard Wi-Fi | Guard phones | Server 443 (phone app) and 5055 (Traccar) only |

- The server needs only 443 (console), 8189/udp (live video), 5055 (guard phones) open inbound; close
  everything else in the server firewall (`sudo ufw default deny incoming`, then allow those ports from
  the networks above, and 22 from the IT PC only).
- Docker-published ports bypass `ufw`. `compose.yaml` publishes 80/443 (proxy), 8189/udp (video), 5055
  (Traccar, geo profile) and 8090 (ntfy push, notify profile); the gateway's RTSP (8554) and API (9997) stay
  inside Docker. Limit those by the VLAN rules above (switch or router ACLs), and don't add other `ports:` entries.
- Wire the server at 1 Gbps to the camera VLAN (tasks 19 and 20).
- No port forwarding from the internet. Remote access through a VPN only.

## TLS

The proxy issues its own certificates from a private authority (no internet needed). Install its root
certificate on every PC, phone and wall PC that uses the console (docs/console.md). The authority is in
every backup, so trust survives a restore. For the hosted option, use a public domain and certificate.

## Time

Every NVR, camera and the server on NTP: on each NVR, Configuration › System › Time Settings › NTP,
server = the site's NTP source (or `pool.ntp.org` if the NVRs reach the internet), interval 60 min,
and "Sync camera time" on. The Devices page and the Security check show cameras still off.

## Recording retention

`HSS_RECORDING_DAYS` (default 30) is the days of video each camera must keep. The daily check reads the
oldest recording per camera from the NVRs; the Devices page shows "Video kept" per camera and the
Security page lists cameras short of the target. Fixes: more or bigger drives, H.265 and lower bitrate
on less important cameras, or event recording instead of continuous. NVR4's failed drive must be
replaced first.

## Privacy masking

Where a camera sees into neighbours' property, toilets or private offices, set a privacy mask on the
camera itself (the NVR's web page › Configuration › Camera › Privacy Mask, or the camera's own page):
masked areas are blacked out in live view and in the recording, so no software can undo it. Record each
mask in the camera's notes and photograph the masked view for the DPIA.

## Power (UPS)

| Device | Why | Size guide |
|---|---|---|
| HSS server | Clean shutdown, no database damage | 1.5 kVA line-interactive, 15 min |
| Core switch and NVRs | Keep recording through short cuts | 2 to 3 kVA online UPS per rack, 30 min |
| PoE switches far from the rack | Cameras stay up | Small UPS per cabinet |
| Wall PCs and TVs | Control room keeps watching | 1 kVA per two wall PCs |

Connect the server's UPS by USB and install `nut` so the server shuts down cleanly at low battery. With
a generator, check that the UPS covers the switch-over time.

## Updates

`git pull` and rebuild monthly, after a backup. Update NVR and camera firmware only from Hikvision's
site and after testing on one device (the two K4 NVRs first).
