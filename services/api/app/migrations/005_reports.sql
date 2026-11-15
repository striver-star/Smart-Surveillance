-- Generated reports (Section 5.6): archived, searchable, re-sendable.
CREATE TABLE IF NOT EXISTS reports (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     text NOT NULL DEFAULT 'default',
    kind          text NOT NULL CHECK (kind IN ('daily', 'weekly', 'monthly', 'custom')),
    title         text NOT NULL,
    period_start  timestamptz NOT NULL,
    period_end    timestamptz NOT NULL,
    timezone      text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    created_by    text NOT NULL,                     -- username, or 'schedule'
    summary       text NOT NULL DEFAULT '',          -- the plain-language summary, for search and preview
    figures       jsonb NOT NULL DEFAULT '{}'::jsonb,  -- headline numbers for the console
    pdf_path      text,
    docx_path     text,
    sent          jsonb NOT NULL DEFAULT '[]'::jsonb   -- delivery attempts when sent
);
CREATE INDEX IF NOT EXISTS reports_created ON reports (created_at DESC);
CREATE INDEX IF NOT EXISTS reports_kind_period ON reports (kind, period_start DESC);
