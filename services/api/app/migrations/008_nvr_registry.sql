-- Phase 1: NVRs added from the console, with their login kept encrypted, and per-camera tier overrides.
CREATE TABLE IF NOT EXISTS nvrs (
    id          serial PRIMARY KEY,
    address     text NOT NULL UNIQUE,              -- host or host:port of the NVR's web (ISAPI) service
    alias       text NOT NULL UNIQUE,              -- prefix of camera ids and gateway paths, e.g. nvr4
    name        text NOT NULL DEFAULT '',
    username    text NOT NULL,
    secret      text NOT NULL,                     -- the password, encrypted by the vault (never returned)
    scheme      text NOT NULL DEFAULT 'http' CHECK (scheme IN ('http', 'https')),
    rtsp_port   integer NOT NULL DEFAULT 554 CHECK (rtsp_port BETWEEN 1 AND 65535),
    segment     text NOT NULL DEFAULT '',          -- network segment / VLAN label
    enabled     boolean NOT NULL DEFAULT true,     -- watched by the edge service
    live_view   boolean NOT NULL DEFAULT true,     -- cameras added to the stream gateway
    info        jsonb NOT NULL DEFAULT '{}',       -- last connection test: model, firmware, channels
    test_ok     boolean,
    test_detail text NOT NULL DEFAULT '',
    tested_at   timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS camera_overrides (
    camera_id   text PRIMARY KEY,                  -- nvr4-ch22
    tier        text CHECK (tier IN ('E', 'N', 'S')),
    note        text NOT NULL DEFAULT '',
    updated_by  text NOT NULL DEFAULT '',
    updated_at  timestamptz NOT NULL DEFAULT now()
);
