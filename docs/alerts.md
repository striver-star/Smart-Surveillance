# Alerts and incidents (Phase 3, part A)

**Status 2026-11-15:** built and tested end to end in the sandbox (rules, live feed, banners and
sound, acknowledge, assign, comment, close, reopen, escalation, evidence export with checksums).
22 API tests pass. Part B (NVR and camera events, device health, clips, offline queueing) is next.

## How an event becomes an alert

Every event the platform stores (from the AI workers now; from cameras and NVRs in part B) is
checked against the **alert rules**, in order; the first rule that matches decides:

| Setting | Meaning |
| --- | --- |
| Lowest severity | events below this don't match (info, warning, critical) |
| Cameras, zones, event types, objects | `*` wildcards, for example `nvr4-*`, `*fence*`; empty = all |
| Armed | local time windows, for example `18:00-06:00` (overnight works); empty = always |
| Raise to | turn a match into a warning or critical alert (for example any person at the fence at night) |
| Channels | screen, sound, push (ntfy), WhatsApp (e-mail fallback) |
| Escalate after (min) | if nobody acknowledges in time, send to everyone subscribed to `escalation` (up to 3 times) |
| Cooldown (s) | repeat events at the same camera and zone are added to the open alert instead of raising new ones |

Defaults: **Critical events** (screen, sound, push, WhatsApp to `critical` subscribers; escalate
after 10 minutes) and **Warnings** (screen and sound). Edit them in the console under
**Settings → Alert rules** (administrators and the CSO).

## In the console

- A banner pops up on every page for each new alert, with a sound (critical: three beeps,
  warning: one). The speaker button in the top bar turns the sound on or off for that browser.
  Critical banners stay until opened or dismissed.
- **Alerts** page: live list (needs action, open, acknowledged, closed, all) with a red count in
  the menu. Open an alert to see its snapshot, details and timeline, and to **acknowledge**,
  **add a note**, **assign** (operators can take an alert themselves; the CSO and administrators can
  assign anyone), **close** with a reason (real incident, false alarm, test, duplicate, other) or
  **reopen**.
- **Export evidence** (administrators and the CSO): a zip with the snapshot, the event, the alert
  and its timeline, and `manifest.json` with the SHA-256 of every file. The zip's own SHA-256 is
  recorded in the alert's timeline and the audit log, so a copy can be checked later.

## Recipients

Add `escalation` to the subscriptions of whoever should receive escalations in
`config/recipients.json` (for example the CSO and the GM). `critical` subscribers receive the
first WhatsApp message with the snapshot.

## Phones

The console's live alerts work in a phone browser while the page is open. Alerts while the
browser is closed come by WhatsApp and the ntfy push app.
