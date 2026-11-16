-- Release 2.0: control-room large-screen mode. A wall screen is either a camera grid or the control-room
-- status board (alerts, site map, devices, guards, lockdown), optionally on one site plan.
ALTER TABLE wall_screens ADD COLUMN IF NOT EXISTS kind text NOT NULL DEFAULT 'cameras';
ALTER TABLE wall_screens DROP CONSTRAINT IF EXISTS wall_screens_kind_check;
ALTER TABLE wall_screens ADD CONSTRAINT wall_screens_kind_check CHECK (kind IN ('cameras', 'control'));
ALTER TABLE wall_screens ADD COLUMN IF NOT EXISTS plan_id integer;
