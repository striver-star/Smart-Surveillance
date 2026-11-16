# Viewing log (who watched which camera)

Release 2.0, first batch. Every live view and every recording played is recorded: who, which camera,
when, live or recorded (and which recorded time), and from which address. **Viewing log** in the console
(CSO and administrators) searches it by camera, person, live or recorded, and dates, and exports CSV.
On an alert, **Who watched** opens the log for that camera from an hour before the alert.

## Video now needs a sign-in

Before this release the stream gateway answered anyone on the network who knew a camera's name. Now every
request for video (`/stream/...`) is checked by the API first (Caddy `forward_auth` to `/live/authorize`):

| Who asks | Allowed |
|---|---|
| Signed-in administrator, CSO or operator | Any live camera. A recording only if they started that playback. |
| Wall screen (sends its screen key) | Only the cameras on that screen. |
| Guards, management, anyone not signed in | Nothing (401 or 403). |
| The gateway's own test pages (`/stream/<camera>/`) | Refused. |

This is also what makes the log reliable: video can't be opened without passing the check, and the check is
where viewing is written down.

## What is recorded

- **Live**: one line when a person opens a camera. If they open it again, or the tile reconnects, within
  10 minutes, the line is extended ("1:44 PM – 2:10 PM") instead of adding a new one. The end time is the
  last time the browser connected to that camera, so a person who watched without interruption for an hour
  shows the time they opened it; treat the range as "at least".
- **Recordings**: one line per playback started, with the time in the recording that was played.
- **Wall screens** are shared displays and aren't logged per person.
- Exporting the CSV is itself written to the audit log.
- Kept for 365 days (`HSS_VIEW_LOG_DAYS` in `.env` to change), removed by the nightly retention clean-up.

## Effects to know about

- The **task 19 wall capacity test page** (`/wall-test/`) now needs the browser to be signed in to the console
  as an administrator, CSO or operator first (same browser, another tab).
- While the **API is down** (for example during an upgrade), cameras already playing keep playing, but a tile
  that drops, or a page opened during the outage, can't start video until the API answers again (usually under
  a minute). See docs/wall-screens.md.
- The gateway's RTSP port (8554) isn't published outside Docker in `compose.yaml`; only the AI worker and other containers reach it. Keep it that way: Docker-published ports bypass the `ufw` firewall.

## Server notes

Migration `017_viewing.sql`; new Caddyfile block for `/stream/*`, so recreate the proxy after pulling:
`docker compose up -d --force-recreate proxy`.
