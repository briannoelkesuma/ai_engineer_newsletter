import os
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

url: str = os.environ.get("SUPABASE_URL", "")
key: str = os.environ.get("SUPABASE_KEY", "")

def get_db_client() -> Client:
    return create_client(url, key)

def get_pending_videos():
    supabase = get_db_client()
    response = supabase.table("videos").select("*").eq("status", "pending").order("created_at", desc=False).execute()
    return response.data

def add_video(video_id: str, title: str):
    supabase = get_db_client()
    data = {
        "video_id": video_id,
        "title": title,
        "status": "pending"
    }
    response = supabase.table("videos").upsert(data, ignore_duplicates=True).execute()
    return response.data

def update_video_status(video_id: str, status: str, model: str = None, telegram_summary_text: str = None, webpage_detailed_info_text: str = None):
    supabase = get_db_client()
    data = {"status": status}
    if model:
        data["model"] = model
    if telegram_summary_text:
        data["telegram_summary_text"] = telegram_summary_text
    if webpage_detailed_info_text:
        data["webpage_detailed_info_text"] = webpage_detailed_info_text
    response = supabase.table("videos").update(data).eq("video_id", video_id).execute()
    return response.data

def reset_stuck_videos():
    """
    Self-healing: If a video has been 'processing' for a while (e.g. script crashed),
    reset it to 'pending' so it can be picked up again.
    (Note: Supabase doesn't easily let us check exactly when it entered 'processing' 
    without a specific timestamp column, so we'll just reset ALL processing videos 
    on startup, assuming this script is the only thing running).
    """
    supabase = get_db_client()
    # Reset all currently 'processing' videos to 'pending'
    response = supabase.table("videos").update({"status": "pending"}).eq("status", "processing").execute()
    count = len(response.data) if response.data else 0
    if count > 0:
        logging.info(f"Self-Healing: Reset {count} stuck videos from 'processing' to 'pending'.")
    return count

def reset_failed_videos_for_daily_retry():
    """
    Reset videos that failed more than 20 hours ago back to 'pending'
    so they can be retried the next day.
    """
    from datetime import timezone
    supabase = get_db_client()
    try:
        res = supabase.table("videos").select("*").eq("status", "failed").execute()
        failed_videos = res.data or []
        now = datetime.now(timezone.utc)
        reset_count = 0
        for vid in failed_videos:
            created_at_str = vid.get("created_at")
            if created_at_str:
                try:
                    created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                    if now - created_at > timedelta(hours=20):
                        supabase.table("videos").update({"status": "pending", "model": None}).eq("video_id", vid["video_id"]).execute()
                        reset_count += 1
                except Exception as e:
                    logging.warning(f"Failed to parse created_at for daily retry check: {e}")
        if reset_count > 0:
            logging.info(f"Daily Retry: Reset {reset_count} failed videos back to 'pending' for next-day retry.")
        return reset_count
    except Exception as e:
        logging.error(f"Error resetting failed videos for daily retry: {e}")
        return 0
