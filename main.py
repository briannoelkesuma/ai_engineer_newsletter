import sys
import os
import logging
import time
from ingestor import get_recent_videos
from transcript_fetcher import fetch_transcript
from llm_analyzer import analyze_transcript
from telegram_bot import send_telegram_message, send_admin_alert
from db import add_video, get_pending_videos, update_video_status, reset_stuck_videos, get_db_client

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

CHANNEL_URL = "https://www.youtube.com/@aiDotEngineer/videos"
DAYS_BACK = 14

def format_date(date_str):
    if not date_str or len(date_str) != 8:
        return "Unknown Date"
    # Format YYYYMMDD to YYYY-MM-DD
    return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"

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
    
    # Self-Healing: Reset stuck processing videos from prior crashed runs (only on batch runs)
    if not target_video_id:
        reset_stuck_videos()
    
    if target_video_id:
        logging.info(f"Triggered for specific video ID: {target_video_id}")
        add_video(target_video_id, "Triggered Video")
    else:
        recent_videos = get_recent_videos(CHANNEL_URL, DAYS_BACK)
        for vid in recent_videos:
            add_video(vid['id'], vid['title'])
        
    pending_videos = get_pending_videos()
    
    if target_video_id:
        pending_videos = [v for v in pending_videos if v['video_id'] == target_video_id]
        
    logging.info(f"Found {len(pending_videos)} pending videos in database.")
    
    # Process at most 3 videos per run to prevent IP blocks / rate limits
    # pending_videos = pending_videos[:3]
    if pending_videos:
        logging.info(f"Processing batch of {len(pending_videos)} videos in this run.")
    
    processed_count = 0
    failed_count = 0
    
    for p_vid in pending_videos:
        video_id = p_vid['video_id']
        title = p_vid['title']
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
                if title == "Triggered Video":
                    fetched_title = info.get("title")
                    if fetched_title:
                        title = fetched_title
                        supabase = get_db_client()
                        supabase.table("videos").update({"title": fetched_title}).eq("video_id", video_id).execute()
        except Exception as e:
            logging.warning(f"Failed to fetch metadata for {video_id} via yt-dlp: {e}. Trying fallback HTML scraping...")
            fallback_meta = fetch_youtube_metadata_fallback(video_id)
            if fallback_meta:
                raw_upload_date = fallback_meta.get("upload_date")
                description = fallback_meta.get("description", "")
                if title == "Triggered Video" and fallback_meta.get("title") and fallback_meta["title"] != "Triggered Video":
                    title = fallback_meta["title"]
                    supabase = get_db_client()
                    supabase.table("videos").update({"title": title}).eq("video_id", video_id).execute()
                
        upload_date = format_date(raw_upload_date)
        
        logging.info(f"Processing video: {title} ({video_id})")
        update_video_status(video_id, "processing")
        
        transcript = fetch_transcript(video_id)
        if not transcript:
            logging.error(f"Could not fetch transcript for {video_id}. Marking as failed.")
            update_video_status(video_id, "failed")
            failed_count += 1
            continue
            
        logging.info("Sending to LLM...")
        insights, model_name = analyze_transcript(title, description, upload_date, transcript)
        
        if not insights:
            logging.error(f"LLM analysis failed for {video_id}. Reverting status to pending for next run retry.")
            update_video_status(video_id, "pending")
            failed_count += 1
            continue
            
        site_url = os.environ.get("SITE_URL", "https://ai-engineer-newsletter.vercel.app")
        insights.telegram_summary_text = f"{insights.telegram_summary_text}\n\n📖 <a href=\"{site_url}/#video-{video_id}\">Read detailed timestamp breakdown</a>\n\n🔗 https://youtube.com/watch?v={video_id}"

        logging.info(f"Publishing to Telegram...")
        send_telegram_message(insights.telegram_summary_text)
        
        update_video_status(video_id, "processed", model=model_name, telegram_summary_text=insights.telegram_summary_text, webpage_detailed_info_text=insights.webpage_detailed_info_text)
        processed_count += 1
        
        # Throttling to respect OpenRouter API limits
        logging.info("Sleeping for 65 seconds to respect API rate limits...")
        time.sleep(65)
        
    logging.info("Pipeline run complete.")
    if processed_count > 0:
        from generate_static_site import build_site
        build_site()

if __name__ == "__main__":
    target_vid = sys.argv[1] if len(sys.argv) > 1 else None
    run_pipeline(target_vid)
