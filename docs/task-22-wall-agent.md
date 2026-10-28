# Task 22: Wall Agent and Windows installer

**Goal:** each wall PC starts its screens by itself after power-on, shows the pages the platform
assigns to each TV, recovers from crashes and freezes without anyone touching it, reports its
health, and updates itself. Installed with one installer, silently if needed.

## Design change from the context document

The context document planned the agent as a Windows service wrapped with WinSW. A Windows
service runs in a hidden session (Session 0) and **cannot show windows on the TVs**. The agent
therefore runs in the signed-in user's session instead, started by a **scheduled task** at
sign-in. The task checks every minute and starts the agent again if it is not running, so it
does the job of the service. WinSW is no longer needed. This is recorded as a Proposed decision
in the context document for the builder to approve.

## What was built

| Part | Where |
|---|---|
| Wall Agent (Go, one .exe, no runtime needed) | `services/wall-agent/` |
| Windows installer (NSIS) and scheduled task | `services/wall-agent/installer/windows/` |
| Linux user service | `services/wall-agent/packaging/linux/hss-wall-agent.service` |
| Build script (agent for Windows and Linux, installer, update manifest) | `services/wall-agent/build.sh` |
| Platform side: heartbeats, layouts, wall PC list | `services/api/app/wall.py`, migration `002_wall.sql` |
| Downloads and self-update files | served at `https://SERVER/wall-agent/` from `dist/wall-agent/` |

What the agent does:

1. Finds the monitors and numbers them left to right (monitor 0 is the leftmost TV).
2. Opens one Chromium kiosk window per monitor, each with its own profile, at that monitor's
   position, with the page the platform assigned (or the default page).
3. Restarts a browser that exits (crash) and one whose page stops reporting (freeze). Each wall
   page reports to the agent on `127.0.0.1` every 5 seconds; only the platform's own pages may.
   Restarts back off from 2 s up to 60 s if a page keeps failing.
4. Every 15 s sends health to the platform: CPU, memory, monitors, and for each screen whether it
   runs, its restarts and what the page reports (tiles playing, fps).
5. Saves the last layout, so after a reboot during a platform outage the wall still comes up.
6. Updates itself when the platform offers a new version: downloads it from the platform only,
   checks its SHA-256, swaps the file and restarts (the scheduled task brings it back).
7. Only opens pages on the platform's own address, so a wrong layout cannot show another website.

## Result in the build environment (Linux, two virtual 1920x1080 screens)

| Test | Result |
|---|---|
| Start | Two kiosk windows, one per screen, each playing its tiles; page heartbeats every 5 s |
| Platform view | `GET /api/wall/nodes` showed the PC online with CPU, memory and both screens |
| Layout change from the platform | Right TV reopened with the new page within 2 s |
| Layout pointing at another website | Refused by the API (422) |
| Browser killed | Restarted in about 4 s |
| Browser frozen (process paused) | Detected and restarted in about 25 s |
| API stopped, then the agent restarted | Both screens came up from the cached layout |
| Agent 0.0.9 with 0.1.0 offered | Downloaded, checked, replaced itself, back up as 0.1.0 in 2 s |
| Automated tests | 10 Go tests pass; Windows build passes `go vet` |

**Not yet tested on Windows.** The Windows parts (monitor detection, scheduled task, installer,
`taskkill`) compile, and the installer builds, but they need the 24-hour soak on a real wall PC.

## Build

```bash
services/wall-agent/build.sh 0.1.0
```

Produces in `dist/wall-agent/`: `hss-wall-agent-setup-0.1.0.exe` (installer),
`hss-wall-agent-0.1.0-windows-amd64.exe`, `hss-wall-agent-0.1.0-linux-amd64`, `manifest.json`
(the version wall PCs should run) and `SHA256SUMS-0.1.0`. Copying a newer build into
`dist/wall-agent/` makes every wall PC update itself within about 15 s.

## Install on a wall PC (Windows 11)

Before installing:
- Install Chromium (not Google Chrome or Microsoft Edge, Section 19). Check that it plays the
  `/wall-test/` page (H.264 support differs between Chromium builds).
- Create a local standard user for the wall, set Windows to sign it in automatically, and turn
  off sleep, screen-off and screen saver. Set display scaling to 100% and the TVs to 1920x1080.
- In the server's `.env`, set `HSS_WALL_TOKEN` and `HSS_ADMIN_TOKEN` (`openssl rand -hex 32`).

Then, as an administrator, download `https://SERVER/wall-agent/hss-wall-agent-setup-0.1.0.exe`
and either run it (it asks for the platform address, a name for this PC, and the wall token) or
install silently:

```
hss-wall-agent-setup-0.1.0.exe /S /PLATFORM=https://SERVER /NODE=wall-pc-1 /TOKEN=<wall token> /CAFILE=C:\path\hss-root-ca.crt
```

`/BROWSER="C:\...\chrome.exe"` sets the browser if it is not in a standard Chromium location.
`/CAFILE` copies the platform's root certificate so the agent trusts the server; Chromium on the
PC also needs it, so import it into Windows' "Trusted Root Certification Authorities" store
(Caddy's root certificate is in the `caddy-data` volume at `/data/caddy/pki/authorities/local/root.crt`).

Installed files: `C:\ProgramData\HSS\WallAgent\` (agent, `config.json`, uninstaller). Logs and
browser profiles: `%LOCALAPPDATA%\HSS\WallAgent\` of the wall user. Uninstall from Settings, Apps.
The installer is not code-signed, so Windows SmartScreen warns; allow it on these managed PCs.

## Assign pages to the TVs

Until Phase 1 brings sign-in, layouts are set with the admin token:

```bash
curl -k https://SERVER/api/wall/nodes -H "Authorization: Bearer $HSS_ADMIN_TOKEN"
```

```bash
curl -k -X PUT https://SERVER/api/wall/nodes/wall-pc-1/layout \
  -H "Authorization: Bearer $HSS_ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '[{"monitor":0,"path":"/wall-test/?n=32&paths=nvr1-ch01,nvr1-ch02"},{"monitor":1,"path":"/wall-test/?n=32&paths=nvr2-ch01"}]'
```

The real grid and rotation screens replace `/wall-test/` in Phase 2.

## 24-hour soak (the rest of task 22)

On one existing i5 wall PC with two TVs:

- [ ] Install silently with `/S`; after sign-in both TVs open in kiosk mode without any click
- [ ] `GET /api/wall/nodes` shows the PC online with both screens
- [ ] Change the layout of one TV from the platform; it switches within about 20 s
- [ ] End `chrome.exe` in Task Manager; the TV comes back within about 10 s
- [ ] Restart Windows; after automatic sign-in the wall comes back by itself
- [ ] Unplug the server's network cable for 5 minutes; the wall keeps showing what it can and
      recovers when the cable is back
- [ ] Unplug one camera (or stop its NVR channel); its tile freezes and reconnects when it returns
- [ ] Copy a newer build into `dist/wall-agent/`; the PC updates itself (check the version in `/api/wall/nodes`)
- [ ] Leave it for 24 hours; CPU stays under 70% and `restarts` stays low; keep the agent log
- [ ] Uninstall from Settings; the task, agent and browsers are gone

## Known limits

- Firefox cannot be placed on a chosen monitor from the command line; use Chromium on multi-TV PCs.
- With display scaling above 100%, window positions may be off; keep 100% scaling on the wall PCs.
- The wall token is shared by all wall PCs and readable by local users of the PC. Per-PC tokens
  come with Phase 1.
- The `HSS_ADMIN_TOKEN` stand-in is replaced by proper sign-in and roles in Phase 1.
