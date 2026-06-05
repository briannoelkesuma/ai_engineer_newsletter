from db import get_db_client

supabase = get_db_client()
res = supabase.table("videos").select("video_id,title,status").execute()
for row in res.data:
    print(f"{row['video_id']}: {row['title']} ({row['status']})")
