# Task 23: Licence scan and SBOM

**Status: done 2026-11-12. Result: PASS** (242 components: 232 permissive, 10 allowed under a
stated condition, none denied or unknown). Engineering guidance against Section 19 of the context
document, not legal advice.

- Report: [`docs/sbom/licence-report.md`](sbom/licence-report.md)
- Software bill of materials (CycloneDX 1.5): [`docs/sbom/sbom.cdx.json`](sbom/sbom.cdx.json)
- Tool: `tools/licence-scan/` (`scan.py`, `policy.json`, `components.json`, optional `waivers.json`)
- Runs on every push to GitHub (`.github/workflows/checks.yml`); a disallowed or unknown licence fails the build.

## What is scanned

| Source | How |
| --- | --- |
| Python (API, AI worker, probe tool) | Installs each project's pinned requirements for Linux x86_64 / Python 3.12 (the image version) and reads each package's licence metadata |
| Native libraries inside Python wheels | Reads the licence string compiled into FFmpeg (`libavcodec license: ...`) and flags GPL-only libraries such as x264 and x265 by file name |
| Node (WhatsApp gateway) | `npm ci --omit=dev` from the lock file, licence field of each installed package |
| Go (Wall Agent) | `go list -m all`; the agent uses only the Go standard library (BSD-3-Clause) |
| Container images, OS packages, models, datasets, build tools, declared exceptions | `components.json`, checked by hand with a date; re-check when a version changes |

Rules (`policy.json`): permissive licences pass; LGPL passes as an unmodified library; GPL and AGPL
pass only as a separate, unmodified program (a GPL library loaded into our own process fails);
source-available, non-commercial and paid licences fail; anything the tool cannot identify fails
until someone checks it and records a waiver with the reason.

## Finding fixed during the scan: PyAV carried GPL code

The AI worker decoded camera streams with PyAV. Its FFmpeg is an LGPL build, but the PyAV 19
wheel also bundles **libx264 and libx265, which are GPL-2.0**, loaded into the worker's process.
Section 19 does not allow that.

Fix: the worker now decodes with OpenCV, which was already a dependency and bundles an LGPL-2.1
FFmpeg (no GPL libraries). PyAV is removed. Tested here with H.264 and H.265 RTSP streams over TCP
through MediaMTX 1.9.3 (the gateway version we run), including reconnecting when a stream drops.
All 10 worker tests pass. **On the server:** rebuild the worker with
`docker compose --profile ai up -d --build ai-worker` and check its log shows
`connected (h264 ...)` or `connected (hevc ...)` for each camera.

## Items allowed under a condition

| Component | Condition |
| --- | --- |
| FFmpeg inside OpenCV (LGPL-2.1) | Used unmodified as a shared library |
| psycopg (LGPL-3.0), node-webpmux (LGPL-2.1) | Used unmodified as libraries |
| PostGIS in the database image (GPL-2.0) | Runs unmodified as part of the database server; we talk to it over the network |
| NVIDIA TensorRT image (GPU worker only) | Pulled from NVIDIA on the server. **Never push the built GPU image to a public registry or ship it to clients.** Re-check NVIDIA's terms before a hosted release |
| NVIDIA driver and CUDA, Windows on wall PCs, Hikvision devices, WhatsApp | Declared exceptions in Section 19 |

## Actions for Phase 1 (not blocking the proof of concept)

1. **Our own licence.** The repository has no LICENSE file. Since the product is licensed per site,
   add a proprietary licence and copyright notice before the first client release (the builder's
   decision, ideally with the legal reviewer).
2. **Third-party notices.** When we ship images or installers to a client, include the licence texts
   of the components in the SBOM (a `THIRD-PARTY-NOTICES` file generated from it). LGPL components
   must stay replaceable, which they are as Python and Node packages.
3. **Model training data.** The YOLOX weights are Apache-2.0 and were trained on COCO. If we fine-tune
   models later, use only datasets that allow commercial use, and add them to `components.json`.
4. **Security, not licence:** the OpenCV wheel bundles OpenSSL 1.1.1k, which no longer receives
   security updates. It's used only if FFmpeg opens an `https`/`rtsps` link; our cameras use plain RTSP
   on the local network. Watch for an OpenCV release with a newer OpenSSL.

## Running it

```bash
python3 tools/licence-scan/scan.py
```

It needs Python 3, pip, npm and Go, and internet access to PyPI and npm. It takes about a minute
and rewrites `docs/sbom/`. To add a dependency, model, dataset or image: add it, run the scan, and
for anything not read from a package manager add an entry to `components.json` with its source
and the date you checked it.
