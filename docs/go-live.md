# Pilot go-live plan

## Ready to go live when

- [ ] Getting started complete in the console (all required steps ticked)
- [ ] Acceptance tests: every Must passed (docs/acceptance-test.md)
- [ ] Server wired at 1 Gbps; NVR4 drive replaced; NTP on all devices
- [ ] Training done and competency checks signed (docs/training.md)
- [ ] Backup passphrase sealed in the safe; second backup copy off the server
- [ ] Support contacts and escalation list printed in the control room

## Go-live day

| Time | Step | Who |
|---|---|---|
| Day before | Final backup and restore test; freeze changes | IT Manager |
| 08:00 | Operators start on HSS; old monitoring stays on as a fallback | CSO |
| 08:00 to 18:00 | IT Manager on site; every problem logged with time and fix | IT Manager |
| 18:00 | Night shift briefed; night alert rules checked armed | CSO |
| Next morning | Review the night: alerts, escalations, WhatsApp delivery | CSO, IT Manager |

## Hypercare (first 2 weeks)

- Daily 15-minute review: alerts handled in time, false alarms, device faults, Security page.
- Tune rules for repeat alerts after day 3 and day 7.
- End of week 2: management review with the weekly report; decide whether the old monitoring can stop.

## Rollback

If HSS can't be used (server down and not recoverable within 2 hours): operators return to the NVRs'
own monitors and the old monitoring; the NVRs keep recording either way, since HSS never stops them.
Restore the server from the latest backup (docs/backup.md) and return to HSS when it passes tests 1, 3,
5 and 10 again.
