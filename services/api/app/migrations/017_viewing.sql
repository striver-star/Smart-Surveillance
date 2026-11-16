-- Viewing log (release 2.0): who watched which camera, live or recorded, when and from where.
CREATE TABLE IF NOT EXISTS view_log (
    id          bigserial PRIMARY KEY,
    started_at  timestamptz NOT NULL DEFAULT now(),
    last_at     timestamptz NOT NULL DEFAULT now(),     -- live: the last time this person (re)connected to the camera
    user_id     uuid,
    username    text NOT NULL,
    role        text,
    camera_id   text NOT NULL,
    kind        text NOT NULL CHECK (kind IN ('live', 'playback')),
    recorded_at timestamptz,                           -- playback: the time in the recording
    ip          text
);
CREATE INDEX IF NOT EXISTS view_log_started ON view_log (started_at DESC);
CREATE INDEX IF NOT EXISTS view_log_camera ON view_log (camera_id, started_at DESC);
CREATE INDEX IF NOT EXISTS view_log_user ON view_log (username, started_at DESC);
