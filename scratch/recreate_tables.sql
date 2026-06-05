-- Recreate the videos table with clean single-table schema
DROP TABLE IF EXISTS insights CASCADE;
DROP TABLE IF EXISTS videos CASCADE;

CREATE TABLE videos (
    video_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    upload_date TEXT,
    status TEXT DEFAULT 'pending',
    model TEXT,
    telegram_summary_text TEXT,
    webpage_detailed_info_text TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
