-- Every notification attempt (WhatsApp, email, push) and the WhatsApp gateway's connection history.
CREATE TABLE IF NOT EXISTS deliveries (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    text NOT NULL DEFAULT 'default',
    created_at   timestamptz NOT NULL DEFAULT now(),
    topic        text NOT NULL,              -- daily, weekly, monthly, critical, device, system, test
    recipient    text,                       -- recipient name from recipients.json
    channel      text NOT NULL,              -- whatsapp | email | ntfy
    address      text,                       -- masked: last 4 digits or e-mail domain only
    status       text NOT NULL,              -- sent | delivered | read | failed
    detail       text,
    message_id   text,
    is_fallback  boolean NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS deliveries_time ON deliveries (created_at DESC);

CREATE TABLE IF NOT EXISTS gateway_events (
    at       timestamptz NOT NULL DEFAULT now(),
    status   text NOT NULL,
    detail   text
);
