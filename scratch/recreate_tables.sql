-- Recreate the videos table with clean schema
DROP TABLE IF EXISTS insights CASCADE;
DROP TABLE IF EXISTS videos CASCADE;

CREATE TABLE videos (
    video_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    upload_date TEXT,
    status TEXT DEFAULT 'pending',
    model TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Recreate the insights table with clean schema (only storing newsletter_text)
CREATE TABLE insights (
    video_id TEXT PRIMARY KEY REFERENCES videos(video_id) ON DELETE CASCADE,
    newsletter_text TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);
