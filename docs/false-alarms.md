# False alarm dashboard

**False alarms** (administrators, CSO, management) shows, for the last 7, 30 or 90 days, how noisy the
alert rules and cameras are and what to try. It learns from how operators close alerts: **false alarm**
against **real incident** (test and duplicate are left out of the rate). Device alerts (camera offline,
drive faults, patrols) are not counted: they are not detection noise.

- **Headline figures:** alerts, false alarm rate, median time to acknowledge, alerts not yet reviewed.
- **By hour of day:** false alarms, real incidents and the rest, stacked, so dusk and dawn noise or
  busy daytime hours stand out.
- **Rules and Cameras:** alerts, false, real and the false rate. A rule or camera with a rate of 60% or
  more and at least 5 reviewed alerts is marked red, with what to try:

| Pattern in its false alarms | Suggestion |
|---|---|
| No person or vehicle on most of them | Turn on the camera's human and vehicle filter, or set the rule's Objects |
| Mostly plain motion | Use line crossing or intrusion with a target filter instead |
| Bunched at dusk and dawn | Light change and infrared switch-over: sensitivity, IR switch time, white light |
| Mostly daytime on a rule armed all day | Arm the rule at night only |
| In bursts minutes apart | Raise the rule's cool-down; look for something moving in view |
| Nearly all in one detection area | Redraw that area to leave out trees, roads, reflections |

- **Check recent false alarms:** the last three, each opening Playback 10 seconds before it, to see what
  set it off.

The figures are only as good as the closing reasons: operators should always close alerts with the right
reason. Review the page weekly in the first month, then monthly.
