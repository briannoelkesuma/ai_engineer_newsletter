import os
import sys
import logging

# Make parent directory importable
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from db import get_db_client
from main import run_pipeline
from generate_static_site import build_site

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def test_e2e():
    video_id = "wcUJWP6WpGM"
    db = get_db_client()
    
    # 1. Clean up database for a fresh run
    logging.info(f"Cleaning up existing DB row for video ID {video_id}...")
    db.table("videos").delete().eq("video_id", video_id).execute()
    
    # 2. Run the main pipeline (it will add the video, download transcript, call Gemma 4, update DB, and post to Telegram)
    logging.info(f"Running main pipeline for video ID: {video_id}...")
    run_pipeline(target_video_id=video_id)
    
    # 3. Build the static site to compile the HTML page containing this new card
    logging.info("Compiling static site HTML...")
    build_site()
    
    # 4. Verify database state
    logging.info("Retrieving final database record...")
    res = db.table("videos").select("*").eq("video_id", video_id).execute()
    if res.data:
        row = res.data[0]
        print("\n" + "="*50)
        print("E2E PIPELINE SUCCESSFUL!")
        print("="*50)
        print(f"Video ID:    {row['video_id']}")
        print(f"Title:       {row['title']}")
        print(f"Status:      {row['status']}")
        print(f"Model:       {row['model']}")
        print("-"*50)
        print("TELEGRAM SUMMARY TEXT (telegram_summary_text):")
        print("-"*50)
        print(row['telegram_summary_text'])
        print("-"*50)
        print("STATIC SITE DEEP DIVE TEXT (webpage_detailed_info_text) - Snippet:")
        print("-"*50)
        print(row['webpage_detailed_info_text'][:1000] + "\n... [truncated] ...")
        print("="*50 + "\n")
    else:
        logging.error("Failed to find the video row in Supabase after pipeline run.")

if __name__ == "__main__":
    test_e2e()
