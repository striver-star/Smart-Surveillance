# Legal review for face and number plate recognition

The review itself is [services/api/app/legal/face-plate-review.md](../../services/api/app/legal/face-plate-review.md).
The console shows it on the **Face & plate** page, and the software uses that file to lock and unlock the features.

## How the lock works

- Face and plate recognition are **locked** until an administrator, signed in with two-factor, opens the
  review in the console, reads it to the end (at least 2 minutes), ticks all ten conditions in section 14,
  and records the legal opinion (practitioner, firm, reference, date) and the DPIA reference.
- The acceptance covers plate, face or both; lasts **12 months**; and applies to that exact text. Any edit
  to the review file changes its version and locks the features until it is accepted again.
- The administrator or the CSO can **Withdraw and lock** at any time.
- While locked: face match and plate events are dropped by the API (not stored), and the recognition trial
  (`python -m worker.recognition_trial`) refuses to run. Stage 1 (`worker.suitability`, no identification)
  and ordinary events (including face capture without identification) are not affected.
- Every acceptance and withdrawal is in the audit log and the page's history.

`--sample` lets the trial tool run on a sample video file with no site footage and no real watchlist, to
test the engine before acceptance. Using it on site recordings defeats the purpose of the lock.

## Before accepting

1. Send the review to the legal practitioner (task 4) and get a written opinion.
2. Complete and sign the DPIA (section 7).
3. Put up the signs and publish the notices (section 8); adopt the watchlist rules (section 9).
4. Then accept in the console, choosing only the features the opinion covers.

The review is engineering guidance prepared for counsel, not legal advice.
