-- Normalized events from every source (edge camera, NVR, server AI). Section 8 of the context document.
-- tenant_id becomes a foreign key with row-level security in Phase 1.
CREATE TABLE IF NOT EXISTS events (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     text NOT NULL DEFAULT 'default',
    camera_id     text NOT NULL,
    source_kind   text NOT NULL,            -- edge | nvr | server_ai
    source_ref    text,                     -- device or worker id
    tier          text NOT NULL,            -- E | N | S
    type          text NOT NULL,            -- intrusion, line_crossing, ...
    object_class  text,                     -- human | vehicle | null
    zone          text,
    severity      text NOT NULL,            -- info | warning | critical
    confidence    real,
    occurred_at   timestamptz NOT NULL,     -- when the frame or device event happened
    received_at   timestamptz NOT NULL DEFAULT now(),
    snapshot_ref  text,
    clip_ref      text,
    geotag        geography(Point, 4326),
    raw           jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS events_camera_time ON events (camera_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS events_time ON events (occurred_at DESC);
