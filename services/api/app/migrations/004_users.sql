-- Users, sessions, audit log and site branding (Phase 1 groundwork, built early for the console preview).
CREATE TABLE IF NOT EXISTS users (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id             text NOT NULL DEFAULT 'default',
    username              text NOT NULL,
    display_name          text NOT NULL DEFAULT '',
    role                  text NOT NULL CHECK (role IN ('admin', 'cso', 'operator', 'management')),
    password_hash         text NOT NULL,
    must_change_password  boolean NOT NULL DEFAULT false,
    totp_secret           text,                         -- base32, set while 2FA is being set up or on
    totp_enabled          boolean NOT NULL DEFAULT false,
    totp_last_step        bigint,                       -- last accepted time step: a code works once
    failed_attempts       integer NOT NULL DEFAULT 0,
    locked_until          timestamptz,
    disabled              boolean NOT NULL DEFAULT false,
    last_login_at         timestamptz,
    created_at            timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS users_tenant_username ON users (tenant_id, lower(username));

CREATE TABLE IF NOT EXISTS sessions (
    token_hash    text PRIMARY KEY,                     -- SHA-256 of the cookie value; the value itself is never stored
    user_id       uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz NOT NULL DEFAULT now(),
    expires_at    timestamptz NOT NULL,
    ip            text,
    user_agent    text
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions (user_id);

CREATE TABLE IF NOT EXISTS audit_log (
    id        bigserial PRIMARY KEY,
    at        timestamptz NOT NULL DEFAULT now(),
    user_id   uuid,
    username  text,
    action    text NOT NULL,                            -- login, login_failed, logout, user_created, ...
    detail    jsonb NOT NULL DEFAULT '{}'::jsonb,
    ip        text
);
CREATE INDEX IF NOT EXISTS audit_log_at ON audit_log (at DESC);

CREATE TABLE IF NOT EXISTS settings (
    key    text PRIMARY KEY,
    value  jsonb NOT NULL
);
