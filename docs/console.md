# Web console and sign-in (preview of the finished product)

**Status 2026-11-15:** sign-in, users, roles, two-factor codes, audit log and branding are real;
the console's Overview, Live view, Events, Devices, Video walls and WhatsApp pages show real data.
Site map and Reports are previews with sample data, marked "Preview", until Phases 5 and 6.
Tested end to end in the sandbox (sign-in, wrong password, lockout, first sign-in password change,
two-factor setup and sign-in, code reuse, roles, logout, 9 live tiles playing) and 14 API tests pass.

## Open it

`https://<server>/` (for example `https://10.6.83.82/`). The old wall test page stays at `/wall-test/`.

## First-time setup on the server

```bash
cd ~/Smart-Surveillance && git pull
```
```bash
docker compose --profile ai --profile notify up -d --build api proxy gateway
```
Create the first administrator (asks for a password of 12+ characters):
```bash
docker compose exec api python -m app.auth create-admin it.manager
```
Sign in, then add the other users under **Users**. Each new user gets a temporary password,
shown once, to hand over in person; they choose their own at first sign-in. Turn on two-factor
for every administrator and CSO under **Settings** (any authenticator app works).

The Devices page reads the latest probe files from `tools/probe/probe-output/` (`inventory.json`
from `hss-probe`, `cameras/cameras.json` from `hss-cameras`). Rerun those to refresh it. If the
probe output lives elsewhere, set `HSS_PROBE_OUTPUT=/path/to/probe-output` in `.env`.

## Roles

| Role | Sees and does |
| --- | --- |
| Administrator | Everything, including users, audit log, branding and test messages |
| Chief Security Officer | Overview, live view, events, site map, devices, video walls, reports, WhatsApp status |
| Operator | Overview, live view, events, site map, devices |
| Management | Overview, devices and reports |

## Security

- Passwords: 12+ characters, stored with scrypt and a random salt. 5 wrong attempts lock the account for 15 minutes.
- Sessions: random token in an HttpOnly, Secure, SameSite=Strict cookie; only its hash is stored. Sign-out after 2 hours idle and 12 hours at most (`HSS_SESSION_IDLE_MIN`, `HSS_SESSION_MAX_H`).
- Two-factor: standard 6-digit codes (RFC 6238); each code works once.
- Every sign-in, failed sign-in, sign-out and user or branding change is in the audit log.
- Event lists, snapshots, wall status and WhatsApp status now need a signed-in user (scripts can still use `HSS_ADMIN_TOKEN`).
- The console page is served with a strict Content Security Policy and can't be framed.

**Known gaps, to close in Phase 2:** the video streams (`/stream/...`) don't yet check the
sign-in, because the wall PCs read them without a user session; and the gateway still accepts
stream publishing from the local network. Both are planned with the wall token in Phase 2.
