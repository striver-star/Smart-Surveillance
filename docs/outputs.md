# Sirens, lights and relays

Alert rules can switch on sirens, strobes, floodlights and other relays when they raise an alert. Each
output turns itself off after its set time, and **acknowledging the alert silences it**. Operators can
switch outputs on and off by hand (Devices, or the panel in Live view). Everything is in the alert's
timeline and the audit log.

## Three ways to drive a siren or light

| Way | Use for | Set up |
|---|---|---|
| NVR alarm output | A siren, strobe or floodlight wired to the NVR's alarm output (through a relay for mains loads) | Devices › Sirens, lights and relays › Add output › NVR alarm output |
| Network device | A siren or light far from the NVR, on an IP relay box or controller switched by a web address | Add output › Network device: the "on" address, and "off" if it has one |
| The camera's own strobe and speaker | AcuSense cameras with a strobe and speaker (models ending -SU) | On the camera or NVR: the event's linkage › Flashing light and Audible warning |

The third way reacts instantly and keeps working if the HSS server is down, so use it for deterrence at
the fence; use HSS outputs for sirens and lights the cameras can't drive, and for rules that need HSS's
schedules or several cameras.

## Set up an NVR alarm output

1. Wire the siren or light (through a relay rated for its load) to an alarm output on the NVR's back panel.
2. Give the HSS user on the NVR the right to trigger alarm outputs (**Remote Notify Surveillance Center /
   Trigger Alarm Output**).
3. Devices › **Add output** › NVR alarm output › choose the NVR, **Read the NVR's outputs**, pick the number.
4. Set **Turns off after** (for example 60 seconds; 0 = stays on until switched off or acknowledged).
5. **Test** switches it on for 3 seconds.

## Use it in a rule

Settings › Alert rules › **Switch on**: the outputs' names, separated by commas (e.g. `Gate siren, Fence
floodlight`). Combine with the armed hours (night only) and **Turn PTZ cameras to** for the same rule.

## Safety

- A siren with "stays on" keeps sounding until someone acknowledges the alert or switches it off: prefer
  a set time for sirens.
- If the server restarts while an output is on, it is not switched off automatically: check Devices after
  a restart, and prefer devices that switch themselves off after a time.
- Agree siren use with the CSO and neighbours; test at agreed times.
