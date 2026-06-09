import os
import sys
import logging

# Append parent dir to path to import db
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from db import get_db_client

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def update_db_links():
    logging.info("Starting Supabase database links migration...")
    supabase = get_db_client()
    
    # Fetch all videos
    try:
        response = supabase.table("videos").select("*").execute()
        videos = response.data or []
        logging.info(f"Fetched {len(videos)} videos from Supabase.")
    except Exception as e:
        logging.error(f"Failed to fetch videos from Supabase: {e}")
        return

    old_url = "https://ai-engineer-newsletter.vercel.app"
    new_url = "https://briannoelkesuma.github.io/ai_engineer_newsletter/public"
    
    updated_count = 0
    
    for vid in videos:
        video_id = vid.get("video_id")
        title = vid.get("title")
        telegram_summary = vid.get("telegram_summary_text") or ""
        
        if old_url in telegram_summary:
            updated_summary = telegram_summary.replace(old_url, new_url)
            logging.info(f"Updating links for video {video_id}: '{title}'...")
            
            try:
                supabase.table("videos").update({
                    "telegram_summary_text": updated_summary
                }).eq("video_id", video_id).execute()
                updated_count += 1
            except Exception as e:
                logging.error(f"Failed to update video {video_id}: {e}")
                
    logging.info(f"Migration finished. Updated {updated_count} rows in Supabase.")

if __name__ == "__main__":
    update_db_links()
