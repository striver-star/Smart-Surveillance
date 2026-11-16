# Per-camera permissions and read-only roles

Release 2.0, second batch.

## Camera lists

Each user can be limited to some cameras: **Users › Cameras › Change** (administrator). Tick whole NVRs or single
cameras, or type patterns (`nvr4-*` = every camera on NVR4, `nvr1-ch0?` = channels 01 to 09). An empty list
means every camera. **Administrators and the CSO always see every camera.**

The list applies to operators, viewers and clients, everywhere a camera shows:

| Where | What a limited user gets |
|---|---|
| Live and recorded video | Only their cameras; any other camera is refused at the video gateway |
| Camera lists (Live view, Playback, Devices) | Only their cameras |
| Alerts | Only their cameras' alerts, in the list, the counts, the pop-ups and the sound |
| Events, snapshots, clips | Only their cameras |
| Site map, heat map | Only their cameras |
| PTZ | Only their cameras |
| Event setup | Not available (it works on every camera at once) |

Changes apply from the user's next action; open pages pick them up when reloaded.

## Read-only roles

| Role | Can | Can't |
|---|---|---|
| **Viewer** | Live view, Playback, Alerts and Events (read only), Site map, heat map | Acknowledge, note or close alerts; sirens and lights; PTZ; anything else |
| **Client** | Live view and Playback of their cameras | Everything else. A client account must have a camera list |

**Can watch recordings** (in the camera list editor) switches Playback off for one user, for "live only" accounts.
Everything they watch is in the **Viewing log**.

Use a **client** account for an outside party (a tenant, a contractor, a head office) who should see only their
own area. Use a **viewer** account for staff who need to follow alerts without handling them.

## API

`users.cameras` (patterns) and `users.can_playback` (migration `020_camera_access.sql`); checks in
`services/api/app/access.py`.
