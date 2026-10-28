-- Wall PCs (wall nodes) and the page each of their monitors shows (Section 8: Wall Node and Layout).
CREATE TABLE IF NOT EXISTS wall_nodes (
    id             text PRIMARY KEY,
    tenant_id      text NOT NULL DEFAULT 'default',
    hostname       text,
    agent_version  text,
    os             text,
    first_seen     timestamptz NOT NULL DEFAULT now(),
    last_seen      timestamptz NOT NULL DEFAULT now(),
    health         jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS wall_layouts (
    node_id     text NOT NULL REFERENCES wall_nodes(id) ON DELETE CASCADE,
    monitor     int  NOT NULL CHECK (monitor BETWEEN 0 AND 15),
    path        text NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (node_id, monitor)
);
