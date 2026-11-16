-- Release 2.0: access control and video intercom (Hikvision ISAPI devices).
CREATE TABLE IF NOT EXISTS access_devices (
    id          serial PRIMARY KEY,
    name        text NOT NULL,
    kind        text NOT NULL CHECK (kind IN ('controller', 'doorstation')),
    address     text NOT NULL UNIQUE,              -- host or host:port of the device's web (ISAPI) port
    scheme      text NOT NULL DEFAULT 'http',
    username    text NOT NULL,
    secret      text NOT NULL,                     -- encrypted with the credentials vault
    enabled     boolean NOT NULL DEFAULT true,
    info        jsonb NOT NULL DEFAULT '{}'::jsonb, -- model, serial, firmware
    online      boolean,
    last_seen   timestamptz,
    last_error  text NOT NULL DEFAULT '',
    cursor_at   timestamptz,                       -- newest access event read
    call_status text NOT NULL DEFAULT 'idle',
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS doors (
    id               serial PRIMARY KEY,
    device_id        integer NOT NULL REFERENCES access_devices (id) ON DELETE CASCADE,
    door_no          integer NOT NULL,
    name             text NOT NULL,
    camera_id        text,                         -- the camera that watches this door
    remote_open      boolean NOT NULL DEFAULT false, -- may operators open it from the console
    lock_in_lockdown boolean NOT NULL DEFAULT false,
    lock_state       text,                         -- locked / unlocked
    contact_state    text,                         -- closed / open
    mode             text,                         -- normal / stay_open / stay_locked
    status_at        timestamptz,
    UNIQUE (device_id, door_no)
);
CREATE TABLE IF NOT EXISTS access_events (
    id          bigserial PRIMARY KEY,
    device_id   integer NOT NULL REFERENCES access_devices (id) ON DELETE CASCADE,
    door_id     integer REFERENCES doors (id) ON DELETE SET NULL,
    serial_no   bigint,                            -- the device's own event number (no duplicates)
    at          timestamptz NOT NULL,
    kind        text NOT NULL,                     -- granted, denied, forced, held_open, door_open, door_closed, ...
    major       integer,
    minor       integer,
    person      text NOT NULL DEFAULT '',
    employee_no text NOT NULL DEFAULT '',
    card        text NOT NULL DEFAULT '',          -- masked: last 4 digits
    verify_mode text NOT NULL DEFAULT '',
    by_user     text NOT NULL DEFAULT '',          -- console user, for remote commands
    event_id    uuid                               -- the HSS event raised from it, if any
);
CREATE UNIQUE INDEX IF NOT EXISTS access_events_serial ON access_events (device_id, serial_no) WHERE serial_no IS NOT NULL;
CREATE INDEX IF NOT EXISTS access_events_at ON access_events (at DESC);
CREATE INDEX IF NOT EXISTS access_events_door ON access_events (door_id, at DESC);
