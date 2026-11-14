# Task 18: Face and number plate recognition

**Status (2026-11-14):** engine and trial tool built and tested on sample photos and synthetic
plates (14 AI worker tests pass, licence scan passes with two waivers for the legal reviewer).
**Stage 1 (camera suitability, no identification) approved 2026-11-14; tool ready.** Stages 2 to 4 wait on the legal gate (task 4).

This is engineering guidance, not legal advice. Every step marked "legal" needs the legal
reviewer's approval first.

## What was built

| Part | File | What it does |
| --- | --- | --- |
| Face engine | `services/ai-worker/worker/face.py` | YuNet detection, quality checks (size, turn, blur), SFace embeddings, watchlist matching |
| Plate reader | `services/ai-worker/worker/plate.py` | PaddleOCR PP-OCRv4 text detection and reading, clean-up to the Nigerian format (`ABC 123 DE`), allow/block lists |
| Trial tool | `services/ai-worker/worker/recognition_trial.py` | Runs on one camera or clip; reports camera suitability, matches to confirm, plate reads, timings |
| Watchlist | `config/watchlist/` (copy from `config/watchlist.example/`) | Enrolled people (with consent reference) and plate lists; git ignores it |

Privacy is built in: watchlist matching only (no open-ended identification), unmatched faces are
counted and discarded, no face images are kept unless `--save-matches` is given (then only of
matches), a person without a consent or authority reference is not enrolled, and every match is a
lead for an operator to confirm.

## Results so far (sample data, not site data)

| Check | Result |
| --- | --- |
| Same person, smaller, tilted, darker, blurred | similarity 0.86 (threshold 0.40) |
| Different person | similarity 0.13 |
| Faces too small (eyes under about 28 px apart) | rejected as "too small" |
| Synthetic Nigerian plates, 114 to 234 px wide, tilted and blurred | 4 of 4 read correctly, including `LND1170S` corrected to `LND 117 OS` |
| Speed on CPU (sandbox) | faces about 28 ms per frame, plates about 57 ms per region |

The synthetic plates are clean and printed in a plain font. Real plates (embossed characters,
dirt, glare, headlights, infrared at night) will read worse. **Accuracy must be measured on the
site's own entrance footage**; that is what the trial is for.

## Model licences (see docs/sbom/licence-report.md)

The weights are permissively licensed: YuNet MIT, SFace Apache 2.0, PP-OCRv4 Apache 2.0. But the
face models were trained on research face datasets (WIDER FACE for YuNet; CASIA-WebFace, VGGFace2
or MS1M for SFace) whose terms are non-commercial research only. We don't ship or use those
datasets, but Section 19 excludes non-commercial datasets, so they are recorded as **waivers
pending the legal reviewer**. If the reviewer rejects them, the alternative is a face model trained
on permissively licensed or consented data (or the cameras' own face features, below).

## Edge first: what the site's devices can already do

From the camera survey (task 13): NVR4 (DS-7632NXI-K2/16P) offers face capture and face picture
events on its channels (NVR AI, limited to a few channels at once), and three camera models are
AcuSense. No dedicated ANPR or face-capture cameras were found. Plate reading therefore runs on
our server; for faces, NVR4's face capture is worth comparing on one entrance channel.

## Proposed staged trial (for the legal reviewer to approve)

| Stage | What | Personal data | Needs |
| --- | --- | --- | --- |
| 1. Camera suitability | Trial tool with an **empty** watchlist on 3 to 5 entrance cameras for a day: counts faces and measures face size, turn and blur. Nobody is identified; nothing but counts is kept | Faces processed in memory only, not stored or identified | Client's written OK; legal reviewer's view on whether this needs a DPIA |
| 2. Plate reading | Trial tool on the main gate with an allow list of staff vehicles; compare each read with the recording to get read accuracy, day and night | Plate numbers (personal data) | Legal; signage; retention limit (for example 30 days) |
| 3. Volunteer face walk test | 3 to 5 staff volunteers with signed consent forms enrolled; they walk past the entrance cameras at set times; measure true matches and false matches | Biometric (sensitive) data of consenting volunteers | Legal; consent forms; DPIA; delete enrolments and results after the trial |
| 4. Go-live | Watchlists as approved | Sensitive | Full legal gate: counsel review, DPIA, lawful basis, signage, access and retention limits, written client sign-off |

Suggested cameras (from the survey): MAIN GATE ENTERANCE (NVR4 ch22, DS-2CD2T43G2-2I, AcuSense,
2688x1520), SECURITY CHECK 1 and 2 (NVR4 ch23 and ch17), Main Gate Exit 1 and 2 (NVR_1 ch19 and
ch2), Gate House and Gate Arrival 02 (10.1.3.5 ch6 and ch10). Recognition needs the **main
stream**: sub-streams are too small for faces.

## Stage 1 on the server: camera suitability (approved 2026-11-14)

`worker.suitability` watches each camera's main stream in turn, finds faces, measures them (size,
turn, blur, brightness) and forgets them. It also counts people in view, so "nobody passed" and
"faces too small" can be told apart. **Nobody is identified:** no face templates are made, no
watchlist is used, no plates are read, no images are saved (an automated test enforces this).
Please keep the client's written OK for this stage with the trial records.

