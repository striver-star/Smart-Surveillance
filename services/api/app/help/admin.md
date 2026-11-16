# Administrator guide

For the IT Manager and other administrators.

## Install and upgrade

- New server (Ubuntu or Debian): `sudo ./install.sh`. It installs Docker, writes `.env` with random secrets, starts everything, creates the first administrator, and sets up backups.
- Upgrade: `sudo ./install.sh --upgrade` (backs up first).
- No internet at the site: build a bundle elsewhere with `tools/package/make-release.sh <version>`, copy it over, then `sudo ./install.sh --offline images.tar.gz`.
- Then follow **Getting started** in the console.

## Every day (5 minutes)

- **Security** page: no red items. **Devices**: no NVR "not answering", no drive faults.
- Overview: WhatsApp "ready", wall PCs online.

## Users (Users page)

- One account per person; the role decides what they see. Administrators and the CSO must use two-factor.
- **Reset password** gives a one-time password and clears two-factor; hand it over in person.
- Disable accounts on the day someone leaves.
- **Camera lists**: Users › Cameras › Change limits an operator, viewer or client to some cameras (whole NVRs, single cameras, or patterns like `nvr4-*`). Administrators and the CSO always see all. **Viewer** = watch and read alerts only; **Client** = an outside party, live (and optionally recorded) video of their cameras only. See docs/camera-access.md.
- **Guard (phone app only)**: for patrol guards. They use the phone app at `/m/` (check-ins, SOS, logbook) and can't open the console. The phone needs the HSS root certificate installed before the app will install. See the Phone app guide in docs/mobile.md.

## Devices

- **Find devices** (Devices page) scans the site's network for Hikvision NVRs and cameras, shows which are new, already added or not activated, and can identify and add them. For devices on unknown addresses run `python3 tools/discovery/hss-sadp.py` on the server. See docs/discovery.md.

- **Add NVR**: address, a dedicated NVR user (not admin), password. The login is tested before saving; passwords are stored encrypted.
- **Event setup**: check each NVR's event settings; tick Notify Surveillance Center for events marked amber.
- **AI tier**: click a camera's tier to override it, with a reason.
- "Video kept" shows days of recording per camera; under 30 days needs more storage or lower bitrate.

## Viewing log and video access

Video needs a sign-in (admin, CSO or operator) or a wall screen key; every live view and playback is in **Viewing log**. The wall capacity test page (`/wall-test/`) now needs a signed-in tab in the same browser. Don't publish the gateway's RTSP port 8554 in compose: Docker-published ports bypass the server firewall.

## Backups

Daily at 01:30, encrypted, kept 14 days; a restore test on the 1st of each month. Keep the passphrase offline and a second copy of backups off the server (docs/backup.md). A failed backup sends a WhatsApp message to the "system" topic.

## Licence

**Settings › Licence**: copy the installation id to the vendor; load the licence file they send. The licence never stops recording or alerts.

## When something breaks

| Problem | First check |
|---|---|
| Console won't open on a phone | The phone trusts the certificate (docs/console.md) |
| Live view "gateway" error | `docker compose up -d --force-recreate gateway` |
| WhatsApp not ready | `docker compose logs whatsapp`; re-link the phone if asked |
| No NVR events | Event setup page; `docker compose logs edge` |
| A service is down | `docker compose ps`, then `docker compose up -d` |

Logs: `docker compose logs --tail 100 <service>` (api, edge, gateway, whatsapp, proxy, traccar).
