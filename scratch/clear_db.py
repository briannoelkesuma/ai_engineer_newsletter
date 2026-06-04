import os
import sys
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

url = os.environ.get("SUPABASE_URL", "")
key = os.environ.get("SUPABASE_KEY", "")

if not url or not key:
    print("Error: SUPABASE_URL or SUPABASE_KEY not found in environment.")
    sys.exit(1)

supabase = create_client(url, key)

print("Clearing Supabase database...")

try:
    # Clear videos table
    print("Deleting from 'videos'...")
    res_videos = supabase.table("videos").delete().neq("video_id", "").execute()
    print(f"Deleted {len(res_videos.data) if res_videos.data else 0} videos rows.")

    print("Supabase database cleared successfully!")
except Exception as e:
    print(f"Error clearing database: {e}")
