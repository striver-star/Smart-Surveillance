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

Not included: PTZ patrols and tours (set them on the NVR or camera), focus and iris, and 3D zoom by
drawing a box on the picture.
