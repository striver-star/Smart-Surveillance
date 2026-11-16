# Unusual activity (anomaly detection)

Release 2.0, third batch. The platform learns each camera's usual pattern of events and flags what doesn't fit,
without anyone setting armed times or thresholds per camera.

## What it finds

| Finding | When | Typical cause |
|---|---|---|
| **Unusual activity** | At least 3 events in the last hour, and that many would almost never happen by chance at this camera at this hour | Someone at a fence or store that is normally silent at night; a gate used at an odd time |
| **Unusually quiet** | No events for 3 hours at a camera that usually has 15 or more in that time | Camera blocked, turned, or its events switched off |

A busy camera being a bit busier is not flagged: the test is against that camera's own usual count for that hour
(a Poisson test), separately for weekdays and weekends.

## How it works

- **Learning**: the usual number of events for every hour, weekdays and weekends apart, from the last 6 weeks.
  Days without events count as zero. A camera is judged once it has 14 days of history ("learning 5/14 days" until then).
- **Checking**: every 10 minutes, the last hour (and the last 3 hours for quiet cameras).
- **Findings** are stored as events (`unusual_activity`, `unusually_quiet`, warning) and go through the alert rules like
  any other event: the default *Warnings* rule raises an alert, with the explanation in its history. One finding per
  camera and kind every 3 hours.
- Counted: the cameras' own detections (line crossing, intrusion, motion, server AI, and so on). Not counted: device
  faults, guard positions and patrols, SOS, face and plate matches.

## The page: Unusual activity

- **Findings** of the last 14 days, with a picture from that hour and a link to the alert.
- **Each camera's day**: today's events per hour (bars, amber where far above usual) against the usual day (dashed),
  cameras with a finding in the last day first. Hover for the numbers.
- **Settings** (CSO, administrators): on or off; sensitivity Low (only the most unusual), Normal, High (more findings,
  more false ones); and whether to flag quiet cameras.

Expect a few findings to be explained by known events (a delivery at night, a holiday). Close those alerts as
"Real incident" or "False alarm" so the False alarms page shows how useful the findings are; lower the sensitivity
if most are false.
