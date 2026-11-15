-- Phase 8: backup and restore-test reports from the backup scripts.
CREATE TABLE IF NOT EXISTS system_reports (
    id          bigserial PRIMARY KEY,
    kind        text NOT NULL,                 -- backup | restore_test | retention
    status      text NOT NULL,                 -- ok | failed
    detail      text NOT NULL DEFAULT '',
    data        jsonb NOT NULL DEFAULT '{}'::jsonb,
    at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS system_reports_kind ON system_reports (kind, at DESC);