1. Update, fetch the models and rebuild the AI worker:
   ```bash
   cd ~/Smart-Surveillance && git pull && bash tools/fetch-models.sh
   ```
   ```bash
   docker compose --profile ai build ai-worker
   ```
2. Give the NVR login for this shell only (not saved anywhere):
   ```bash
   read -p "NVR user: " HSS_NVR_USER; read -s -p "NVR password: " HSS_NVR_PASSWORD; echo; export HSS_NVR_USER HSS_NVR_PASSWORD
   ```
3. Start the run in the background (7 entrance cameras, 20 minutes each, about 2 hours 20 minutes).
   Start it about 7:00, so the morning arrivals are covered:
   ```bash
   mkdir -p trial-output && docker compose --profile ai run -d --name hss-suitability \
     --user "$(id -u):$(id -g)" -e HSS_NVR_USER -e HSS_NVR_PASSWORD -v "$PWD/trial-output:/data/trial" \
     ai-worker python -m worker.suitability --minutes 20 --out /data/trial/suitability-day \
     --camera "Main gate entrance=10.1.3.4:22" --camera "Security check 1=10.1.3.4:23" \
     --camera "Security check 2=10.1.3.4:17" --camera "Main gate exit 1=10.1.3.6:19" \
     --camera "Main gate exit 2=10.1.3.6:2" --camera "Gate house=10.1.3.5:6" --camera "Gate arrival 02=10.1.3.5:10"
   ```
   Follow it with `docker logs -f hss-suitability` (Ctrl+C stops following, not the run). Results
   so far are written after each camera, so a stopped run still leaves a report.
4. Repeat after dark with `--out /data/trial/suitability-night` (and `docker rm hss-suitability` first).
5. Send back `trial-output/suitability-day/suitability.md` and the night one. They contain only counts.

## Running the full trial (stages 2 and 3 only, after legal approval)

Not for stage 1. On a live camera this tool refuses to start without `--approval "<legal approval reference>"`.

1. Update and fetch the new models:
   ```bash
   cd ~/Smart-Surveillance && git pull && bash tools/fetch-models.sh
   ```
2. Rebuild the AI worker:
   ```bash
   docker compose --profile ai build ai-worker
   ```
3. Stage 1 (empty watchlist, faces and plates), 30 minutes on the main gate main stream:
   ```bash
   mkdir -p config/watchlist trial-output
   docker compose --profile ai run --rm --user "$(id -u):$(id -g)" \
     -v "$PWD/config/watchlist:/config/watchlist:ro" -v "$PWD/trial-output:/data/trial" \
     ai-worker python -m worker.recognition_trial --name "Main gate entrance" --minutes 30 \
     --source "rtsp://USER:PASSWORD@10.1.3.4:554/Streaming/Channels/2201" --out /data/trial/main-gate
   ```
   For a fixed entrance lane, add `--plate-roi 0.2,0.4,0.8,0.9` (fractions of the frame) to read
   plates in that region instead of looking for vehicles first.
4. Read `trial-output/main-gate/trial-summary.md`. Delete `trial-output/` when the trial ends.

The server must be wired (task 20) before long trials: one main stream fits on Wi-Fi, several don't.
