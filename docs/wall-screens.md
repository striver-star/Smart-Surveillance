# Video wall screens (Phase 2)

Each TV on the video wall shows a **screen**: a grid of cameras. Screens are made on the console's
**Video walls** page and assigned to the TVs of each wall PC. The Wall Agent on the PC opens the screen
full screen, restarts the browser if the page stops, and picks up changes within a minute.

## Make screens

- **Add a screen per NVR** makes one screen for every NVR that doesn't have one: all of its cameras on
  a 32-tile grid (8 × 4), or 16 tiles for small NVRs. These are the 32-channel NVR screens.
- **New screen** for anything else:
  - *Shows*: cameras you pick, all cameras of one NVR, or all cameras.
  - *Grid*: 1, 4, 6, 9, 16, 25, 32 (8 × 4), 36 or 64 tiles.
  - *Seconds per page*: when there are more cameras than tiles, the screen shows a page at a time
    and moves on after this many seconds. "All cameras" on 16 tiles is a **rotation screen** that
    walks through the whole site.
  - *Keep cameras with open alerts on screen*: a camera with an open warning or critical alert is
    put first on every page and outlined (amber for warning, red and pulsing for critical) until the
    alert is closed in the console.
- **Open** shows the screen in a new browser tab, to check it before assigning it.
- Edits reach the TVs within 10 seconds, without restarting anything.

## Put screens on the TVs

On the same page, **Wall PCs** → **Assign screens**: choose a screen for each TV of that PC. TV 1 is
the left-most display (Windows: Settings › System › Display shows the order). The wall PC switches
within a minute. A TV with no screen shows "Assign a screen to this TV in the console" (Wall Agent 0.2
and later).

On the wall PC itself, **F** puts the page in full screen if the agent hasn't, and the left and right
arrow keys change page on a rotation screen.

## How it plays

- Cameras play the **sub-stream** over WebRTC from the stream gateway, which pulls each camera from its
  NVR once, however many TVs show it. Lost or frozen tiles reconnect on their own with back-off.
- The screen's link (`/wall/?s=<number>&k=<key>`) works without signing in, so the wall PCs need no
  user accounts. The key only lets a page see which cameras to play. **New link** (in Edit) changes
  it; wall PCs showing that screen move to the new link automatically, and the old link stops working.
- The page reports to the Wall Agent every 5 seconds (tiles, how many are playing, frozen tiles); the
  console shows "n/m playing" and "page stalled" per TV.

## Sizing (from task 19)

One Core i5 wall PC is expected to handle about 32 sub-stream tiles per TV. Repeat the task 19 two-TV
test once the server is wired at 1 Gbps (the earlier 20% drops were measured over Wi-Fi), then decide
the screens per PC. Seven NVRs need a fourth wall PC.

## Updating the Wall Agent

Build and publish version 0.2.0 on the server (`services/wall-agent/build.sh 0.2.0`); wall PCs update
themselves at their next check. 0.2.0 only changes the page shown on TVs without a screen.

Gate for Phase 2: real wall PCs showing all six (later seven) NVRs' screens through a working day.
