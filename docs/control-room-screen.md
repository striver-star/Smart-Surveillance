# Control-room large-screen mode

Release 2.0, second batch. A wall screen can be a **status board** instead of a camera grid: everything the
control room needs at a glance, readable across the room on a 55-inch TV.

| Part | Shows |
|---|---|
| Top row | Open alerts (critical, warning), not acknowledged (and how long the oldest has waited, how many escalated), cameras online, NVRs (drive faults, unreachable), guards reporting, wall PCs online |
| Site map | The chosen site plan with zones, cameras (red blinking = critical alert, amber = warning, grey = offline) and guards |
| Live | The camera of the newest unacknowledged critical alert, playing live |
| Open alerts | Unacknowledged first, critical first, newest first: picture, what, where, how long it has waited, who acknowledged it |
| Shift and patrols | Current shift and when it ends, latest checkpoint check-ins, latest logbook entries |
| Lockdown | The red lockdown banner across the top while the site is in lockdown |

It refreshes every 10 seconds. Like camera screens it keeps showing the last board if the server is busy or
restarting, with the amber "Platform unreachable" note.

## Setting up

1. **Video walls › Add screen** (administrator): Type **Control-room status board**, and pick the site map to show
   (or none: then the live camera takes the map's place).
2. Assign the screen to a TV in **Wall PCs** like any other screen. Nothing changes on the wall PC.
3. Tip: put the board on the TV operators face, and camera grids on the others.

## What the board's link can see

The board needs no sign-in (it uses its screen key, like camera screens), so it is limited to what it shows:
pictures of **open** alerts, its own site plan, and live video only of cameras with an open alert. The key
can be changed with **New link** in the screen's settings.
