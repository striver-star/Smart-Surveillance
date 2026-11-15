-- Legal review gate for face and plate recognition: who read it, and who accepted which version.
CREATE TABLE IF NOT EXISTS legal_reads (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document    text NOT NULL,
    version     text NOT NULL,
    user_id     uuid NOT NULL,
    opened_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS legal_acceptances (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document      text NOT NULL,                 -- face-plate
    version       text NOT NULL,                 -- hash of the document text accepted
    scopes        text[] NOT NULL,               -- face, plate
    user_id       uuid,
    username      text NOT NULL,
    full_name     text NOT NULL,
    position      text NOT NULL,
    reviewer_name text NOT NULL,                 -- legal practitioner who gave the opinion
    reviewer_firm text NOT NULL,
    opinion_ref   text NOT NULL,
    opinion_date  date NOT NULL,
    dpia_ref      text NOT NULL,
    conditions    jsonb NOT NULL,                -- the conditions as worded when accepted
    read_seconds  integer NOT NULL,
    accepted_at   timestamptz NOT NULL DEFAULT now(),
    expires_at    timestamptz NOT NULL,
    revoked_at    timestamptz,
    revoked_by    text,
    revoke_reason text
);
CREATE INDEX IF NOT EXISTS legal_acceptances_doc ON legal_acceptances (document, accepted_at DESC);
