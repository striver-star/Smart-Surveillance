# CSO guide

For the Chief Security Officer: rules, escalation, evidence, reports and the legal duties.

## Alert rules (Settings › Alert rules)

Rules are checked top to bottom; the first that matches decides. Each rule sets:
- which events (severity, cameras, zones, event types, person or vehicle);
- when it's armed (for example 18:00 to 06:00 at the fence);
- channels (screen, sound, push, WhatsApp) and escalation (minutes before it goes up a level);
- a cool-down, so repeats at one place fold into the open alert;
- PTZ cameras to turn to a preset when it fires (for example `nvr4-ch05:3`: the yard PTZ looks at the fence).

Save PTZ presets from Live view (select the camera, aim it, **Save view**). You and administrators can take over a PTZ camera that someone else is steering.

Start strict at night and at the perimeter, lighter in busy daytime areas. Review the weekly report's **repeat alerts**, and the alerts closed as false alarms, and adjust.

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

## Video wall

**Video walls**: one screen per NVR, or a rotation through all cameras. Cameras with open alerts stay on every page, outlined. Assign screens to each TV.

## Site map and guards

**Site map**: draw restricted zones, the perimeter and patrol checkpoints; link the cameras covering each. Use **Walk-through** to test a zone without a phone.

## Each month

- [ ] Security page: no red items
- [ ] Repeat alerts and false alarms reviewed; rules adjusted
- [ ] Evidence on legal hold still needed
- [ ] Watchlist reviewed (if face and plate are on)
- [ ] Accounts of people who left are disabled
