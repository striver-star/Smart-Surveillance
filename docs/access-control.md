# Access control and video intercom

Release 2.0. HSS works with Hikvision access control and video intercom devices over ISAPI, the same way it works
with Hikvision NVRs: access controllers and face or card terminals (DS-K series) and video intercom door stations
(DS-KV, DS-KD). It also works with ZKTeco access panels (InBio, C3) and standalone face, fingerprint and card
terminals (SpeedFace, ProFace, F-series) over ZKTeco's push protocol: see "ZKTeco" below. No device is installed yet;
this was built and tested against `tools/simulators/hik-access-sim.py` and `tools/simulators/zk-push-sim.py`, so the
first real devices must be checked against this guide (see "First real device" and "ZKTeco: first real device").

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

## ZKTeco

ZKTeco devices aren't polled: they call in to HSS (ZKTeco's push protocol, also called PUSH SDK, ADMS or cloud
server), every 2 seconds, over plain HTTP on **port 8088**. Doors, Who came through, alerts, console commands,
lockdown, camera permissions and the 90-day retention are the same as for Hikvision.

| | Hikvision | ZKTeco |
|---|---|---|
| How HSS reaches it | HSS asks the device (ISAPI, user and password) | The device calls HSS (port 8088); HSS only listens to devices an administrator added, from the address they were added from |
| Access panels (InBio, C3) | | Events, door contacts and lock states, names from the panel's user list |
| Standalone terminals | Full events | Successful verifications only (the terminal doesn't report refusals in its push log) and no door states |
| Duress code | | **Duress code used**: critical alert |
| Keep locked | Yes: cards are refused until set back to normal | **No**: "Lock now" locks the door, but valid cards still open it, also during a lockdown. Use the panel's own settings (or a Hikvision controller) where a door must refuse cards |
| Video intercom | DS-KV / DS-KD door stations | Not supported |

### Setting up a ZKTeco device

1. Give it a fixed address on the security VLAN, and set its **time and time zone** to the site's (HSS_TZ). If its
   clock is wrong HSS corrects event times from its status reports and shows "the device's clock is N min slow".
2. On the device: Comm. › Cloud Server Setting (or ADMS): server address = the HSS server's IP, port **8088**,
   domain name off, proxy off. On InBio / C3 panels this needs the push firmware (ask the supplier for "PUSH" or
   "ADMS" firmware; panels set up for ZKAccess or ZKBioSecurity must be moved to HSS).
3. Within a minute it appears in Doors › **ZKTeco devices calling in** with its serial number and address.
   Check the serial on the device's label, then **Add**: a name and its number of doors (1, 2 or 4; 1 for a
   terminal). Nothing it sent before this was kept.
4. Door settings and the test are as for Hikvision (step 3 and 4 above), plus the duress code if it's used.
5. Firewall: port 8088 open from the access-control devices only, never from the internet. The protocol is plain
   HTTP and the device is identified by its serial number and address: keep the devices on the security VLAN.

If a device's address changes (a DHCP lease, a move), HSS ignores it and lists it again under ZKTeco devices calling
in with **Accept new address**: check it's the same device before accepting.

### ZKTeco: first real device

Compare Who came through with the device's own event log, and check:

| ZKTeco event | Shown as |
|---|---|
| 0–5, 14–19, 26, 32 | Access granted (card, fingerprint, face, multi-card, first card, during normal open, ...) |
| 20–25, 27, 29–31, 33–36 | Access refused (interval, time zone, anti-passback, interlock, unregistered, expired, wrong PIN, ...) |
| 8 / 205 | Door unlocked (remote open / remote normal open) |
| 9 | Door locked (remote close) |
| 28 | Door held open (open timeout) |
| 101 / 103 | Duress code used (PIN / fingerprint) |
| 102 | Door forced open |
| 200 / 201 | Door opened / closed (door contact) |
| 202 | Exit button |

Also check:

- **Door commands.** HSS sends `CONTROL DEVICE 01<door>01<seconds>00` to open a door for 5 s, `...01FF00` to keep it
  open, `04<door>000000` then `01<door>010000` for normal / lock now. Check Open unlocks for the panel's time and
  Normal ends Keep open. If the firmware wants another format, only `control_commands()` in
  `services/api/app/zkteco.py` changes.
- **Door states.** HSS reads `rtstate` as one byte per door in `sensor` (1 closed, 2 open) and one bit per door in
  `relay` (1 unlocked). Check the door cards follow the doors.
- **Names.** When added (and when it comes back online) HSS asks for the user list; check events show names.
- **Times.** Event times match the camera recordings.

### Without devices

```bash
python3 tools/simulators/zk-push-sim.py http://SERVER:8088 --serial ZKSIM0001 --doors 2 --port 8603
```
```bash
python3 tools/simulators/zk-push-sim.py http://SERVER:8088 --serial ZKTERM0001 --terminal --port 8604
```

Add them in Doors › ZKTeco devices calling in. Events: `http://127.0.0.1:8603/test/swipe?door=1&pin=1001&ok=1`
(`ok=0` refused), `/test/forced?door=1`, `/test/held?door=1`, `/test/duress?door=1&pin=1001`,
`/test/contact?door=1&open=1`; `/test/commands` lists the commands it carried out.
