# CSO guide

For the Chief Security Officer: rules, escalation, evidence, reports and the legal duties.

## Alert rules (Settings › Alert rules)

Rules are checked top to bottom; the first that matches decides. Each rule sets:
- which events (severity, cameras, zones, event types, person or vehicle);
- when it's armed (for example 18:00 to 06:00 at the fence);
- channels (screen, sound, push, WhatsApp) and escalation (minutes before it goes up a level);
- a cool-down, so repeats at one place fold into the open alert;
- sirens, strobes and floodlights to switch on (**Switch on**, by the output's name; acknowledging silences them);
- PTZ cameras to turn to a preset when it fires (for example `nvr4-ch05:3`: the yard PTZ looks at the fence).

Save PTZ presets from Live view (select the camera, aim it, **Save view**). You and administrators can take over a PTZ camera that someone else is steering.

Start strict at night and at the perimeter, lighter in busy daytime areas. Review the **False alarms** page weekly at first: it marks the noisy rules and cameras and says what to try, with links to play the recent false alarms.

## Evidence (Evidence vault)

- Seal evidence from an alert, or close it as a real incident to seal it automatically.
- Download checks the package's fingerprint first. Give police the file and its SHA-256 (shown on the page).
- Put a **legal hold** on anything a case depends on; otherwise packages are deleted after a year.
- The custody log shows every access. A red warning means someone tampered with the log: tell the administrator and change nothing on the server.

## Reports

Daily, weekly and monthly reports go to WhatsApp subscribers automatically. **Reports** lets you make one for any period or camera and download it as PDF or Word.

## Watchlists and face and plate (only if unlocked)

- Only you or a named deputy add entries, with a written reason, the source document and an end date (12 months at most). Review the list every 3 months.
- Never list someone on suspicion alone, or for ethnicity, religion, politics, union membership or health.
- **Withdraw and lock** (Face & plate page) stops recognition at once if there's a complaint or doubt.

**Live recognition** (stage 4): Face & plate › Face watchlist and Plate watchlist (every entry needs a reason, an authority reference and an expiry date), Cameras and thresholds, and Accuracy (operators' verdicts, a suggested threshold). Details: docs/recognition.md.

## Planning cameras

**Camera planner** shows, for a camera, lens and distance, the pixels per metre on the target, whether faces and plates will be big enough, and how far each level (detect, observe, recognise, identify) reaches. Use it before buying or moving a camera; confirm with the suitability tests.

## Video wall

**Video walls**: one screen per NVR, or a rotation through all cameras. Cameras with open alerts stay on every page, outlined. Assign screens to each TV.

**Status board**: a screen of type *Control-room status board* shows open alerts, the site map, device health, guards and the shift on one TV; ask the administrator to add one and put it on the TV the operators face.

## Site map and guards

**Site map**: draw restricted zones, the perimeter and patrol checkpoints; link the cameras covering each. Use **Walk-through** to test a zone without a phone.

**Phone app** (`https://<server>/m/`): guards check in at checkpoints with the phone's GPS and hold **SOS** for 2 seconds to raise a critical alert with their position. Supervisors also see open alerts there and can acknowledge and close them. Keep the Traccar Client app for guards who must be tracked all shift: the phone app only knows where a guard is when they check in.

## Heat map

**Incident heat map** shows where (on the site plan) and when (day and hour) alerts happen. Use *Real incidents* to plan patrol routes, patrol times and lighting; click a camera to see its busiest hours. Place every camera on the site plan so the map is complete.

## Unusual activity

**Unusual activity** learns each camera's usual events hour by hour and raises a warning when a normally quiet camera suddenly has activity, or a busy camera goes silent (blocked or turned). Cameras need 14 days of history. Set the sensitivity there; see docs/anomaly-detection.md.

## Lockdown

Operators can start a lockdown with the red **Lockdown** button; you or an administrator end it with **End lockdown** on the red banner. In Settings › **Lockdown** choose the floodlights and sirens to switch on; add `lockdown` to the subscriptions of everyone who must be told in config/recipients.json (ask IT). Rehearse it once with the control room. Details: docs/lockdown.md.

## Doors

In **Doors** › Settings choose, for each door, its camera, whether operators may open it from the console, and whether it stays locked in a lockdown. Only you and administrators can keep a door locked or open. Who came through keeps 90 days of access events with names. Details: docs/access-control.md.

## Viewing log

**Viewing log** shows who watched which camera, live or recorded, when and from where; search by camera, person or dates and export CSV. On an alert, **Who watched** opens it for that camera. Video can't be opened without signing in, so the log is complete for the console and the phone app (wall screens aren't logged per person). Check it after any incident where footage may have leaked.

## Compliance report

On the 1st the **compliance and privacy report** arrives (Reports › Compliance): a checklist of what needs action (legal review and DPIA dates, signs, retention, evidence, accounts) and who watched video. Keep Settings › **Compliance** up to date: the DPIA review date and the date you last checked the recognition signs. Deal with every *Action* before the next one.

## Each month

- [ ] Security page: no red items
- [ ] Repeat alerts and false alarms reviewed; rules adjusted
- [ ] Evidence on legal hold still needed
- [ ] Watchlist reviewed (if face and plate are on)
- [ ] Accounts of people who left are disabled
