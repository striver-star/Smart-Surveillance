# Acceptance test (Phase 9 gate: client acceptance)

Run on the live site with the client's CSO and IT Manager. Each test records pass or fail and a note.
The system is accepted when every test marked **Must** passes and every failed **Should** has an agreed
fix date.

| # | Area | Test | Expected | Priority | Result | Note |
|---|---|---|---|---|---|---|
| 1 | Sign-in | An operator signs in; an admin signs in with two-factor | Each sees only their role's pages | Must | | |
| 2 | Devices | All NVRs added; Devices shows every channel online or explained | Matches the NVRs' own channel lists | Must | | |
| 3 | Live view | 16 cameras on a PC and 4 on a phone for 10 minutes | Video under 2 s behind, recovers by itself after a cable pull | Must | | |
| 4 | Video wall | Each wall PC shows its assigned screens for a full shift | No stalled TV; agent restarts a closed browser within a minute | Must | | |
| 5 | Events | Walk test on every perimeter and gate camera | Each camera raises its alert within 5 s | Must | | |
| 6 | Alerts | Acknowledge, assign, note, close as real incident | Timeline complete; evidence sealed automatically | Must | | |
| 7 | Escalation | Leave a critical alert unacknowledged | Escalation reaches the escalation recipients on WhatsApp after the set time | Must | | |
| 8 | Clips | Critical alert on a recording camera | Clip of the event plays in the console and on iPhone | Should | | |
| 9 | Device faults | Unplug a camera; then reconnect | "Camera offline" alert, then "back online" note | Must | | |
| 10 | WhatsApp | Daily report and a test alert | Delivered to GM, CSO, IT Manager | Must | | |
| 11 | Reports | Weekly report as PDF and Word | Correct counts, names, site branding | Must | | |
| 12 | Evidence | Download a sealed package; verify its SHA-256 on another PC | Hash matches; custody log shows the download | Must | | |
| 13 | Site map | Guard walks into a restricted zone and presses SOS | Zone alert and SOS alert with the linked camera pinned on the wall | Should | | |
| 14 | Patrols | Skip a checkpoint for its interval | Missed patrol alert | Should | | |
| 15 | Backup | Nightly backup and a restore test | Both reported OK on the Security page | Must | | |
| 16 | Security | Security page | No red items | Must | | |
| 17 | Load | Load test on the site server (docs/load-test.md) | PASS | Must | | |
| 18 | Power | Pull power to the server, then restore | Back in service by itself within 5 minutes; no data lost | Should | | |
| 19 | Face and plate | Only if unlocked: plate on the watchlist drives in | Match alert reviewed by a person before any action | Should | | |
| 20 | Training | Competency checks | Every operator and the CSO passed | Must | | |

## Sign-off

| | Name | Signature | Date |
|---|---|---|---|
| Client representative (General Manager) | | | |
| Chief Security Officer | | | |
| IT Manager (builder) | | | |
