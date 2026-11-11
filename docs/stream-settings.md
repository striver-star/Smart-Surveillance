# Changing stream settings on all NVRs (hss-streams)

`hss-streams` switches camera stream codecs on many NVRs at once, through each NVR (cameras on
the NVR's PoE ports included). It is part of the probe package in `tools/probe`.

- **Sub-streams to H.264** (`--sub-h264`): needed so the wall screens can play them in a browser.
- **Main streams to H.265** (`--main-h265`): roughly halves storage for cameras still on H.264.

It is safe by design:

- Without `--apply` it only shows what would change.
- It changes only the codec; every other setting (resolution, bitrate, frame rate) is sent back as it was.
- It skips offline cameras, streams already on the target codec, and cameras that do not offer it.
- Before each change it saves the old settings; afterwards it reads the setting back to confirm it.
- It writes a report and can put everything back with `--restore`.

Changing a sub-stream briefly interrupts that camera's sub-stream (live view on phones and the
wall). Main-stream recording continues. Changing a main stream restarts it for a few seconds, so
a few seconds of recording are lost on that camera; do main streams at a quiet time.

## Use

```bash
cd ~/Smart-Surveillance-main/tools/probe && . .venv/bin/activate && pip install -e .
export HSS_NVR_USER=admin
read -rs HSS_NVR_PASSWORD && export HSS_NVR_PASSWORD
```

1. Preview every NVR:
   ```bash
   hss-streams --host 10.1.3.4 --host 10.1.3.5 --host 10.1.3.6 --host 10.1.3.7 --sub-h264
   ```
2. Try one camera first, then check its live view on the NVR:
   ```bash
   hss-streams --host 10.1.3.4 --channels 1 --sub-h264 --apply
   ```
3. Do the rest:
   ```bash
   hss-streams --host 10.1.3.4 --host 10.1.3.5 --host 10.1.3.6 --host 10.1.3.7 --sub-h264 --apply
   ```
4. Run the probe again; the "sub-stream is H.265" flags should be gone.

Undo a run (the folder name is printed at the end of each run):

```bash
hss-streams --restore stream-backups/20261111-120000 --apply
```

The `stream-backups/` folder holds camera settings; keep it on the server and out of git.

## Results meaning

| Result | Meaning |
|---|---|
| changed | Done and confirmed |
| changed (camera asks for a reboot) | Saved; the camera applies it after its next restart |
| refused: … | The NVR or camera rejected the change; the reason code follows |
| not confirmed: … | Accepted but the camera still reports the old codec; check it in the NVR web page |
| skip: camera does not offer H.264 | This camera model cannot do it; the gateway will need to convert its video |
