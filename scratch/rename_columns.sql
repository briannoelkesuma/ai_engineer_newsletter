-- Rename columns in the videos table to match the new naming scheme
ALTER TABLE videos RENAME COLUMN summary_text TO telegram_summary_text;
ALTER TABLE videos RENAME COLUMN newsletter_text TO webpage_detailed_info_text;
