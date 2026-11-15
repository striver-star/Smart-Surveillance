# Phone app (guards and supervisors)

Release 2.0, first batch. A web app at `https://<server>/m/` that installs on a phone's home screen. Nothing
comes from an app store, and nothing stays on the phone except the sign-in.

## Who uses it

| Role | What they get in the app |
|---|---|
| **Guard** (new role) | Home (check-in, SOS, recent check-ins), Log (logbook entries), Me (password, sign out). A guard can't open the console: signing in there sends them to the phone app. |
| Operator, CSO, administrator | The same, plus **Alerts**: the open alerts with snapshots; acknowledge, add a note, close (real incident, false alarm, test, duplicate) and open live view. |

Management accounts don't use the phone app.

## Check-in

The guard presses **Check in here** at a patrol checkpoint. The phone's GPS position goes to HSS, which runs it through
the same zone tests as Traccar positions: inside a checkpoint zone it counts as a patrol visit (and resets that
checkpoint's missed-patrol timer). Outside, the guard is told the nearest checkpoint and how far it is.

- A position less accurate than **50 m** is refused ("wait a few seconds in the open and try again").
- Each person has their own tracked unit, named `app-<username>`, made on first use. It shows on the Site map with the other guards.
- The phone app needs the **gps** licence feature, as Traccar does.

## SOS

Hold the red **SOS** button for 2 seconds (a tap does nothing, so it isn't sent from a pocket). HSS raises a critical
**SOS** event at the guard's position; the alert rules decide who is told (the default "Critical events" rule
catches it). The alert's timeline says who sent it and from where, for example
`SOS from Ade (Patrol 2) at 6.501912, 3.350423 (±6 m)`. If the phone has no GPS fix the SOS is still sent, marked "no location".

Every SOS is written to the audit log.

## Continuous tracking

A web page only has GPS while it is open on screen. For guards who must be tracked all shift, keep using the
**Traccar Client** app (see [gps.md](gps.md)); the phone app is for check-ins, SOS, the logbook and, for supervisors, alerts.

## Setting up a guard

1. **Users › Add user**, role **Guard (phone app only)**. Give them the one-time password in person; they set their own on first sign-in.
2. On the phone, open `https://<server>/m/` on the site Wi-Fi (or VPN).
   - The server uses the HSS internal certificate: install the HSS root certificate on the phone first (steps in [console.md](console.md), "phones"), or the browser will warn and won't install the app.
3. Install to the home screen:
   - **iPhone (Safari)**: Share › **Add to Home Screen**.
   - **Android (Chrome)**: menu › **Install app** (or **Add to Home screen**).
4. Open it from the icon, sign in, and allow location when asked.

## Server notes

- The proxy serves `/m/` with `Permissions-Policy: geolocation=(self)`, so location works on the app pages only.
  After pulling this release recreate the proxy: `docker compose up -d --force-recreate proxy`.
- Migration `016_guards.sql` adds the guard role and links tracked units to user names.
- API: `GET /api/mobile/me`, `POST /api/mobile/checkin`, `POST /api/mobile/sos`.
