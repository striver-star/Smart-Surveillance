-- Phase 3: evidence vault. A sealed evidence package is a zip written once, never changed, with its
-- SHA-256 recorded; every access is written to a hash-chained custody log.
CREATE TABLE IF NOT EXISTS evidence (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id      uuid REFERENCES alerts (id) ON DELETE SET NULL,
    camera_id     text NOT NULL DEFAULT '',
    title         text NOT NULL,
    case_ref      text NOT NULL DEFAULT '',          -- police or insurance reference
    reason        text NOT NULL DEFAULT '',
    file          text NOT NULL,                     -- path under the data folder
    sha256        text NOT NULL,
    size_bytes    bigint NOT NULL,
    manifest      jsonb NOT NULL,
    sealed_by     text NOT NULL,
    sealed_at     timestamptz NOT NULL DEFAULT now(),
    retain_until  date NOT NULL,
    legal_hold    boolean NOT NULL DEFAULT false,
    hold_reason   text NOT NULL DEFAULT '',
    deleted_at    timestamptz,
    deleted_by    text
);
CREATE INDEX IF NOT EXISTS evidence_alert ON evidence (alert_id);

CREATE TABLE IF NOT EXISTS evidence_custody (
    seq          bigserial PRIMARY KEY,
    evidence_id  uuid NOT NULL REFERENCES evidence (id) ON DELETE CASCADE,
    at           timestamptz NOT NULL DEFAULT now(),
    username     text NOT NULL,
    action       text NOT NULL,      -- sealed, downloaded, verified, verify_failed, hold_on, hold_off, retention, deleted
    detail       text NOT NULL DEFAULT '',
    ip           text NOT NULL DEFAULT '',
    prev_hash    text NOT NULL,
    hash         text NOT NULL       -- SHA-256 of prev_hash and this entry: editing any entry breaks the chain
);
