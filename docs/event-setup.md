# Event setup and the walk test (Phase 3 gate)

Phase 3's gate is "real events raise alerts". Two tools on the console's **Event setup** page get you
there.

## 1. Check that the NVRs send their events

Hikvision only sends an event to outside software when **Notify Surveillance Center** is ticked for
that event on that channel. **Check event settings** (administrator or CSO, for NVRs added in Devices)
reads every NVR's event linkage and shows, per camera:

- **Sent to HSS**: events with Notify Surveillance Center ticked (green).
- **Set up but not sent**: events that exist on the camera but aren't ticked (amber). Tick them on the
  NVR: Configuration › Event › Smart Event (or Basic Event) › choose the event and channel ›
  Linkage Method › **Notify Surveillance Center** › Save. Then check again.
- **NVR exceptions**: HDD error, HDD full, network disconnected and similar; tick Notify Surveillance
  Center for these under Event › Exception.
- **Events, 7 days** and **Last event**: what actually arrived. A camera that sends events but shows
  "none yet" for a week is worth a look (detection off, wrong area, camera offline).

Plain motion is not listed; HSS ignores it (`HSS_EDGE_IGNORE`), except from cameras chosen for
person/vehicle motion (below).

## Person/vehicle motion (cameras without line crossing or intrusion)

Value-series cameras such as the DS-2CD1043G2-LIU, DS-2CD1143G2-LIU and DS-2CD1047G2H-LIUF have no line
crossing or intrusion, but their **Motion Detection 2.0** can be limited to people and vehicles. For those:

1. On the camera or NVR: Event › Basic Event › Motion Detection › the channel: draw the area, set
   **Target: Human** (and Vehicle if wanted), set the arming schedule, and under Linkage tick
   **Notify Surveillance Center**.
2. In HSS: Event setup › the camera's row › **Person/vehicle motion: on** (administrators and the CSO;
   audited). The edge service picks it up within a minute.
3. Walk test it: the camera appears with "Motion, human".

HSS then forwards that camera's motion only when the camera says the target was a person or vehicle, as a
**warning** event of type Motion with the object (so alert rules can match it); motion without a target is
still dropped. If the walk test shows nothing, the camera's firmware may not report the target with its
motion events: update its firmware, or leave it for the server AI. Plain motion from all other cameras stays
ignored.

The NVR user needs *Remote Parameters Settings* (read). The check only reads; it changes nothing on
the NVR.

## 2. Walk test

1. Make sure the edge service is running (`docker compose logs edge` shows `event stream open` for
   each NVR).
2. **Start walk test**, then walk through each camera's line-crossing or intrusion area.
3. Each camera is listed as its first event arrives, with the event, the delay, and whether it raised
   an alert (green) or not (amber: no rule matched, or a repeat inside the rule's cool-down).
4. **Stop** when done. A camera that stays missing: check its event is set up and ticked (step 1), its
   detection area, and the camera's clock (docs/edge.md).

The gate is passed when the cameras covering the perimeter and the gates all raise alerts.
