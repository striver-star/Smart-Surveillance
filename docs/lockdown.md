# Master lockdown mode

Release 2.0, second batch. One button for a serious threat: intruders on site, an armed robbery, unrest at
the gate.

## What it does

| While the site is in lockdown | |
|---|---|
| Alert rules | Every **enabled** rule is armed, whatever its armed times. Disabled rules stay off. |
| New alerts | Raised to **critical** (except device faults), so they sound, record a clip, and escalate like any critical alert. The alert history says "Raised to critical: the site is in lockdown". |
| Sirens and lights | The outputs chosen for lockdown switch on and **stay on** until it ends. |
| Screens | A red LOCKDOWN banner on every console page, on every wall screen and in the phone app. |
| Messages | Everyone subscribed to `lockdown` in `config/recipients.json` gets WhatsApp (e-mail if that fails) and push, at the start and at the end. |
| Records | Logbook entries (incident) and audit log entries at the start and the end. |

## Who can do what

- **Start**: operators, the CSO and administrators: the red **Lockdown** button at the top of every console page.
  A reason is required; it goes out with the messages.
- **End**: the CSO and administrators: **End lockdown** on the banner, with an optional note ("police on site, all clear").
- **Set up** (CSO, administrators): Settings › **Lockdown**: tick the outputs to switch on (floodlights, sirens).

## Setting up

1. Add `"lockdown"` to the subscriptions of everyone who must be told, at least the CSO, management and the
   IT Manager, in `config/recipients.json` (see `config/recipients.example.json`). Phones subscribed to the
   HSS push topic on ntfy get it too, at high priority.
2. Settings › Lockdown: choose the outputs.
3. Try it once with everyone in the control room, at a quiet time, and end it straight away. The messages
   say what they are; tell recipients beforehand that it's a test.

## Notes

- An alert rule that switches one of the lockdown outputs with a time limit during the lockdown can switch it
  off when its time runs out. Keep lockdown floodlights out of timed alert rules, or give them no time limit.
- The lockdown survives a server restart (it's stored in the database); outputs aren't switched on again by
  themselves after a restart. Check them from Live view › Sirens and lights.
- API: `GET /api/lockdown`, `POST /api/lockdown` `{reason}`, `POST /api/lockdown/end` `{note}`,
  `GET/PUT /api/lockdown/config` `{outputs: [names]}`.
