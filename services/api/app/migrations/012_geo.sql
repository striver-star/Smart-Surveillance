-- Phase 5: site plans, camera geotags, zones (geofences), tracked units (guards, vehicles) and positions.
-- Plans are uploaded images; two reference points tie a plan to latitude and longitude, so zones drawn
-- on it become PostGIS polygons and GPS positions can be tested against them.
CREATE TABLE IF NOT EXISTS site_plans (
    id          serial PRIMARY KEY,
    name        text NOT NULL UNIQUE,
    file        text NOT NULL,
    mime        text NOT NULL,
    width       integer NOT NULL,
    height      integer NOT NULL,
    refs        jsonb NOT NULL DEFAULT '[]'::jsonb,  -- [{x, y, lat, lon}, {x, y, lat, lon}] in image pixels
    sort        integer NOT NULL DEFAULT 0,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS camera_geo (
    camera_id   text PRIMARY KEY,
    plan_id     integer NOT NULL REFERENCES site_plans (id) ON DELETE CASCADE,
    x           real NOT NULL,
    y           real NOT NULL,
    bearing     real NOT NULL DEFAULT 0,         -- degrees, 0 = up on the plan, clockwise
    fov         real NOT NULL DEFAULT 90,        -- degrees
    reach       real NOT NULL DEFAULT 120,       -- drawn length of the view, image pixels
    geom        geography(Point, 4326)           -- set when the plan has reference points
);

CREATE TABLE IF NOT EXISTS zones (
    id            serial PRIMARY KEY,
    name          text NOT NULL,
    kind          text NOT NULL CHECK (kind IN ('restricted', 'perimeter', 'checkpoint', 'area')),
    plan_id       integer NOT NULL REFERENCES site_plans (id) ON DELETE CASCADE,
    points        jsonb NOT NULL,                -- [[x, y], ...] image pixels
    geom          geometry(Polygon, 4326),       -- set when the plan has reference points
    applies_to    text NOT NULL DEFAULT 'all' CHECK (applies_to IN ('all', 'guard', 'vehicle')),
    alert_on      text NOT NULL DEFAULT 'enter' CHECK (alert_on IN ('enter', 'exit', 'both', 'none')),
    severity      text NOT NULL DEFAULT 'warning' CHECK (severity IN ('info', 'warning', 'critical')),
    armed         jsonb NOT NULL DEFAULT '[]'::jsonb,   -- [["18:00", "06:00"]]; empty = always
    cameras       jsonb NOT NULL DEFAULT '[]'::jsonb,   -- cameras covering the zone
    visit_every_min integer,                       -- checkpoints: alert if no guard visits within this time
    enabled       boolean NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tracked_units (
    id          serial PRIMARY KEY,
    name        text NOT NULL UNIQUE,
    kind        text NOT NULL DEFAULT 'guard' CHECK (kind IN ('guard', 'vehicle')),
    device_id   text NOT NULL UNIQUE,            -- the identifier set in Traccar Client (or tracker IMEI)
    active      boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS unit_positions (
    id          bigserial PRIMARY KEY,
    unit_id     integer NOT NULL REFERENCES tracked_units (id) ON DELETE CASCADE,
    at          timestamptz NOT NULL,
    geom        geography(Point, 4326) NOT NULL,
    accuracy    real,
    speed_kmh   real,
    battery     real,
    alarm       text
);
CREATE INDEX IF NOT EXISTS unit_positions_time ON unit_positions (unit_id, at DESC);

CREATE TABLE IF NOT EXISTS unit_state (
    unit_id       integer PRIMARY KEY REFERENCES tracked_units (id) ON DELETE CASCADE,
    last_at       timestamptz,
    lat           double precision,
    lon           double precision,
    battery       real,
    speed_kmh     real,
    zones         integer[] NOT NULL DEFAULT '{}',
    offline       boolean NOT NULL DEFAULT false,
    low_battery   boolean NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS checkpoint_visits (
    zone_id     integer NOT NULL REFERENCES zones (id) ON DELETE CASCADE,
    unit_id     integer NOT NULL REFERENCES tracked_units (id) ON DELETE CASCADE,
    at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS checkpoint_visits_zone ON checkpoint_visits (zone_id, at DESC);
