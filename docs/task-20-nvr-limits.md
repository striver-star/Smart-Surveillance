# Task 20: NVR connection and bandwidth limits

**Status:** tool built and tested against a real RTSP server (MediaMTX with Digest login, the
same login method Hikvision uses): 26 probe tests pass. **Waiting on the site run.**

## Why

The gateway pulls each camera once (only while someone watches it) and shares it with every
viewer. At a busy moment the NVR must serve the walls, the AI workers and its own iVMS and phone
users at the same time. Each NVR model has a limit on outgoing bandwidth and sessions; above it,
the NVR refuses new pulls ("453 Not Enough Bandwidth") or every stream stutters.

## What `hss-nvrload` does

1. Reads the NVR's online channels and how many streaming sessions are already open.
2. Opens sub-stream pulls through the NVR in steps (default 8 more every step), holds each step
   20 seconds and measures what every pull receives. It doesn't decode video, so the server's CPU
   doesn't affect the result.
3. Stops at the first step where the NVR refuses or drops a pull, or a pull falls below half of
   its own starting rate, and closes every pull.

By default it goes up to one pull per online camera (the normal platform load). Add
`--max-pulls 64` to go past that and find the real limit; channels then repeat, as several
viewers would. It changes no settings.

## Run it on the server (at a quiet time)

Staff watching the same NVR may see a short stutter if its limit is reached.

```bash
cd ~/Smart-Surveillance && git pull
```
```bash
cd tools/probe && . .venv/bin/activate && pip install -e .
```
One pull per camera on all four NVRs (about 3 minutes per NVR):
```bash
hss-nvrload --host 10.1.3.4 --host 10.1.3.5 --host 10.1.3.6 --host 10.1.3.7
```
Then find the real limit, one NVR at a time:
```bash
hss-nvrload --host 10.1.3.4 --max-pulls 96
```

Send back `probe-output/nvrload/nvrload.md`.

## Reading the result

- **No trouble at one pull per camera, and margin beyond:** pull everything through the NVR (current design).
- **Trouble below one pull per camera plus about 25%:** pull the busiest cameras directly from the
  camera (LAN cameras) instead of through the NVR. The gateway supports both; PoE cameras behind the
  NVR can only be pulled through it.
- "First trouble" can also be a camera going offline during the test: check the problem column.
