# Access control and video intercom

Release 2.0. HSS works with Hikvision access control and video intercom devices over ISAPI, the same way it works
with Hikvision NVRs: access controllers and face or card terminals (DS-K series) and video intercom door stations
(DS-KV, DS-KD). No device is installed yet; this was built and tested against `tools/simulators/hik-access-sim.py`,
so the first real devices must be checked against this guide (see "First real device" below).

## What it does

| | |
|---|---|
| **Doors page** | Every door with its state (locked or unlocked, open or closed, normal or kept open or locked) and the camera that watches it |
| **Who came through** | Every access event: door, time, granted or refused, person and staff number, how they verified (card, face, fingerprint), card number masked to its last 4 digits. Filter by door, kind and person; **Play** opens the door camera's recording |
| **Alerts** (on the door's camera, so the picture and recording are there) | Door forced open (critical), door held open (warning), access refused 3 times in 2 minutes at one door (warning), device not answering for 2 minutes (warning) |
| **Open from the console** | Operators, CSO and administrators, only on doors set to allow it, with a reason; during a lockdown only the CSO and administrators |
| **Keep locked, keep open, back to normal** | CSO and administrators, with a reason |
| **Lockdown** | Doors marked "keep locked during a lockdown" are locked when a lockdown starts and back to normal when it ends (docs/lockdown.md) |
| **Intercom** | When a door station rings, every operator gets a pop-up with its camera, **Open door** (if allowed) and **Reject call**. Talking is on the indoor station or the Hikvision app: two-way audio in the browser isn't supported |

Every command, door setting change and rejected call is in the audit log. Access events are kept `HSS_ACCESS_DAYS`
(default 90) and contain people's names: only administrators, the CSO and operators see them, limited by camera
permissions (a door's events follow its camera).

## Setting up a device

1. On the device: give it a fixed address on the security VLAN, turn ISAPI on, and make a dedicated user for HSS
   (not admin) with rights to read events and status and to control doors.
2. Console › **Doors** › Access devices (administrators): name, kind (access controller or terminal / door station),
   address, user and password. HSS tests the login and finds the doors.
3. For each door, **Settings**: a clear name, the camera that watches it, whether operators may open it from the
   console, and whether it is kept locked during a lockdown.
4. Test: a good card or face, a refused one three times, the exit button, and (at a quiet time) holding the door open
   and opening it without a card. Check each appears in Who came through, and the alerts.

## First real device: what to check

Hikvision event codes differ a little between models and firmware. HSS reads them as below; unknown codes are kept as
"Other event" with their numbers, never dropped. On the first device, compare Who came through with the device's own
event log and note any difference:

| Hikvision code (major, minor) | Shown as |
|---|---|
| 5, 1 / 38 / 75 / 104 | Access granted (card / fingerprint / face / other) |
| 5, 6 / 7 / 8 / 9 / 39 / 76 | Access refused |
| 5, 21 / 22 | Door unlocked / locked |
| 5, 23 | Exit button |
| 5, 25 / 26 | Door opened / closed (door contact) |
| 5, 27 | Door forced open |
| 5, 28 | Door held open |

Also check: door states (`AcsWorkStatus`) match the door, the console's Open unlocks it for the configured time, Keep
locked and Normal behave as expected, and a door station's call appears within 3 seconds.

## Without devices: the simulator

```bash
python3 tools/simulators/hik-access-sim.py controller 8601 --doors 2
```
```bash
python3 tools/simulators/hik-access-sim.py doorstation 8602
```

Add them in Doors with the server's address and those ports (any user and password). Make events from a browser on
the server: `http://127.0.0.1:8601/test/swipe?door=1&name=Ada&ok=1`, `/test/forced?door=1`, `/test/held?door=1`,
`http://127.0.0.1:8602/test/ring`. Useful for operator training.
