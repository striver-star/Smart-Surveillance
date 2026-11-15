-- Release 2.0 phone app: a 'guard' role (phone app only), and guards linked to their tracked unit.
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (role IN ('admin', 'cso', 'operator', 'management', 'guard'));
ALTER TABLE tracked_units ADD COLUMN IF NOT EXISTS username text UNIQUE;
