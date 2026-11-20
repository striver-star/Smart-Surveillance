# Compliance and privacy report

Release 2.0, second batch. A monthly report for the CSO, the Data Protection Officer and management that shows
whether the system is run as the DPIA and the face and plate legal review say. PDF and Word, in the site's branding.

## What it contains

It opens with a **checklist**: each item is **Action** (fix now), **Attention** (due soon or not recorded) or **OK**.

| Area | Checks |
|---|---|
| Face and plate | Legal review in force; Action if recognition was used without it; Attention 60 days before it expires |
| DPIA | The DPIA review date (Settings › Compliance): Attention 60 days before, Action when past |
| Signs | Recognition signs checked in the last 90 days (only while face or plate is unlocked or used) |
| Retention | The nightly clean-up ran; no events or guard positions held beyond their limit; evidence past its keep-until date without a legal hold |
| Recording | NVR recording days per camera against `HSS_RECORDING_DAYS`: too short, or more than twice as long as the DPIA allows |
| Evidence | Failed integrity checks |
| Accounts | Administrators and the CSO without two-factor; accounts unused for 90 days; 20 or more failed sign-ins |

Then the figures behind it:
- face and plate recognition use (events by camera and type);
- retention limits and the oldest data held;
- **who watched video** (from the viewing log: live and recordings per person, cameras, out-of-hours viewing 22:00 to 06:00);
- the evidence vault (sealed, downloaded, exported, legal holds, failed checks);
- data that left the system (evidence downloads and exports, viewing log exports, reports downloaded and sent);
- accounts by role, sign-ins, and changes to users.

The report contains user names and is marked confidential.

## Setting up

1. Settings › **Compliance** (CSO, administrators): enter the DPIA review date, the date the recognition signs
   were last checked, and the DPO. Update the signs date after each walk round.
2. Tick **compliance** for the CSO, the DPO and management in WhatsApp & alerts › Recipients.
3. With the report schedule on (`HSS_REPORT_TIME`), it is generated on the 1st for the previous month and sent
   to "compliance" subscribers. `HSS_REPORT_KINDS` includes `compliance` by default.
4. On demand: Reports › New report › **Compliance and privacy**, any day in the month.
