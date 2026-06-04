import sys
import logging
import time
from ingestor import get_recent_videos
from transcript_fetcher import fetch_transcript
from llm_analyzer import analyze_transcript
from telegram_bot import send_telegram_message, send_admin_alert
from db import add_video, get_pending_videos, update_video_status, insert_insights, reset_stuck_videos, get_db_client

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

CHANNEL_URL = "https://www.youtube.com/@aiDotEngineer/videos"
DAYS_BACK = 14

def format_date(date_str):
    if not date_str or len(date_str) != 8:
        return "Unknown Date"
    # Format YYYYMMDD to YYYY-MM-DD
    return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"

def run_pipeline(target_video_id=None):
    logging.info("Starting ingestion pipeline...")
    
    # Self-Healing: Reset stuck processing videos from prior crashed runs (only on batch runs)
    if not target_video_id:
        reset_stuck_videos()
    
    if target_video_id:
        logging.info(f"Triggered for specific video ID: {target_video_id}")
        add_video(target_video_id, "Triggered Video", "", "")
    else:
        recent_videos = get_recent_videos(CHANNEL_URL, DAYS_BACK)
        for vid in recent_videos:
            add_video(vid['id'], vid['title'], vid['description'], vid['upload_date'])
        
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
        description = p_vid['description'] or ""
        raw_upload_date = p_vid['upload_date']
        
        # If upload_date or description is missing, fetch them via yt-dlp
        if not raw_upload_date or not description:
            try:
                import yt_dlp
                logging.info(f"Fetching full metadata for {video_id} via yt-dlp...")
                ydl_opts = {'quiet': True, 'skip_download': True}
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
                    if not raw_upload_date:
                        raw_upload_date = info.get("upload_date")
                        if raw_upload_date:
                            update_video_status(video_id, "pending") # ensure we don't clear status
                            supabase = get_db_client()
                            supabase.table("videos").update({"upload_date": raw_upload_date}).eq("video_id", video_id).execute()
                    if not description:
                        description = info.get("description", "")
                        if description:
                            supabase = get_db_client()
                            supabase.table("videos").update({"description": description}).eq("video_id", video_id).execute()
            except Exception as e:
                logging.warning(f"Failed to fetch metadata for {video_id}: {e}")
                
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
            logging.error(f"LLM analysis failed for {video_id}. Marking as failed.")
            update_video_status(video_id, "failed")
            failed_count += 1
            continue
            
        insert_insights(
            video_id, 
            insights.newsletter_text
        )
        
        logging.info(f"Publishing to Telegram...")
        final_message = f"📺 <b>{title}</b>\n\n{insights.newsletter_text}\n\n🔗 https://youtube.com/watch?v={video_id}"
        send_telegram_message(final_message)
        
        update_video_status(video_id, "processed", model=model_name)
        processed_count += 1
        
        # Throttling to respect OpenRouter API limits
        logging.info("Sleeping for 65 seconds to respect API rate limits...")
        time.sleep(65)
        
    logging.info("Pipeline run complete.")
    if processed_count > 0 or failed_count > 0:
        send_admin_alert(f"Cron run complete.\n✅ Processed: {processed_count}\n❌ Failed: {failed_count}")
        
    if processed_count > 0:
        from generate_static_site import build_site
        build_site()

if __name__ == "__main__":
    target_vid = sys.argv[1] if len(sys.argv) > 1 else None
    run_pipeline(target_vid)
