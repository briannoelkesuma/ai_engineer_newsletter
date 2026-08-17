import sys
import os
import logging
import time
from datetime import datetime, timedelta
from ingestor import get_recent_videos
from transcript_fetcher import fetch_transcript, VideoUpcomingException
from llm_analyzer import analyze_transcript
from telegram_bot import send_telegram_message, send_admin_alert
from db import (
    add_video,
    add_videos_batch,
    get_pending_videos,
    update_video_status,
    reset_stuck_videos,
    get_db_client,
    reset_failed_videos_for_daily_retry
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

CHANNEL_URL = "https://www.youtube.com/@aiDotEngineer/videos"
DAYS_BACK = 14

def format_date(date_str):
    if not date_str or len(date_str) != 8:
        return "Unknown Date"
    # Format YYYYMMDD to YYYY-MM-DD
    return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"

def is_within_days_back(raw_upload_date: str, days_back: int = DAYS_BACK) -> bool:
    if not raw_upload_date or len(raw_upload_date) != 8:
        return True # If unknown, allow through for safety
    try:
        upload_dt = datetime.strptime(raw_upload_date, "%Y%m%d")
        cutoff = datetime.now() - timedelta(days=days_back)
        return upload_dt >= cutoff
    except Exception:
        return True

def fetch_youtube_metadata_fallback(video_id: str) -> dict:
    import urllib.request
    import re
    url = f"https://www.youtube.com/watch?v={video_id}"
    req = urllib.request.Request(
        url, 
        headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8', errors='ignore')
            
            # 1. Parse Title
            title_match = re.search(r'<meta name="title" content="([^"]+)"', html)
            if not title_match:
                title_match = re.search(r'<meta property="og:title" content="([^"]+)"', html)
            title = title_match.group(1) if title_match else "Triggered Video"
            
            # 2. Parse Description
            desc_match = re.search(r'<meta name="description" content="([^"]+)"', html)
            if not desc_match:
                desc_match = re.search(r'<meta property="og:description" content="([^"]+)"', html)
            description = desc_match.group(1) if desc_match else ""
            
            # 3. Parse Upload Date
            date_match = re.search(r'itemprop="uploadDate" content="([^"T]+)', html)
            if not date_match:
                date_match = re.search(r'itemprop="datePublished" content="([^"T]+)', html)
            # Format: YYYY-MM-DD -> YYYYMMDD
            upload_date = date_match.group(1).replace("-", "") if date_match else None
            
            return {
                "title": title,
                "description": description,
                "upload_date": upload_date
            }
    except Exception as e:
        logging.warning(f"Fallback metadata fetch failed for {video_id}: {e}")
    return {}

def run_pipeline(target_video_id=None):
    logging.info("Starting ingestion pipeline...")
    
    # Self-Healing: Reset stuck processing videos and failed videos for daily retry (only on batch runs)
    if not target_video_id:
        reset_stuck_videos()
        reset_failed_videos_for_daily_retry()
    
    if target_video_id:
        logging.info(f"Triggered for specific video ID: {target_video_id}")
        add_video(target_video_id, "Triggered Video")
    else:
        recent_videos = get_recent_videos(CHANNEL_URL, DAYS_BACK)
        if recent_videos:
            add_videos_batch(recent_videos)
        
    pending_videos = get_pending_videos()
    
    if target_video_id:
        pending_videos = [v for v in pending_videos if v['video_id'] == target_video_id]
        
    logging.info(f"Found {len(pending_videos)} pending videos in database.")
    
    if pending_videos:
        logging.info(f"Processing batch of {len(pending_videos)} videos in this run.")
    
    processed_count = 0
    failed_count = 0
    
    for idx, p_vid in enumerate(pending_videos):
        video_id = p_vid['video_id']
        title = p_vid.get('title', 'Triggered Video')
        description = ""
        raw_upload_date = None
        
        # Fetch full metadata from YouTube for LLM context
        try:
            import yt_dlp
            logging.info(f"Fetching full metadata for {video_id} via yt-dlp...")
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
                raw_upload_date = info.get("upload_date")
                description = info.get("description", "")
                
                # Check live/premiere status
                live_status = info.get("live_status")
                if live_status in ["is_upcoming", "is_live"]:
                    logging.info(f"Video {video_id} is upcoming ({live_status}). Postponing.")
                    update_video_status(video_id, "upcoming", title=info.get("title", title))
                    continue

                if title in ["Triggered Video", "YouTube video feed"] or not title:
                    fetched_title = info.get("title")
                    if fetched_title:
                        title = fetched_title
                        update_video_status(video_id, "pending", title=fetched_title)
        except Exception as e:
            logging.warning(f"Failed to fetch metadata for {video_id} via yt-dlp: {e}. Trying fallback HTML scraping...")
            fallback_meta = fetch_youtube_metadata_fallback(video_id)
            if fallback_meta:
                raw_upload_date = fallback_meta.get("upload_date")
                description = fallback_meta.get("description", "")
                if (title in ["Triggered Video", "YouTube video feed"] or not title) and fallback_meta.get("title"):
                    title = fallback_meta["title"]
                    update_video_status(video_id, "pending", title=title)
                
        # Verify date cutoff: ignore videos older than DAYS_BACK (unless target_video_id explicitly requested)
        if not target_video_id and raw_upload_date and not is_within_days_back(raw_upload_date, DAYS_BACK):
            logging.info(f"Skipping old video {video_id} uploaded on {raw_upload_date} (older than {DAYS_BACK} days).")
            update_video_status(video_id, "skipped_old", title=title)
            continue

        upload_date = format_date(raw_upload_date)
        
        logging.info(f"Processing video: {title} ({video_id})")
        update_video_status(video_id, "processing")
        
        try:
            transcript = fetch_transcript(video_id)
        except VideoUpcomingException as ue:
            logging.info(f"Postponing upcoming video {video_id}: {ue}")
            update_video_status(video_id, "upcoming", title=title)
            continue
        except Exception as e:
            logging.error(f"Error fetching transcript for {video_id}: {e}")
            transcript = ""

        if not transcript or not transcript.strip():
            logging.error(f"Could not fetch transcript for {video_id}. Marking as failed.")
            update_video_status(video_id, "failed")
            failed_count += 1
            continue
            
        logging.info("Sending to LLM...")
        insights, model_name = analyze_transcript(title, description, upload_date, transcript)
        
        if not insights:
            current_model_val = p_vid.get("model") or ""
            if current_model_val == "retry_1":
                next_model_val = "retry_2"
                next_status = "pending"
            elif current_model_val == "retry_2":
                next_model_val = "retry_3"
                next_status = "pending"
            elif current_model_val == "retry_3":
                next_model_val = "failed_permanently"
                next_status = "failed"
            else:
                next_model_val = "retry_1"
                next_status = "pending"
                
            if next_status == "pending":
                logging.error(f"LLM analysis failed for {video_id}. Reverting status to pending (attempt {next_model_val}) for retry.")
                update_video_status(video_id, "pending", model=next_model_val)
            else:
                logging.error(f"LLM analysis failed max retries for {video_id}. Marking as failed.")
                update_video_status(video_id, "failed", model="failed_permanently")
                
            failed_count += 1
            continue
            
        site_url = os.environ.get("SITE_URL", "https://briannoelkesuma.github.io/ai_engineer_newsletter/public")
        insights.telegram_summary_text = f"{insights.telegram_summary_text}\n\n📖 <a href=\"{site_url}/#video-{video_id}\">Read detailed timestamp breakdown</a>\n\n🔗 https://youtube.com/watch?v={video_id}"

        # 1. Update DB to 'processed' FIRST to guarantee idempotency and prevent duplicate re-sends
        update_video_status(
            video_id, 
            "processed", 
            model=model_name, 
            telegram_summary_text=insights.telegram_summary_text, 
            webpage_detailed_info_text=insights.webpage_detailed_info_text,
            title=title
        )
        processed_count += 1

        # 2. Dispatch to Telegram
        logging.info(f"Publishing to Telegram...")
        success = send_telegram_message(insights.telegram_summary_text, video_id=video_id)
        if success:
            logging.info(f"Successfully posted video {video_id} to Telegram.")
        
        # Throttling to respect OpenRouter API limits
        if idx < len(pending_videos) - 1:
            logging.info("Sleeping for 10 seconds between items...")
            time.sleep(10)
        
    logging.info("Pipeline run complete.")
    if processed_count > 0:
        try:
            from generate_static_site import build_site
            build_site()
        except Exception as site_err:
            logging.error(f"Error rebuilding static site: {site_err}")

if __name__ == "__main__":
    target_vid = sys.argv[1] if len(sys.argv) > 1 else None
    run_pipeline(target_vid)
