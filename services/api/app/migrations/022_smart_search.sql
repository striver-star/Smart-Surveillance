-- Release 2.0, smart search: people and vehicles found in event snapshots, with their colours.
-- objects: [{"class": "human", "box": [x1, y1, x2, y2], "upper": ["red"], "lower": ["blue"]}, {"class": "vehicle", "body": ["white"]}]
CREATE TABLE IF NOT EXISTS event_attributes (
    event_id    uuid PRIMARY KEY REFERENCES events (id) ON DELETE CASCADE,
    objects     jsonb NOT NULL DEFAULT '[]'::jsonb,
    analysed_at timestamptz NOT NULL DEFAULT now(),
    ok          boolean NOT NULL DEFAULT true
);
CREATE INDEX IF NOT EXISTS event_attributes_objects ON event_attributes USING gin (objects jsonb_path_ops);
