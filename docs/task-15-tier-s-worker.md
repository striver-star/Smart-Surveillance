# Task 15: one non-AI camera end to end through a Tier S worker

**Goal:** a non-AI camera's sub-stream goes through the stream gateway to the AI worker, which
detects people and vehicles inside a zone and posts a normalized event (with a snapshot) to the
API within 3 seconds.

## What was built

| Part | Where | Notes |
|---|---|---|
| Event schema and storage | `services/api/app/migrations/001_events.sql` | Section 8 fields; `tier`, `source_kind`, geotag column ready |
| Event API | `services/api/app/events.py` | `POST /events` (worker token), `GET /events`, `GET /events/{id}/snapshot` |
| AI worker | `services/ai-worker/` | YOLOX on ONNX Runtime; TensorRT/CUDA, OpenVINO or CPU; PyAV (LGPL FFmpeg) decoding |
| Zone rules | `services/ai-worker/worker/rules.py` | Polygons in 0-1 coordinates, foot-point test, schedules, 3-of-5 frame confirmation, cooldown |
| Camera sources | `gateway/cameras.env` (from `cameras.env.example`) | Each NVR channel pulled once by the gateway |
| Demo camera | `compose.demo.yaml` | Loops a sample video so the chain can be tested without site hardware |

## Result in the build environment (CPU only, no GPU)

- Sample video (768x576, people walking) streamed through MediaMTX to the worker.
- People in the zone detected and posted as `critical` `intrusion` events with snapshots.
- **Latency from frame decode to event stored: 160 to 260 ms** (target under 3 s).
- YOLOX-S inference on CPU: about 120 to 160 ms per frame, 4 to 5 analysed frames per second for one camera.
- API stopped for 25 s: events were queued and delivered in order when it came back.
- Not measured yet: the delay from the camera to the gateway (needs a real camera; see step 6 below).

## Run it on site

1. On the server, fetch the models: `./tools/fetch-models.sh`
2. Pick one non-AI camera (Tier S in the probe's matrix). Copy `gateway/cameras.env.example`
   to `gateway/cameras.env` and set its sub-stream, for example channel 3 of NVR 1:
   `MTX_PATHS_NVR1-CH03_SOURCE=rtsp://viewer:PASSWORD@192.168.1.64:554/Streaming/Channels/302`.
   Use an NVR user that can only view live video.
3. Copy `config/worker.example.json` to `config/worker.json`. Set the `camera_id` and `source`
   (`rtsp://gateway:8554/nvr1-ch03`) and draw the zone as corner points between 0 and 1
   (0,0 is top left; 1,1 is bottom right). Remove `armed` to test in daytime.
4. In `.env` set `HSS_WORKER_TOKEN` (`openssl rand -hex 32`). On a slow CPU set `HSS_MODEL=yolox_nano.onnx`.
5. Start: `docker compose --profile ai up -d --build`, then `docker compose logs -f ai-worker`.
6. Walk into the zone. Check `https://SERVER/api/events?limit=5` and open the `snapshot_url`.
   To measure the full delay, hold a phone showing a clock with seconds in front of the camera
   and compare it with `occurred_at` on the event.

To try the demo first (no camera needed): `./tools/fetch-models.sh --demo`, then
`docker compose -f compose.yaml -f compose.demo.yaml --profile ai up -d --build`.

## Checklist

- [ ] `python3 -m pytest -q` passes in `services/ai-worker` (8 tests)
- [ ] Demo run shows events in `docker compose logs ai-worker` with latency under 3000 ms
- [ ] On site: walking into the zone of a non-AI camera creates one event, not a burst
- [ ] The snapshot shows a box around the person
- [ ] Clock test: full delay (camera to event) under 3 s
- [ ] A person outside the zone, or during disarmed hours, creates no event
- [ ] `docker compose logs ai-worker` reports the analysed fps and inference time; note them for task 16

## Known limits (to address in later tasks)

- One inference at a time per worker; more cameras need more workers or a GPU (task 16 measures this).
- No object tracking yet: a person standing in the zone triggers again after the cooldown.
- The gateway API is closed; the gateway itself still accepts any reader or publisher on the
  server network. Gateway authentication comes with Phase 2 (live viewing).
- The NVIDIA image (`Dockerfile.gpu`) is written but not yet tested; it needs the GPU server.
