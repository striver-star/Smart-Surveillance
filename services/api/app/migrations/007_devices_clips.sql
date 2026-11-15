-- Live device health from the edge service (Phase 3 part B) and video clips for alerts.
CREATE TABLE IF NOT EXISTS device_health (
    nvr         text PRIMARY KEY,                 -- NVR address
    alias       text NOT NULL,                    -- nvr<last octet>, the prefix of camera ids
    reachable   boolean NOT NULL,
    data        jsonb NOT NULL,                   -- model, firmware, channels, disks
    checked_at  timestamptz NOT NULL,
    changed_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS clips (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id    uuid REFERENCES alerts (id) ON DELETE CASCADE,
    event_id    uuid NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    camera_id   text NOT NULL,
    starts_at   timestamptz NOT NULL,
    ends_at     timestamptz NOT NULL,
    not_before  timestamptz NOT NULL,             -- the NVR needs the recording to exist first
    status      text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'working', 'done', 'failed')),
    attempts    integer NOT NULL DEFAULT 0,
    detail      text NOT NULL DEFAULT '',
    path        text,
    sha256      text,
    size_bytes  bigint,
    requested_by text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS clips_queue ON clips (status, not_before);
CREATE INDEX IF NOT EXISTS clips_alert ON clips (alert_id);
