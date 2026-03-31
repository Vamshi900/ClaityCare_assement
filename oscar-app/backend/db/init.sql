CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS policies (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT NOT NULL,
    guideline_code  TEXT,
    version         TEXT,
    pdf_url         TEXT NOT NULL UNIQUE,
    source_page_url TEXT NOT NULL,
    discovered_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status          TEXT NOT NULL DEFAULT 'discovered'
);

CREATE INDEX IF NOT EXISTS idx_policies_pdf_url ON policies(pdf_url);
CREATE INDEX IF NOT EXISTS idx_policies_guideline_code ON policies(guideline_code);

CREATE TABLE IF NOT EXISTS downloads (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_id       UUID NOT NULL REFERENCES policies(id) ON DELETE CASCADE,
    stored_location TEXT,
    downloaded_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    http_status     INTEGER,
    file_size_bytes BIGINT,
    content_hash    TEXT,
    error           TEXT,
    attempt_number  INTEGER NOT NULL DEFAULT 1,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_downloads_policy_id ON downloads(policy_id);

CREATE TABLE IF NOT EXISTS structured_policies (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_id         UUID NOT NULL REFERENCES policies(id) ON DELETE CASCADE,
    extracted_text_ref TEXT,
    structured_json   JSONB NOT NULL,
    structured_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    llm_metadata      JSONB NOT NULL,
    validation_error  TEXT,
    initial_only_method TEXT,
    version         INTEGER NOT NULL DEFAULT 1,
    is_current      BOOLEAN NOT NULL DEFAULT true,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_structured_policy_id ON structured_policies(policy_id);

CREATE TABLE IF NOT EXISTS jobs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'queued',
    source_url  TEXT,
    started_at  TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    metadata    JSONB,
    error       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
