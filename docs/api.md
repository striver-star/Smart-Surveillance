# HSS open API and webhooks (version 1)

For integrators: a PSIM or control-room system, access control, a ticketing tool, a client's dashboard.
Administrators make keys and webhooks in the console: **Administration › API and webhooks**.

- Base URL: `https://<server>/api/v1` (the site's HSS server; reach it on the site network or through the VPN, and
  trust the HSS certificate authority, docs/console.md).
- Machine-readable description: `https://<server>/api/v1/openapi.json` (OpenAPI 3.1).
- Version 1 stays stable: fields may be added, never removed or renamed. Breaking changes will come as `/api/v2`.
- Face and plate recognition matches are never returned or sent.

## Authentication

```
Authorization: Bearer hss_<id>_<secret>
```

Keys are shown once when made, stored only as a hash, and can be revoked at any time. Each key has:

| Scope | Allows |
|---|---|
| `events:read` | `GET /events`, `GET /events/{id}/snapshot` |
| `alerts:read` | `GET /alerts`, `GET /alerts/{id}` |
| `alerts:write` | `POST /alerts/{id}/acknowledge`, `POST /alerts/{id}/close` |
| `cameras:read` | `GET /cameras` |

A key can be limited to some cameras (patterns such as `nvr4-*`) and given an expiry date. Each key may make 300
requests a minute (HTTP 429 with `Retry-After` beyond that). Errors are JSON: `{"detail": "..."}` with 401 (no or bad
key), 403 (missing scope or camera), 404, 409 (already acknowledged or closed), 422 (bad input).

## Endpoints

```bash
curl -H "Authorization: Bearer $HSS_KEY" "https://hss.example/api/v1/events?since=2026-11-16T00:00:00Z&limit=100"
```
```bash
curl -H "Authorization: Bearer $HSS_KEY" "https://hss.example/api/v1/alerts?status=active&severity=critical"
```
```bash
curl -X POST -H "Authorization: Bearer $HSS_KEY" -H "Content-Type: application/json" -d '{"note": "Guard sent"}' https://hss.example/api/v1/alerts/<id>/acknowledge
```
```bash
curl -X POST -H "Authorization: Bearer $HSS_KEY" -H "Content-Type: application/json" -d '{"reason": "real_incident", "note": "Police called"}' https://hss.example/api/v1/alerts/<id>/close
```

- `GET /events`: `since`, `until` (ISO 8601 with a time zone), `camera_id`, `type`, `limit` (max 500). Newest first; for
  the next page pass `before=<next_before>` from the previous answer.
- `GET /alerts`: `status` (`open`, `acknowledged`, `closed`, `active`), `severity`, `since`, `limit`.
- Close reasons: `real_incident`, `false_alarm`, `test`, `duplicate`, `other`. Actions are recorded in the alert's history
  and the audit log as `api:<key name>`.
- `GET /health` needs no key.

An alert:

```json
{"id": "7c57e5fb-…", "status": "open", "severity": "critical", "rule": "Critical events", "type": "intrusion",
 "camera_id": "nvr4-ch22", "camera": "MAIN GATE ENTERANCE", "zone": "Gate", "object": "human", "confidence": 0.91,
 "occurred_at": "2026-11-16T18:23:40+00:00", "created_at": "…", "acknowledged_by": null, "acknowledged_at": null,
 "closed_at": null, "close_reason": null, "snapshot": "/api/v1/events/<event id>/snapshot"}
```

## Webhooks

HSS POSTs JSON to the receiver's URL when something happens:

| Event | When |
|---|---|
| `alert.created` | An alert is raised (filtered by minimum severity and cameras) |
| `alert.acknowledged`, `alert.closed`, `alert.reopened` | Its status changes (once per change) |
| `lockdown.started`, `lockdown.ended` | The site goes into or out of lockdown |
| `ping` | The console's Test button |

```json
{"id": "<delivery event id>", "type": "alert.created", "created_at": "2026-11-16T18:23:41Z", "data": {"alert": { … as above … }}}
```

Headers: `X-HSS-Event`, `X-HSS-Delivery` (the same on every retry: use it to ignore duplicates) and
`X-HSS-Signature: t=<unix time>,v1=<hex>`, where v1 is the HMAC-SHA256 of `"<t>.<raw body>"` with the webhook's
secret (shown once when the webhook is made; **New secret** replaces it).

Answer with any 2xx within 10 seconds. Otherwise HSS tries again after 1, 5 and 30 minutes, then 2 and 6 hours; after
50 failures in a row the webhook is paused (the console shows why). Receivers must use https, except on the site's own
private network; the platform's internal services can't be targeted.

Checking the signature (Python):

```python
import hashlib, hmac, time

def verify(secret: str, body: bytes, header: str, tolerance: int = 300) -> bool:
    parts = dict(p.split("=", 1) for p in header.split(","))
    t = int(parts["t"])
    if abs(time.time() - t) > tolerance:          # stale or replayed
        return False
    expected = hmac.new(secret.encode(), str(t).encode() + b"." + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts["v1"])
```

Node.js:

```js
const crypto = require("crypto");
function verify(secret, rawBody, header, tolerance = 300) {
  const parts = Object.fromEntries(header.split(",").map(p => p.split("=")));
  if (Math.abs(Date.now() / 1000 - Number(parts.t)) > tolerance) return false;
  const expected = crypto.createHmac("sha256", secret).update(`${parts.t}.${rawBody}`).digest("hex");
  return crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(parts.v1));
}
```

Check the raw body as received, before parsing the JSON.
