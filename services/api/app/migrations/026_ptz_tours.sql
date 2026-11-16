-- Release 2.0: PTZ patrol tours, run by HSS (ptz_tours.py).
CREATE TABLE IF NOT EXISTS ptz_tours (
    id           serial PRIMARY KEY,
    camera_id    text NOT NULL,
    name         text NOT NULL,
    steps        jsonb NOT NULL,                   -- [{"preset": 3, "dwell_s": 20}, ...]
    days         integer[] NOT NULL DEFAULT '{1,2,3,4,5,6,7}',   -- ISO weekdays, Monday = 1
    start_local  time,                             -- both empty = all day; start after end = overnight
    end_local    time,
    enabled      boolean NOT NULL DEFAULT true,
    paused_until timestamptz,                      -- an operator paused it
    paused_by    text NOT NULL DEFAULT '',
    created_by   text NOT NULL DEFAULT '',
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ptz_tours_camera ON ptz_tours (camera_id);
