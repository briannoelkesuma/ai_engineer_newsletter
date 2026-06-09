import os
import sys
import time
import logging

# Import our pipeline functions
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from transcript_fetcher import fetch_transcript
from llm_analyzer import analyze_transcript
from telegram_bot import send_telegram_message
from db import add_video, update_video_status, get_db_client, get_pending_videos
from generate_static_site import build_site

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# The 9 specific historical video IDs from the past 6 days (excluding today's video 'wcUJWP6WpGM')
BACKFILL_VIDEO_IDS = [
    "hCMrEfPG2Yg",
    "zKk7sDMGDEQ",
    "504PvfXou5Y",
    "HvZXAOZ3iv8",
    "NuePCNMpWGc",
    "N7b1PJc7SFc",
    "UQKg0td-Bf4",
    "B9h9ovW5H9U",
    "V-L0INGTEOg"
]

def format_date(date_str):
    if not date_str or len(date_str) != 8:
        return "Unknown Date"
    return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"

def run_backfill():
    logging.info(f"Starting backfill and Telegram sync for {len(BACKFILL_VIDEO_IDS)} historical videos...")
    
    # 1. Pre-populate database with placeholders
    for vid_id in BACKFILL_VIDEO_IDS:
        add_video(vid_id, f"Backfill Video {vid_id}")
        
    # Get pending videos to process
    pending = get_pending_videos()
    pending = [v for v in pending if v['video_id'] in BACKFILL_VIDEO_IDS]
    
    logging.info(f"Beginning ingestion for {len(pending)} videos...")
    
    processed_count = 0
    
    for idx, p_vid in enumerate(pending):
        video_id = p_vid['video_id']
        title = p_vid['title']
        description = ""
        raw_upload_date = None
        
        logging.info(f"[{idx+1}/{len(pending)}] Ingesting video metadata for: {video_id}")
        
        # Fetch fresh metadata
        try:
            import yt_dlp
            ydl_opts = {'quiet': True, 'skip_download': True}
            proxy_env = os.environ.get("YOUTUBE_PROXY")
            if proxy_env:
                import random
                proxies = [p.strip() for p in proxy_env.split(",") if p.strip()]
                proxy = random.choice(proxies) if proxies else None
                if proxy:
                    ydl_opts['proxy'] = proxy
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
                title = info.get("title", title)
                raw_upload_date = info.get("upload_date", raw_upload_date)
                description = info.get("description", description)
                
                # Update in DB (title only)
                supabase = get_db_client()
                supabase.table("videos").update({
                    "title": title
                }).eq("video_id", video_id).execute()
        except Exception as e:
            logging.warning(f"Failed to fetch metadata for {video_id}: {e}")
            
        upload_date = format_date(raw_upload_date)
        
        logging.info(f"Processing content: {title} ({video_id})")
        update_video_status(video_id, "processing")
        
        # Get transcript
        transcript = fetch_transcript(video_id)
        if not transcript:
            logging.error(f"Could not fetch transcript for {video_id}. Marking as failed.")
            update_video_status(video_id, "failed")
            continue
            
        # Get LLM analysis
        logging.info("Analyzing transcript via Gemini...")
        insights, model_name = analyze_transcript(title, description, upload_date, transcript)
        
        if not insights:
            logging.error(f"LLM analysis failed for {video_id}. Marking as failed.")
            update_video_status(video_id, "failed")
            continue
            
        # Publish to Telegram
        logging.info("Publishing to Telegram channel...")
        site_url = os.environ.get("SITE_URL", "https://briannoelkesuma.github.io/ai_engineer_newsletter/public")
        final_message = (
            f"📺 <b>{title}</b>\n\n"
            f"{insights.telegram_summary_text}\n\n"
            f"📖 <a href=\"{site_url}/#video-{video_id}\">Read detailed timestamp breakdown</a>\n\n"
            f"🔗 https://youtube.com/watch?v={video_id}"
        )
        send_telegram_message(final_message)
        
        # Update status to processed
        update_video_status(video_id, "processed", model=model_name, telegram_summary_text=insights.telegram_summary_text, webpage_detailed_info_text=insights.webpage_detailed_info_text)
        processed_count += 1
        
        # Respect rate limits
        if idx < len(pending) - 1:
            logging.info("Sleeping for 65 seconds to respect API rate limits...")
            time.sleep(65)
            
    logging.info(f"Backfill complete! Rebuilt website with {processed_count} backfilled entries.")
    if processed_count > 0:
        build_site()

if __name__ == "__main__":
    run_backfill()
