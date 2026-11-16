-- Release 2.0: open API keys and webhooks.
CREATE TABLE IF NOT EXISTS api_keys (
    id          text PRIMARY KEY,                  -- public part of the key: hss_<id>_<secret>
    name        text NOT NULL,
    secret_hash text NOT NULL,                     -- SHA-256 of the secret; the key is shown once
    scopes      text[] NOT NULL,
    cameras     jsonb NOT NULL DEFAULT '[]'::jsonb, -- patterns, as for users; empty = every camera
    created_by  text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  date,
    last_used   timestamptz,
    last_ip     text,
    revoked_at  timestamptz
);
CREATE TABLE IF NOT EXISTS webhooks (
    id          serial PRIMARY KEY,
    name        text NOT NULL,
    url         text NOT NULL,
    secret      text NOT NULL,                     -- encrypted with the credentials vault; signs each delivery
    events      text[] NOT NULL,
    min_severity text NOT NULL DEFAULT 'warning',
    cameras     jsonb NOT NULL DEFAULT '[]'::jsonb,
    enabled     boolean NOT NULL DEFAULT true,
    created_by  text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    failures    integer NOT NULL DEFAULT 0,        -- consecutive failed deliveries; paused at 50
    paused_reason text NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id          bigserial PRIMARY KEY,
    hook_id     integer NOT NULL REFERENCES webhooks (id) ON DELETE CASCADE,
    event_id    uuid NOT NULL DEFAULT gen_random_uuid(),
    type        text NOT NULL,
    payload     jsonb NOT NULL,
    status      text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'failed')),
    attempts    integer NOT NULL DEFAULT 0,
    next_at     timestamptz NOT NULL DEFAULT now(),
    last_code   integer,
    last_error  text NOT NULL DEFAULT '',
    created_at  timestamptz NOT NULL DEFAULT now(),
    sent_at     timestamptz
);
CREATE INDEX IF NOT EXISTS webhook_deliveries_due ON webhook_deliveries (next_at) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS webhook_deliveries_hook ON webhook_deliveries (hook_id, created_at DESC);
-- The alert status last announced to webhooks, so a status change is announced once, even across restarts.
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS notified_status text;
