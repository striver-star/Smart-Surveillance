-- Release 2.0: operator logbook and shift handover.
CREATE TABLE IF NOT EXISTS logbook_entries (
    id          bigserial PRIMARY KEY,
    at          timestamptz NOT NULL DEFAULT now(),
    username    text NOT NULL,
    category    text NOT NULL CHECK (category IN ('patrol', 'incident', 'visitor', 'maintenance', 'other')),
    text        text NOT NULL,
    alert_id    uuid REFERENCES alerts (id) ON DELETE SET NULL,
    camera_id   text,
    edited_at   timestamptz
);
CREATE INDEX IF NOT EXISTS logbook_entries_at ON logbook_entries (at DESC);

CREATE TABLE IF NOT EXISTS handovers (
    id           serial PRIMARY KEY,
    shift_label  text NOT NULL,
    shift_start  timestamptz NOT NULL,
    shift_end    timestamptz NOT NULL,
    from_user    text NOT NULL,
    from_at      timestamptz NOT NULL DEFAULT now(),
    notes        text NOT NULL DEFAULT '',
    summary      jsonb NOT NULL,
    to_user      text,
    to_at        timestamptz,
    to_note      text NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS handovers_from_at ON handovers (from_at DESC);
