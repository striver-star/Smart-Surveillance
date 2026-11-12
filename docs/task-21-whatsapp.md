# Task 21: WhatsApp delivery (provider A) and the one-week trial

**Goal:** reports and alerts reach Management, the CSO and the IT Manager on WhatsApp from the
dedicated site number, fall back to e-mail automatically when WhatsApp is unavailable, and alerts
also reach the self-hosted push app. The one-week trial shows whether the free gateway is stable
enough to be the default.

## What was built

| Part | Where |
|---|---|
| WhatsApp gateway (whatsapp-web.js, Apache 2.0, headless Chromium) | `services/whatsapp-gateway/` (compose service `whatsapp`, profile `notify`) |
| Push server (ntfy, Apache 2.0) | compose service `ntfy`, profile `notify`, port 8090 |
| Notification service: recipients, WhatsApp first, e-mail fallback, push, delivery log, gateway watch, daily test | `services/api/app/notify.py`, migration `003_notifications.sql` |
| Recipients and what they receive | `config/recipients.json` (copy from `config/recipients.example.json`; not in git) |

Baileys, the other common WhatsApp library, was not used: it depends on `libsignal`, which is
GPL-3.0. Every package in the gateway is MIT, ISC, Apache 2.0, BSD or similar, except
`node-webpmux` (LGPL-3.0, used unmodified as a library, which Section 19 allows).

Topics a recipient can subscribe to: `daily`, `weekly`, `monthly`, `critical`, `device`, `system`
(gateway problems), `test`. Push notifications go out for `critical`, `device` and `system`.

## Result in the build environment

WhatsApp's servers cannot be reached from the build environment, so the gateway stayed unlinked
(`error`). That exercised the fallback: a test report went to both recipients by e-mail with the
PDF attached, marked as fallback; a critical alert went only to the recipient subscribed to it;
`/api/notify/status` showed the gateway state and the masked recipients. 6 automated tests pass
for the notification logic and 2 for the gateway. **2026-11-12: the dedicated number is linked on site and the first test report was sent and delivered** (after two gateway fixes: stale browser lock after a rebuild, and the library's page cache that blocked `ready`). E-mail fallback is on hold; WhatsApp and push only for the trial.

## Set up on the server

1. In `.env`, set:
   - `HSS_WA_TOKEN` (`openssl rand -hex 32`)
   - `HSS_NTFY_TOPIC`, a hard-to-guess name such as `hss-alerts-` followed by random letters
   - `HSS_NOTIFY_DAILY_TEST=08:05` (the daily test time for the trial)
   - the SMTP settings for e-mail fallback (`HSS_SMTP_HOST`, `HSS_SMTP_PORT`, `HSS_SMTP_USER`,
     `HSS_SMTP_PASSWORD`, `HSS_SMTP_FROM`), for example the company mail server or a mailbox's SMTP.
     These are optional: leave them out to run on WhatsApp and push only (the trial does this
     until e-mail is set up). Without e-mail, the push app is the only warning when WhatsApp drops.
2. Create the recipients file with the real numbers (international format, `+234...`):
   ```bash
   cp config/recipients.example.json config/recipients.json && nano config/recipients.json
   ```
3. Start everything, including the gateway and push server:
   ```bash
   docker compose --profile ai --profile notify up -d --build
   ```
4. Link the dedicated phone: run `docker compose logs -f whatsapp`, wait for the QR code, then on
   the phone open WhatsApp → Linked devices → Link a device and scan it. The log then shows
   `state: ready`. The link is kept in the `wa-data` volume, so this is done once.
5. Send a test report:
   ```bash
   ADMIN=$(grep ^HSS_ADMIN_TOKEN .env | cut -d= -f2)
   curl -sk -X POST https://localhost/api/notify/test -H "Authorization: Bearer $ADMIN" | python3 -m json.tool
   ```
   Each recipient subscribed to `test` should get a WhatsApp message with a one-page PDF. When two
   recipients share a phone number, that phone gets one copy and the log shows the second as
   `skipped`. The dedicated (sending) number must not be in the recipients list.
6. Push: install the ntfy app (Android or iPhone), add server `http://SERVER_IP:8090` and subscribe
   to the topic from `HSS_NTFY_TOPIC`. Phones must be on the site network (or VPN) to receive it.

## The one-week trial

Leave it running for 7 days. Every day at `HSS_NOTIFY_DAILY_TEST` a test report is sent. The
gateway is checked every minute; if it drops, the IT Manager is told by e-mail and push, and
messages fall back to e-mail until it is linked again.

Check progress at any time:

```bash
curl -sk "https://localhost/api/notify/status?days=7" -H "Authorization: Bearer $ADMIN" | python3 -m json.tool
```

**Pass:** 7 daily tests delivered on WhatsApp (status `delivered` or `read`), no number restriction
by WhatsApp, the gateway never unlinked for more than an hour, and the fallback e-mail arrived on
every day WhatsApp failed.

Keep the volume low and the use honest, as the plan requires: one dedicated number, a few messages
a day, recipients who have saved the number, no marketing. The gateway is unofficial; if WhatsApp
restricts the number, the official Cloud API (provider B) remains the paid alternative.

## Troubleshooting: "authenticated" but never "ready"

whatsapp-web.js sometimes links (log shows `authenticated`) but never reaches `state: ready`, usually
when WhatsApp changes its web app. The gateway now handles this itself:

1. logs the WhatsApp Web page's errors as `page error: ...` (the real cause);
2. after 60 s re-runs the library's injection; after 180 s restarts the session;
3. after 3 failed restarts stops in `state: stuck` (so it doesn't hammer WhatsApp), and the platform
   alerts the IT Manager by push.

If it ends in `stuck`, re-link from scratch (upstream reports say a fresh link often works when a
restored session doesn't):

```bash
docker compose --profile notify stop whatsapp
docker compose --profile notify run --rm --no-deps --entrypoint sh whatsapp -c 'rm -rf /data/session /data/.wwebjs_cache'
docker compose --profile notify up -d whatsapp && docker compose logs -f whatsapp
```

On the dedicated phone, remove the old entry under WhatsApp → Linked devices, then scan the new QR code.
If it still gets stuck, send the `page error` lines: the fix is then a whatsapp-web.js update.
