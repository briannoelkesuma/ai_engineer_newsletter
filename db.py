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
    response = supabase.table("videos").select("*").eq("status", "pending").order("upload_date", desc=False).execute()
    return response.data

def add_video(video_id: str, title: str, description: str, upload_date: str):
    supabase = get_db_client()
    data = {
        "video_id": video_id,
        "title": title,
        "description": description,
        "upload_date": upload_date,
        "status": "pending"
    }
    response = supabase.table("videos").upsert(data, ignore_duplicates=True).execute()
    return response.data

def update_video_status(video_id: str, status: str, model: str = None):
    supabase = get_db_client()
    data = {"status": status}
    if model:
        data["model"] = model
    response = supabase.table("videos").update(data).eq("video_id", video_id).execute()
    return response.data

def insert_insights(video_id: str, newsletter_text: str):
    supabase = get_db_client()
    data = {
        "video_id": video_id,
        "newsletter_text": newsletter_text
    }
    response = supabase.table("insights").upsert(data).execute()
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
