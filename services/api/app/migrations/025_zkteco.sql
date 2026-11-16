-- Release 2.0: ZKTeco access panels and terminals (push protocol), alongside Hikvision.
ALTER TABLE access_devices ADD COLUMN IF NOT EXISTS vendor text NOT NULL DEFAULT 'hikvision';
ALTER TABLE access_devices ADD COLUMN IF NOT EXISTS serial text;     -- ZKTeco: the serial number it calls in with
CREATE UNIQUE INDEX IF NOT EXISTS access_devices_serial ON access_devices (serial) WHERE serial IS NOT NULL;

-- ZKTeco devices that called in but haven't been added by an administrator (nothing they send is kept).
CREATE TABLE IF NOT EXISTS zk_waiting (
    serial     text PRIMARY KEY,
    ip         text NOT NULL,
    info       jsonb NOT NULL DEFAULT '{}'::jsonb,
    first_seen timestamptz NOT NULL DEFAULT now(),
    last_seen  timestamptz NOT NULL DEFAULT now()
);

-- Commands waiting for a ZKTeco device to collect them (it asks every few seconds), and its answers.
CREATE TABLE IF NOT EXISTS zk_commands (
    id        serial PRIMARY KEY,
    device_id integer NOT NULL REFERENCES access_devices (id) ON DELETE CASCADE,
    command   text NOT NULL,
    queued_at timestamptz NOT NULL DEFAULT now(),
    sent_at   timestamptz,
    done_at   timestamptz,
    result    integer                              -- the device's return code; 0 = done
);
CREATE INDEX IF NOT EXISTS zk_commands_pending ON zk_commands (device_id) WHERE sent_at IS NULL;

-- Names for the PINs a ZKTeco device reports (its user list, when it sends one).
CREATE TABLE IF NOT EXISTS zk_people (
    device_id integer NOT NULL REFERENCES access_devices (id) ON DELETE CASCADE,
    pin       text NOT NULL,
    name      text NOT NULL DEFAULT '',
    PRIMARY KEY (device_id, pin)
);

-- ZKTeco devices are known by serial number; several may call in through one address (NAT), so the address
-- only has to be unique for Hikvision devices (which HSS calls).
ALTER TABLE access_devices DROP CONSTRAINT IF EXISTS access_devices_address_key;
CREATE UNIQUE INDEX IF NOT EXISTS access_devices_hik_address ON access_devices (address) WHERE vendor = 'hikvision';
