-- Run this in your Supabase SQL Editor to create the required table.

CREATE TABLE IF NOT EXISTS transcriptions (
    id           SERIAL PRIMARY KEY,
    url          TEXT NOT NULL,
    title        TEXT,
    duration     DOUBLE PRECISION,
    segments     JSONB NOT NULL DEFAULT '[]'::jsonb,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_transcriptions_url ON transcriptions(url);
CREATE INDEX IF NOT EXISTS idx_transcriptions_processed_at ON transcriptions(processed_at);
