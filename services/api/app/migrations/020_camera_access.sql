-- Release 2.0: per-camera permissions and read-only roles.
-- viewer: watches live and recorded video, reads alerts and events (no actions), for their cameras.
-- client: an outside client's account: live (and, if allowed, recorded) video of their cameras only.
-- cameras: patterns like "nvr4-*" or "nvr1-ch05"; empty = every camera. Admins and the CSO always see all.
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE users ADD CONSTRAINT users_role_check
    CHECK (role IN ('admin', 'cso', 'operator', 'management', 'guard', 'viewer', 'client'));
ALTER TABLE users ADD COLUMN IF NOT EXISTS cameras jsonb NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE users ADD COLUMN IF NOT EXISTS can_playback boolean NOT NULL DEFAULT true;
