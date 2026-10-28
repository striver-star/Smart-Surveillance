# Task 19: wall PC capacity test

**Goal:** find out how many camera tiles one existing wall PC (Intel Core i5, 16 GB RAM) can
play smoothly on the 55 inch Hisense TVs, and whether one PC can drive three TVs. The answer
decides whether a fourth wall PC is needed for the seven screens at 6 NVRs.

## What was built

| Part | Where |
|---|---|
| Test page | `web/wall-test/index.html`, served at `https://SERVER/wall-test/` |
| Camera paths for a whole NVR | `tools/nvr-paths.sh` (writes lines for `gateway/cameras.env`) |
| WebRTC address for wall PCs | `HSS_SERVER_IP` in `.env` |

The page opens one WebRTC session per tile from the stream gateway (the gateway pulls each
camera from the NVR once, and only while someone watches). Every second it measures each tile's
frame rate, dropped frames, freezes and reconnects, reconnects a tile that freezes for 6 seconds,
checks whether the browser has hardware H.264 decoding, and shows a verdict:

- **Keeping up:** all tiles playing, average fps at least 90% of the camera frame rate,
  under 1% of frames dropped, and the page not busy for more than 3 s in the last minute.
- **Not keeping up:** lists the reasons.

Press **D** (or the button) to download the results as JSON. Press **H** to hide the panel.

## Result in the build environment (no GPU, software decoding)

| Run | Result |
|---|---|
| 8 tiles, sample stream 768x576 at 10 fps | Keeping up: 10 fps on every tile, 0% dropped |
| 32 tiles, same stream | Keeping up: 10 fps on every tile, 0% dropped |
| 32 tiles while the AI worker shared the CPU | Not keeping up: 9.8 fps average, 2% dropped (the page caught the overload) |
| Stream cut for 8 s during the test | All 8 tiles froze, reconnected by themselves and played again |

These numbers only prove the page works. The real answer comes from the wall PCs.

## Run it on site

1. On the server, set `HSS_SERVER_IP` in `.env` to the server's LAN address and open UDP port
   8189 and TCP 443 on its firewall.
2. Generate the gateway lines for each NVR (use a view-only NVR user), for example:
   ```bash
   export HSS_NVR_USER=viewer
   read -rs HSS_NVR_PASSWORD && export HSS_NVR_PASSWORD
   tools/nvr-paths.sh nvr1 192.168.1.64 >> gateway/cameras.env
   tools/nvr-paths.sh nvr2 192.168.1.65 >> gateway/cameras.env
   docker compose up -d
   ```
   The script prints the matching test URL with all 32 paths of that NVR.
3. Make sure the camera sub-streams are H.264 (the probe's matrix flags any that are not).
4. On a wall PC, open Chromium in kiosk mode on one TV, for example:
   ```
   chromium.exe --kiosk --user-data-dir=C:\walltest\tv1 --window-position=0,0 "https://SERVER/wall-test/?n=32&label=PC1-TV1&minutes=60&paths=nvr1-ch01,...,nvr1-ch32"
   ```
   For a second or third TV, start another window with its own `--user-data-dir`,
   `--window-position` on that TV, and the paths of another NVR. Press Alt+F4 to close a window.
5. Open Task Manager on a laptop-free corner of the screen or over remote desktop and note CPU,
   GPU "Video Decode" and memory every 10 minutes.
6. After 60 minutes press D in each window and keep the JSON files.

**Runs to do, in order** (stop when one fails):

| Run | Screens on one PC | Tiles | What it tells us |
|---|---|---|---|
| A | 1 TV | 32 (one NVR) | Baseline |
| B | 2 TVs | 32 + 32 | The planned one PC per two TVs |
| C | 3 TVs | 32 + 32 + 32 | Whether 3 PCs can drive 7 screens without a fourth PC |
| D | 1 TV | rotation screen (4 main streams) + 2 TVs of grids | Mix used in Phase 2 |

**Pass for a run:** the page says "Keeping up" for the full hour, CPU stays below 70% on
average, and nothing looks wrong on the TVs.

## Things to check while testing

- **Chromium build:** if no tile plays and the page reports errors, this Chromium build may not
  include H.264. Try another Chromium build or Firefox; note which one works.
- **Hardware decoding:** the panel shows whether hardware H.264 decoding is available. If it says
  "not available" on the i5 PCs, update the Intel graphics driver and check `chrome://gpu`.
- **TV settings:** PC or Game mode, overscan off, eco standby and auto input switching off,
  1920x1080 output (4K output adds GPU load without making 32 small tiles clearer).
- **Windows:** turn off sleep and screen-off, and pause Windows Update during the test.

## Checklist

- [ ] `https://SERVER/wall-test/` opens on a wall PC (accept the certificate warning only for this test)
- [ ] Run A finished with "Keeping up"; JSON saved
- [ ] Run B finished; JSON saved
- [ ] Run C finished; JSON saved; decision recorded: 3 TVs per PC, or buy a fourth PC
- [ ] CPU, GPU and memory notes kept with the JSON files
