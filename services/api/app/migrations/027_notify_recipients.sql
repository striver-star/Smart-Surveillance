-- Message recipients managed in the console (replaces config/recipients.json, which is imported once).
CREATE TABLE IF NOT EXISTS notify_recipients (
    id            serial PRIMARY KEY,
    name          text NOT NULL,
    role          text NOT NULL DEFAULT '',
    whatsapp      text NOT NULL DEFAULT '',         -- +<country code><number>
    email         text NOT NULL DEFAULT '',
    subscriptions text[] NOT NULL DEFAULT '{}',
    enabled       boolean NOT NULL DEFAULT true,
    updated_by    text NOT NULL DEFAULT '',
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);
