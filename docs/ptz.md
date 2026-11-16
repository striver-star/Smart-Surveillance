# PTZ control

PTZ (pan, tilt, zoom) cameras are steered from the console through their NVR (Hikvision's PTZ proxy over
ISAPI), with the NVR login stored in Devices. Fixed cameras simply show "no PTZ".

## Set up

1. Give the HSS user on each NVR the **Remote PTZ Control** right (Configuration › System › User
   Management › the HSS user › Remote rights), for the PTZ channels.
2. The NVR must be added in **Devices**. Nothing else to configure.

## Use (Live view, or a camera on the Site map)

- Click the PTZ camera's tile; the controls appear under the camera list.
- **Hold** an arrow to move and **+ / −** to zoom; let go to stop. Speed sets how fast.
- **Presets**: pick one and press **Go**. The CSO and administrators can **Save view** as a preset
  (a number already used is replaced).
- Keyboard: Tab to an arrow, hold Space.

Safety: the console repeats a move every half second while the button is held; the server stops the
camera by itself 1.5 seconds after the last repeat, so a closed browser or a dropped network never leaves
it turning. One person steers a camera at a time; another operator must wait 30 seconds after the last
command, while the CSO and administrators can take over at once. Steering and presets are in the audit
log (steering once per person and camera every 5 minutes).

## Turn a PTZ to a preset when an alert fires

In **Settings › Alert rules**, set **Turn PTZ cameras to** on a rule, e.g. `nvr4-ch05:3` (preset 3 of
camera nvr4-ch05; several separated by commas). When the rule raises an alert, the camera turns and the
alert's timeline records it ("PTZ: nvr4-ch05 to preset 3"). Pair it with the wall screen's alert
pinning so the control room sees the PTZ view at once.

## Patrol tours

A patrol tour takes a PTZ camera round its presets in order, waiting a set time at each, all day or only in set
hours on set days (for example the fence line every night 18:00–06:00, and the car park at weekends). Release 2.0.

**Set up** (CSO and administrators): Live view › click the PTZ camera › Patrol › **New patrol tour**. Pick at least
two presets saved on the camera, the seconds to stay at each (10 s to 1 hour; include the time it takes to turn),
the days, and all day or from–to (an end before the start runs overnight, and counts as the day it started).
A camera has one tour in force at a time: tours on one camera can't overlap in their hours (e.g. a day tour 06:00–18:00
and a night tour 18:00–06:00 is fine).

**It gives way:**

| When | The tour |
|---|---|
| An operator steers the camera or sends it to a preset | waits, never blocks them, and carries on 2 minutes after their last move (`HSS_PTZ_RESUME_S`, default 120) |
| An alert rule turns the camera to a preset | waits 5 minutes (`HSS_PTZ_ALERT_HOLD_S`, default 300) so the control room sees the alert's view |
| An operator presses **Pause** (15 minutes, 1 hour or 4 hours) | stops until then, or until someone presses **Resume** |
| Outside its hours, or turned off | leaves the camera where it is |
| The camera or NVR doesn't answer | shows "can't reach the camera" and tries again (the NVR's own offline alert covers the outage) |

The PTZ panel shows each tour's state: the step and preset it is at, paused (by whom, until when), waiting (who
has the camera), or outside its hours. Adding, changing, deleting, pausing and resuming a tour are in the audit log.

Why HSS runs the tour rather than the camera's own patrol function: the camera's patrol doesn't know when an
operator or an alert needs the camera, and fights them. Turn off any patrol set on the camera or NVR itself
before using an HSS tour on it.

Wear: a PTZ moving all day wears its motors. Prefer tours in the hours they're needed, and dwell times of 20 s or
more.

Not included: focus and iris, and 3D zoom by drawing a box on the picture.
