-- Alerts and incident workflow (Section 5.5): an alert is raised when an event matches an alert rule.
CREATE TABLE IF NOT EXISTS alerts (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         text NOT NULL DEFAULT 'default',
    event_id          uuid NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    rule              text NOT NULL,                          -- name of the rule that raised it
    severity          text NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    status            text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'acknowledged', 'closed')),
    assigned_to       text,                                   -- username
    acknowledged_by   text,
    acknowledged_at   timestamptz,
    closed_by         text,
    closed_at         timestamptz,
    close_reason      text CHECK (close_reason IN ('real_incident', 'false_alarm', 'test', 'duplicate', 'other')),
    escalation_level  integer NOT NULL DEFAULT 0,
    escalate_after_s  integer,                                -- from the rule; null = no escalation
    last_escalated_at timestamptz,
    channels          jsonb NOT NULL DEFAULT '[]'::jsonb,     -- channels the rule asked for
    created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS alerts_status_time ON alerts (status, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS alerts_event ON alerts (event_id);

CREATE TABLE IF NOT EXISTS alert_timeline (
    id        bigserial PRIMARY KEY,
    alert_id  uuid NOT NULL REFERENCES alerts (id) ON DELETE CASCADE,
    at        timestamptz NOT NULL DEFAULT now(),
    username  text,                                           -- null for the system
    kind      text NOT NULL,                                  -- raised, notified, acknowledged, assigned, comment, escalated, closed, reopened, exported
    text      text NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS alert_timeline_alert ON alert_timeline (alert_id, at);
