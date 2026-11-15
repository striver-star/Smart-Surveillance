# Adding NVRs and setting camera tiers (Phase 1)

Administrators add, edit and remove NVRs on the console's **Devices** page. Phase 1's gate is met when
an NVR added there shows its channels and tiers.

## Add an NVR

1. On each NVR, create a dedicated user (not admin) with *Remote Live View*, *Remote Playback*,
   *Remote Parameters Settings (read)* and *Remote Log Search* for all channels (docs/edge.md, step 1).
2. Console → **Devices** → **Add NVR**:
   - **NVR address**: its IP address, e.g. `10.1.3.4`. Add `:port` only if its web port isn't 80.
   - **Short name**: starts every camera id (`nvr4` gives `nvr4-ch22`). Left empty, it's `nvr` plus the
     last number of the IP address. It can't be changed later, because events and history use it. Two
     NVRs on different networks with the same last number (10.1.3.4 and 10.1.4.4) need different
     short names.
   - **NVR user** and **Password**: the user from step 1.
   - **RTSP port** (normally 554) and **Network segment** (a label such as `CCTV VLAN 30`).
3. **Test and add**. The server logs in to the NVR first and reads its model, firmware, channels and
   drives. If the test fails, the reason is shown (wrong password, no answer, not a Hikvision NVR).
   Tick **Save anyway** only for an NVR that is offline now but will be reachable later.

After saving, within a few seconds:
- its cameras appear in **Live view**, named as on the NVR (sub-streams, pulled only while watched);
- the edge service starts watching it for events, health and clips (within a minute);
- it is written to the **Audit log** (never the password).

NVRs found by the probe or listed in `.env` but not yet added show an **Add to console** button.

**Edit** retests the connection; leave the password empty to keep the stored one. Untick *Watch this
NVR* to pause it, or *Add its cameras to live view* to remove its cameras from live view. **Remove**
stops watching it and removes its live view paths; past events and alerts stay.

## Camera tiers (E, N, S)

Each camera has an AI tier: **E** (the camera's own AI), **N** (the NVR's AI) or **S** (the server's AI).
The camera survey (`hss-cameras`) sets it automatically. Administrators and the CSO can override it:
click the tier on the Devices page, choose a tier and write why (for example "AcuSense licence missing
on this camera"). Overridden tiers show a ✎ mark and the reason on hover; choose *Automatic* to undo.

## How passwords are kept

- Stored encrypted (Fernet: AES-128 with an HMAC check, from the `cryptography` package), never in
  plain text, never shown in the console again and never written to logs or the audit log.
- The key is `HSS_VAULT_KEY` in `.env`. If that's empty, the API creates a key file in its data
  volume on first use (`/data/vault.key`, readable only by the API).
- **Back up the key with the database.** Without it the stored NVR passwords can't be read and each
  NVR has to be edited with its password again. To see the key file:
  ```bash
  docker compose exec api cat /data/vault.key
  ```
- Only the edge service can read the passwords back (with the worker token), because it has to log
  in to the NVRs. Treat `HSS_WORKER_TOKEN` like a password.
- Changing the key: make a new one (`docker compose exec api python -m app.vault new-key`), set
  `HSS_VAULT_KEY=<new>,<old>` in `.env`, restart the API, run
  `docker compose exec api python -m app.vault rotate`, then remove `,<old>`.

## Live view and gateway/cameras.env

Cameras of console-added NVRs are added to the stream gateway through its API and rechecked every two
minutes, so a gateway restart doesn't lose them. Camera paths already listed in `gateway/cameras.env`
are left exactly as they are. Once every NVR is in the console, `gateway/cameras.env` can be emptied
and the gateway recreated (`docker compose up -d --force-recreate gateway`); the console adds the
paths back within two minutes.

## Not in Phase 1 yet

Multi-site (tenant) separation with row-level security, ONVIF and plain RTSP cameras, and a
dedicated health service with polling settings per NVR. These come with the hosted option and
Phase 8.
