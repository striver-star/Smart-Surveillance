# Task 13: Camera classes, firmware and zones through the NVR

**Status:** tool built and tested against simulated NVRs and cameras (18 probe tests pass).
**Waiting on the site run.**

## Why a second tool

`hss-probe` asks the NVRs. NVR4 (DS-7632NXI-K2/16P) reports its own AI for every channel, so the
NVR's answers can't tell a ColorVu, an AcuSense and a basic camera apart. `hss-cameras` asks each
**camera** directly, read-only (GET requests only, nothing is changed):

| Question | Where the answer comes from |
| --- | --- |
| Model, firmware, serial | camera `/ISAPI/System/deviceInfo` |
| ColorVu or hybrid light | camera supplement light modes (white light only = ColorVu), then the model code |
| AcuSense | camera smart rules offer human/vehicle target filtering, then the model code (G2 and later with -I) |
| Where the AI runs (tier) | **E** camera has smart events; **N** camera has none but the NVR offers AI for the channel (limited number of channels); **S** neither, our server AI is needed |
| Clock | camera time and NTP mode, compared with the server clock |
| Can we send zones through the NVR? | NVR `/ISAPI/Smart/FieldDetection/<ch>` and `LineDetection/<ch>` readable per channel |

The class is a best guess from evidence, listed in the `class_evidence` column. An administrator can
override it in the platform.

## Reaching the cameras

- **Cameras on the site LAN** (NVR4's 10.1.3.x cameras, and those on 10.1.3.5): asked directly at the IP the NVR uses.
- **PoE cameras behind NVR_1 and NVR2** (192.168.254.x, plugged into the NVR): not reachable from the
  server. The tool tries the NVR's **Virtual Host** ports (NVR_IP:65001 and up), which forward to the
  cameras' web servers, and matches each camera to its channel by IP address. If Virtual Host is off,
  enable it on each PoE NVR first:
  NVR web page → **Configuration → Network → Advanced Settings → Other / More Settings → Enable Virtual Host** → Save.
  (The menu name varies a little between firmware versions.) It doesn't affect recording or live view.

If the cameras use a different password from the NVR, pass `--camera-user` and the tool asks for the
camera password.

## Run it on the server

1. Update and reinstall the tools:
   ```bash
   cd ~/Smart-Surveillance && git pull
   ```
   ```bash
   cd tools/probe && . .venv/bin/activate && pip install -e .
   ```
2. Survey all four NVRs (about 2 to 5 minutes):
   ```bash
   hss-cameras --host 10.1.3.4 --host 10.1.3.5 --host 10.1.3.6 --host 10.1.3.7
   ```
3. Send back `probe-output/cameras/cameras-summary.md` and `cameras.csv`. The `raw/` folder holds every
   response if something needs a closer look; it contains no passwords but does contain serial
   numbers, so keep it on site.

## Walk test (after the survey)

The summary suggests one camera per class (ColorVu, AcuSense, non-AI). For each:

1. Start listening on its NVR:
   ```bash
   hss-probe --host <NVR> --listen-events 300 --out probe-output/walk-<class>
   ```
2. Walk through the camera's view (and across a line or into a zone if one is set).
3. Check `probe-output/walk-<class>/summary.md` lists the events on the right channel.

That confirms "each class's events arrive through the NVR", the pass mark for task 13. Repeat for a
second firmware version of the same model if the summary shows one.

## What the results feed

- The tier of each camera in the inventory (E, N or S), which sets how much GPU the server needs (task 16).
- Which channels can take platform-drawn zones through the NVR, and which need Tier S zones.
- The firmware update list (old K4 firmware was already noted).
- The NTP fix list: every camera and NVR off by more than 30 seconds or not set to NTP.
