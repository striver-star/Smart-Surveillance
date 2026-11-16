# Face and plate recognition, stage 4 (go-live)

Release 2.0. Live recognition against watchlists on approved cameras, with operator confirmation. It runs only
while the face and plate legal review is accepted (console: Face & plate) and stops within a minute if it is
withdrawn or expires. Stages 1 to 3 (suitability, plate trial, volunteer walk test) are in task-18-face-plate.md.

## How it works

1. The CSO or an administrator enrols people (2 to 5 photos each) and plates on the **Face & plate** page. Every
   entry needs a list, a reason, a consent or legal authority reference and an expiry date (at most 12 months).
2. The **recognition service** (`docker compose --profile recognition up -d`) reads the approved cameras' **main
   streams** straight from the NVRs (the gateway carries sub-streams only, too small for faces), about 3 frames a
   second per camera.
3. Each face is checked for quality (size, turn, blur) and compared with the watchlist; each plate read on the lane
   area is compared with the plate list. **Only matches are sent to the platform.** Unmatched faces and plates are
   discarded in memory; nothing about them is stored.
4. A match raises an alert (severity by list). The operator compares the enrolment photo with the camera picture and
   presses **Confirm: same person** (the alert is acknowledged) or **Not a match** (the alert is closed as a false
   alarm). Any siren or light the alert started switches off.
5. Verdicts (camera, score, outcome; no names) build the accuracy figures on **Face & plate › Accuracy**, with a
   suggested threshold once there are 20 verdicts.

| List | Alert | Use |
|---|---|---|
| Barred | critical | People barred from site (dismissal, trespass notice) |
| Watch | warning | People the CSO must be told about |
| VIP | none (event only) | Visitors to be met |
| Trial volunteers | warning | Stage 3 walk test volunteers (consent form) |
| Plates: Blocked | critical | Vehicles barred from site |
| Plates: Watch | warning | Vehicles to be checked |
| Plates: Allowed | none | Staff vehicles (nothing is raised) |

## Setting up

1. Face & plate › **Cameras and thresholds**: tick Faces and/or Plates for each camera. Use cameras that passed the
   stage 1 suitability test (40 pixels or more between the eyes; plates 130 pixels wide or more). The cameras must be
   on NVRs added in **Devices**, so the service can read their main stream. For plates, enter the lane area as
   fractions `x1,y1,x2,y2`.
2. Start with the threshold the stage 3 walk test supports (default 0.40, margin 0.06). Raise it if operators reject
   matches; the Accuracy tab suggests a value.
3. Start the service:
   ```bash
   docker compose --profile recognition up -d --build
   ```
4. Enrol the stage 3 volunteers on **Trial volunteers** first, walk past, and check that matches arrive and that the
   operators' verdicts are right.

Photos are checked within a minute: **used**, or **not usable** with the reason (no face, more than one face, too
small, turned away, blurred). A person is matched only once at least one photo is usable.

## Privacy controls (from the DPIA and the legal review)

- Watchlist only; no "who is this" search. Unmatched faces and plates are discarded at once.
- Only the CSO and administrators manage watchlists, and only while the legal review is in force.
- Entries expire within 12 months and stop matching on their expiry date; the compliance report warns 14 days ahead.
  Pausing an entry stops it matching at once.
- Deleting a person deletes their photos and face data. Earlier match alerts keep their own snapshot until retention.
- Match records are deleted after `HSS_RECOGNITION_DAYS` (default 30) unless their alert is still open. Evidence
  sealed into the vault follows the vault's own retention.
- Audited: adding, changing and deleting entries and photos, viewing enrolment photos (once per person and viewer
  per 10 minutes), camera and threshold changes, and every verdict. Viewers and clients can't see matches.
- Uploaded photos are re-encoded: location and device data (EXIF) are removed.

## Files

API `services/api/app/recognition.py`, migration `021_recognition.sql`; service `services/ai-worker/worker/recognition.py`
(reuses `face.py` and `plate.py`); console: Face & plate page and the alert drawer.
