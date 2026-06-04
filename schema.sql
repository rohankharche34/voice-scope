-- Run this in your Supabase SQL Editor to create the required table.

CREATE TABLE IF NOT EXISTS transcriptions (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    url          TEXT NOT NULL,
    title        TEXT,
    duration     DOUBLE PRECISION,
    segments     JSONB NOT NULL DEFAULT '[]'::jsonb,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_transcriptions_url ON transcriptions(url);
CREATE INDEX IF NOT EXISTS idx_transcriptions_processed_at ON transcriptions(processed_at);

-- Allow the service_role used by supabase-py to read/write the table.
GRANT ALL ON public.transcriptions TO service_role;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO service_role;
