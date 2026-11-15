# Edge service: NVR events, device health and clips (Phase 3, part B)

**Status 2026-11-15:** built and rehearsed end to end in the sandbox against a simulated Hikvision
NVR (event stream with repeats and pictures, health endpoints, snapshots) and an RTSP recording:
events raised once per activity, motion ignored, tamper and line crossing alerted with snapshots,
camera offline / drive fault / NVR offline raised once and recovery noted, a 28.5 s clip cut and
attached with its SHA-256, and an event kept on disk while the API was stopped and delivered when it
came back. 8 edge tests and 23 API tests pass. **Not yet run against the site's NVRs.**

## What it does

| Job | How | Result in the platform |
| --- | --- | --- |
| NVR and camera events | Listens to each NVR's alert stream (`/ISAPI/Event/notification/alertStream`) | Line crossing, intrusion, region entrance, loitering, tamper, video loss, face capture, plate, scene change, drive errors... become events; each activity is raised once; a snapshot comes with the event or is fetched from the NVR |
| Device health | Every minute: NVR answering, each channel online, drive status, time mode | Live status on Devices and Overview; changes become events (camera offline/online, drive fault/ok, NVR offline/online) |
| Clips | When an alert needs one (critical alerts automatically, others from the alert's **Get clip** button) | 10 s before to 20 s after the event, copied from the NVR recording (no re-encoding), attached to the alert and the evidence export |
| Offline queue | Events wait on disk (up to 10,000) while the API is unreachable | Delivered in order when the API is back |

Event times use the server's clock (several cameras' clocks are hours off); the device's own time
is kept in the event details. Plain motion (VMD) is ignored by default (`HSS_EDGE_IGNORE`).

Device faults go through the **Device faults** alert rule (screen, push, WhatsApp to `device`
subscribers, normally the IT Manager), not the CSO's security alerts. When a camera or drive
recovers, a note is added to its open alert.

## Setting it up on site

1. **A dedicated NVR user** on each NVR (not the admin): Configuration → System → User Management →
   Add, user type Operator, with remote rights *Remote Live View*, *Remote Playback*, *Remote
   Parameters Settings (read)*, *Remote Log Search* and, for PTZ cameras, *Remote PTZ Control*, for all channels. Use the same name and
   password on all NVRs.
2. **Turn on "Notify Surveillance Center"** for each event the platform should receive. Hikvision
   only sends an event to outside software when this is ticked, per channel and per event:
   NVR web page → Configuration → Event → Smart Event (Line Crossing, Intrusion, Region Entrance...)
   and Basic Event (Video Tampering, Video Loss) → channel → *Linkage Method* → **Notify
   Surveillance Center**. Do the same for HDD Error and Network exceptions under Exception.
3. Start it:
   ```bash
   docker compose --profile ai --profile notify --profile edge up -d --build
   ```
4. **Add each NVR in the console**: Devices → **Add NVR**, with its address and the user from step 1
   (see docs/nvr-registry.md). The edge service checks the console's list every minute, so NVRs
   added, edited or removed there are picked up without a restart.

   Fallback: while no NVR has been added in the console, the edge service uses `HSS_NVRS`,
   `HSS_NVR_USER` and `HSS_NVR_PASSWORD` from `.env` instead. Once the first NVR is in the console,
   those lines are ignored and can be emptied.
5. Watch it connect:
   ```bash
   docker compose logs -f edge
   ```
   Each NVR should log `event stream open`. Walk through a camera's line-crossing area and look for a
   line like `nvr4-ch22 line_crossing (sent)`, then the alert in the console.

Clips need the NVR to be recording that camera at the time (NVR4's failed drive means no clips from
NVR4 until it is replaced). H.265 clips play on iPhone and in Chrome or Edge on Windows PCs with
hardware HEVC support; if a PC can't play them, the evidence zip still contains the original file.
