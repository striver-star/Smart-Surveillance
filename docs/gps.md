# Site map, zones and guard tracking (Phase 5)

The console's **Site map** shows the site plan with cameras (live status, open alerts), zones
(geofences) and guards or vehicles on the move. Guard phones report through **Traccar** (Apache 2.0),
which forwards every position to HSS; HSS owns the zones, tests positions with PostGIS and raises
ordinary events, so alert rules, escalation, WhatsApp and the video wall all apply.

## 1. Start the GPS service

```bash
cd ~/Smart-Surveillance && git pull
docker compose --profile ai --profile notify --profile edge --profile geo up -d --build
```

Traccar listens on port **5055** (OsmAnd protocol) on the server's LAN address. Its own web page is
not exposed; nothing needs setting there. Open port 5055 in the server's firewall for the site
network only.

## 2. Add a plan and tie it to the map (administrator or CSO)

1. **Site map › Add plan**: a site drawing, floor plan, or a satellite or drone picture of the site
   (PNG, JPEG or WebP, up to 8 MB; export a PDF plan as an image first). Add one plan per area or
   floor as needed.
2. **Reference points**: click two spots far apart whose latitude and longitude you know (two fence
   corners, the main gate and the far store). For each, stand there with a phone's map app and copy
   the coordinates, or right-click the spot in an online map. Paste "6.524379, 3.379206".
   The page then shows the plan's scale in metres per pixel; check it against a known distance.
   Without reference points the plan still shows cameras, but GPS positions and zones can't work.

## 3. Place cameras

**Place cameras**: pick a camera on the right, click its spot, then set which way it faces, its view
angle and how far its view reaches on the plan. Cameras show green (online), grey (offline), amber or
red with a pulse (open alert). Click a camera in View mode to watch it live beside the plan.

## 4. Draw zones

**Draw zone**: click the corners in order, then **Finish**, and fill in:

| Kind | Use | Alerts |
|---|---|---|
| Restricted area | Store yard, server room, roof | entering (or leaving / both / none) |
| Perimeter | The site boundary | usually leaving (a guard or vehicle left the site) |
| Patrol checkpoint | Places guards must visit | "missed patrol" if no guard visits within N minutes |
| Area | Labels only, or vehicle areas | as chosen |

- **For**: guards, vehicles or both. **Armed**: always, or windows like `18:00-06:00`.
- **Cameras covering it**: zone events open on the first camera, the clip is cut from it, and the
  video wall pins it with a red outline.

## 5. Guard phones

For each guard phone (Android works best; iPhone limits background location):

1. **Site map › Guards and vehicles › Add**: name, type, and a device identifier (one is suggested,
   e.g. `hss-k3f9a2`).
2. On the phone install **Traccar Client** (free, Google Play or App Store) and set:
   - **Device identifier**: the same identifier as in HSS
   - **Server URL**: `http://<server IP>:5055` (for example `http://10.6.83.82:5055`)
   - **Location accuracy**: High; **Frequency**: 30 seconds; **Distance** 0; **Offline buffering** on
   - Allow location **all the time**, turn off battery optimisation for the app, then switch
     **Service status** on.
3. Within a minute the guard shows as "reporting". A phone that reports but isn't added appears under
   "Reporting but not added" with an **Add** button.

Positions travel over the site network as plain HTTP (the OsmAnd protocol); the device identifier works
as its password. Keep port 5055 to the site network or a VPN; for guards outside the site network, use
the hosted option with a public certificate.

Events from guards and vehicles:

| Event | Severity | When |
|---|---|---|
| zone_enter / zone_exit | the zone's | a unit enters or leaves an armed zone that alerts on it |
| sos | critical | the phone or tracker sends an alarm (Traccar Client: SOS button where available) |
| checkpoint_visit | info | a guard reaches a checkpoint |
| missed_patrol | warning | no guard at a checkpoint within its interval, while armed |
| unit_offline / unit_online | warning / info | no position for `HSS_UNIT_OFFLINE_MIN` minutes (default 10), and back |
| low_battery | warning | phone battery below `HSS_UNIT_LOW_BATTERY` % (default 15) |

## 6. Walk-through (Phase 5 gate)

**Walk-through** mode moves a guard or vehicle to wherever you click, as if its phone reported from
there, so zones and alerts can be tested from the control room; each simulated event is marked as
simulated. **Send SOS from here** tests the SOS path.

The gate is a real walk-through: a guard with a phone walks into a restricted zone and out of the
perimeter, skips a checkpoint, and presses SOS; each raises its alert, the linked camera is pinned on
the wall, and the guard's trail shows on the map.

Not in this phase: pushing zones to cameras over ISAPI (camera detection areas stay set on the NVR),
an internet map background (plans are your own images), and vehicle trackers (add their protocol in
`gps/traccar.xml` when chosen).
