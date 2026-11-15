-- Release 2.0: sirens, lights and relays that alert rules switch on.
CREATE TABLE IF NOT EXISTS outputs (
    id          serial PRIMARY KEY,
    name        text NOT NULL UNIQUE,
    kind        text NOT NULL CHECK (kind IN ('nvr_relay', 'http')),
    nvr_alias   text,                         -- nvr_relay: which NVR
    port        integer,                      -- nvr_relay: alarm output number
    url_on      text,                         -- http: address that switches it on
    url_off     text,                         -- http: address that switches it off (optional)
    method      text NOT NULL DEFAULT 'GET' CHECK (method IN ('GET', 'POST', 'PUT')),
    username    text NOT NULL DEFAULT '',
    secret      text NOT NULL DEFAULT '',     -- http: password, encrypted by the vault
    duration_s  integer NOT NULL DEFAULT 60 CHECK (duration_s BETWEEN 0 AND 3600),   -- 0 = stays on until switched off
    enabled     boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now()
);
