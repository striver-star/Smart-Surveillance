# HSS Platform

Security Surveillance System for Hikvision NVRs and cameras (working title).
The source of truth for requirements is the AI Collaboration Context Document v0.5
(`docs/context-document-v0.5.md`; the Word version is kept alongside the project).

Current stage: **Phase 0, Discovery and PoC**. See `docs/poc-plan-v0.5.md`.

| Path | What it is |
|---|---|
| `compose.yaml` | Step 0 skeleton: PostgreSQL + PostGIS, API, MediaMTX stream gateway, Caddy (HTTPS) |
| `services/api/` | FastAPI service: health, version, event ingestion and listing |
| `services/ai-worker/` | Tier S AI worker: YOLOX person and vehicle detection with zone rules (task 15) |
| `config/` | Worker camera and zone files (`worker.example.json`, `worker.demo.json`) |
| `compose.demo.yaml` | Demo camera that loops a sample video |
| `tools/fetch-models.sh` | Downloads the open-source models with checksum checks |
| `gateway/mediamtx.yml` | Stream gateway configuration |
| `proxy/Caddyfile` | Reverse proxy and TLS |
| `tools/probe/` | Step 1: read-only NVR capability probe and compatibility matrix |
| `docs/` | Context document, PoC plan and stage checklists (`task-15-tier-s-worker.md`) |

## Step 0: start the skeleton (Linux server with Docker Engine or Podman)

```bash
cp .env.example .env      # then edit .env and set a strong POSTGRES_PASSWORD
docker compose up -d --build
docker compose ps
curl -k https://localhost/api/healthz
```

Expected: all four services `Up`, and the health check returns
`{"api":"ok","database":"ok","postgis":"3.5 ..."}`.

Stop with `docker compose down` (data is kept in the `db-data` volume).

## Step 1: probe the NVRs

The probe sends **GET requests only**; it never changes a device.
Run it from any PC on the NVR network with Python 3.10 or later.

```bash
cd tools/probe
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"
export HSS_NVR_USER=admin          # use a read-only NVR user if you have one
read -rs HSS_NVR_PASSWORD && export HSS_NVR_PASSWORD
hss-probe --host 192.168.1.64 --host 192.168.1.65 --listen-events 60 --out probe-output
```

On Windows (PowerShell) use `py -m venv .venv`, `.venv\Scripts\activate`, and
`$env:HSS_NVR_USER="admin"`; if the password variable is not set the probe asks for it.

Outputs in `probe-output/`:

- `summary.md`: per NVR model, firmware, drives, estimated retention days against the
  30-day target, incoming bandwidth against the 256 Mbps limit, tiers and flagged channels
- `compatibility-matrix.csv`: one row per channel (codecs, bitrates, smart events,
  provisional tier, an empty `tier_override` column for the IT Manager)
- `inventory.json`: everything above in machine-readable form
- `raw/<nvr>/`: the untouched ISAPI responses, so the parser can be improved against real firmware

`probe-output/` holds device details and is ignored by git. Do not share it outside the project.

Run the tests: `cd tools/probe && python3 -m pytest -q`
