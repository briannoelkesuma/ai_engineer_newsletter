import os
import logging
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

def get_db_client() -> Client:
    url: str = os.environ.get("SUPABASE_URL", "")
    key: str = os.environ.get("SUPABASE_KEY", "")
    return create_client(url, key)

def get_pending_videos():
    supabase = get_db_client()
    response = supabase.table("videos").select("*").eq("status", "pending").order("created_at", desc=False).execute()
    return response.data or []

def add_video(video_id: str, title: str):
    supabase = get_db_client()
    data = {
        "video_id": video_id,
        "title": title,
        "status": "pending"
    }
    response = supabase.table("videos").upsert(data, on_conflict="video_id", ignore_duplicates=True).execute()
    return response.data

def add_videos_batch(video_list: list[dict]):
    """
    Inserts a list of videos in a single batch call.
    Ignores duplicates so existing processed/pending videos are untouched.
    """
    if not video_list:
        return []
    supabase = get_db_client()
    data = [
        {
            "video_id": v["id"],
            "title": v.get("title", "Triggered Video"),
            "status": "pending"
        }
        for v in video_list if v.get("id")
    ]
    if not data:
        return []
    try:
        response = supabase.table("videos").upsert(data, on_conflict="video_id", ignore_duplicates=True).execute()
        return response.data or []
    except Exception as e:
        logging.error(f"Error in add_videos_batch: {e}")
        # Fallback to individual inserts if batch fails
        inserted = []
        for item in data:
            try:
                res = supabase.table("videos").upsert(item, on_conflict="video_id", ignore_duplicates=True).execute()
                if res.data:
                    inserted.extend(res.data)
            except Exception as single_err:
                logging.warning(f"Error adding single video {item.get('video_id')}: {single_err}")
        return inserted

def update_video_status(video_id: str, status: str, model: str = None, telegram_summary_text: str = None, webpage_detailed_info_text: str = None, title: str = None):
    supabase = get_db_client()
    data = {"status": status}
    if title:
        data["title"] = title
    if model is not None:
        data["model"] = model
    if telegram_summary_text is not None:
        data["telegram_summary_text"] = telegram_summary_text
    if webpage_detailed_info_text is not None:
        data["webpage_detailed_info_text"] = webpage_detailed_info_text
    response = supabase.table("videos").update(data).eq("video_id", video_id).execute()
    return response.data

def get_processed_videos(limit: int = 100):
    supabase = get_db_client()
    response = supabase.table("videos").select("*").eq("status", "processed").order("created_at", desc=True).limit(limit).execute()
    return response.data or []

def reset_stuck_videos():
    """
    Self-healing: If a video has been 'processing' for a while (e.g. script crashed),
    reset it to 'pending' so it can be picked up again.
    """
    supabase = get_db_client()
    response = supabase.table("videos").update({"status": "pending"}).eq("status", "processing").execute()
    count = len(response.data) if response.data else 0
    if count > 0:
        logging.info(f"Self-Healing: Reset {count} stuck videos from 'processing' to 'pending'.")
    return count

def reset_failed_videos_for_daily_retry():
    """
    Reset videos that failed within the last 3 days back to 'pending' for a single retry.
    Ignores older failures to prevent infinite retry loops on non-transcribable videos.
    """
    supabase = get_db_client()
    try:
        res = supabase.table("videos").select("*").eq("status", "failed").execute()
        failed_videos = res.data or []
        now = datetime.now(timezone.utc)
        reset_count = 0
        for vid in failed_videos:
            created_at_str = vid.get("created_at")
            if not created_at_str:
                continue
            try:
                created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                age = now - created_at
                # Only retry videos failed between 12 hours and 3 days ago, and not marked max_retried
                if timedelta(hours=12) < age <= timedelta(days=3) and vid.get("model") != "failed_permanently":
                    supabase.table("videos").update({
                        "status": "pending", 
                        "model": "retrying_after_failure"
                    }).eq("video_id", vid["video_id"]).execute()
                    reset_count += 1
                elif age > timedelta(days=3):
                    # Mark permanently failed so it's not checked again
                    supabase.table("videos").update({"model": "failed_permanently"}).eq("video_id", vid["video_id"]).execute()
            except Exception as e:
                logging.warning(f"Failed to parse created_at for daily retry check: {e}")
                
        if reset_count > 0:
            logging.info(f"Daily Retry: Reset {reset_count} recently failed videos back to 'pending' for retry.")
        return reset_count
    except Exception as e:
        logging.error(f"Error resetting failed videos for daily retry: {e}")
        return 0

