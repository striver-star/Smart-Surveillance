# Verification checklist: Steps 0 and 1

Step 0 (on the Linux server):
- [ ] `docker compose ps` shows db, api, gateway and proxy as Up
- [ ] `curl -k https://localhost/api/healthz` shows database ok and a PostGIS version
- [ ] `.env` exists, has a strong password and is not committed to git

Step 1 (from a PC on the NVR network):
- [ ] `python3 -m pytest -q` in `tools/probe` passes
- [ ] The probe runs against one NVR and `summary.md` shows the right model and firmware
- [ ] Channel count in `compatibility-matrix.csv` matches the NVR's own channel list
- [ ] Drive sizes and the estimated retention look right against the NVR's storage page
- [ ] With `--listen-events 60`, walking past an AcuSense camera shows an event in the summary
- [ ] Probe repeated on all 6 NVRs; `probe-output/` zipped and kept safe (it holds device details)
