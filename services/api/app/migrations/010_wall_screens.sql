-- Phase 2: wall screens. A screen is a grid of cameras shown on one TV; with more cameras than
-- tiles it rotates through pages. Wall PCs show a screen per monitor (wall_layouts.path).
CREATE TABLE IF NOT EXISTS wall_screens (
    id           serial PRIMARY KEY,
    name         text NOT NULL UNIQUE,
    source       text NOT NULL DEFAULT 'cameras',     -- 'all', 'nvr:<alias>' or 'cameras'
    cameras      jsonb NOT NULL DEFAULT '[]'::jsonb,  -- gateway paths, for source 'cameras'
    tiles        integer NOT NULL DEFAULT 16 CHECK (tiles IN (1, 4, 6, 9, 16, 25, 32, 36, 64)),
    dwell_s      integer NOT NULL DEFAULT 20 CHECK (dwell_s BETWEEN 5 AND 600),
    labels       boolean NOT NULL DEFAULT true,
    pin_alerts   boolean NOT NULL DEFAULT true,       -- cameras with open alerts stay on screen, outlined
    key          text NOT NULL,                       -- in the screen's URL; wall PCs don't sign in
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
