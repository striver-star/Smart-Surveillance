-- Release 2.0, face and plate recognition stage 4 (go-live): watchlists, operator verdicts.
-- Every entry has a reason, a consent or legal authority reference and an expiry date. Photos are files
-- under the data folder (watchlist/); embeddings are computed by the recognition worker and kept here.
CREATE TABLE IF NOT EXISTS watch_people (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    list          text NOT NULL,
    name          text NOT NULL,
    reason        text NOT NULL,
    authority_ref text NOT NULL,
    expires_at    date NOT NULL,
    added_by      text NOT NULL,
    added_at      timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    active        boolean NOT NULL DEFAULT true
);
CREATE TABLE IF NOT EXISTS watch_faces (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id   uuid NOT NULL REFERENCES watch_people (id) ON DELETE CASCADE,
    file        text NOT NULL,
    status      text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'ok', 'rejected')),
    problem     text NOT NULL DEFAULT '',
    embedding   bytea,                    -- 128 float32, unit length (SFace)
    quality     jsonb NOT NULL DEFAULT '{}'::jsonb,
    added_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS watch_faces_person ON watch_faces (person_id);
CREATE TABLE IF NOT EXISTS watch_plates (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plate         text NOT NULL,           -- normalised: letters and digits only, upper case
    list          text NOT NULL CHECK (list IN ('block', 'watch', 'allow')),
    name          text NOT NULL DEFAULT '',
    reason        text NOT NULL,
    authority_ref text NOT NULL,
    expires_at    date NOT NULL,
    added_by      text NOT NULL,
    added_at      timestamptz NOT NULL DEFAULT now(),
    active        boolean NOT NULL DEFAULT true
);
CREATE UNIQUE INDEX IF NOT EXISTS watch_plates_plate ON watch_plates (plate) WHERE active;
CREATE TABLE IF NOT EXISTS recognition_verdicts (
    alert_id   uuid PRIMARY KEY,           -- kept after the alert is deleted: verdicts (no names) are the accuracy record
    verdict    text NOT NULL CHECK (verdict IN ('confirmed', 'rejected')),
    username   text NOT NULL,
    at         timestamptz NOT NULL DEFAULT now(),
    note       text NOT NULL DEFAULT '',
    camera_id  text NOT NULL,
    kind       text NOT NULL,              -- face or plate
    score      real
);
