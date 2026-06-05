import yt_dlp
from datetime import datetime, timedelta

CHANNEL_URL = "https://www.youtube.com/@aiDotEngineer/videos"
DAYS_BACK = 6

date_limit_str = (datetime.now() - timedelta(days=DAYS_BACK)).strftime('%Y%m%d')

ydl_opts = {
    'quiet': True,
    'skip_download': True,
    'extract_flat': True
}

print(f"Fetching recent videos from channel... (Limit date: {date_limit_str})")

with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    info = ydl.extract_info(CHANNEL_URL, download=False)
    if 'entries' in info:
        for idx, entry in enumerate(info['entries']):
            vid_id = entry.get('id')
            title = entry.get('title')
            
            # Since extract_flat is True, we need to fetch full metadata for each video to get the upload date
            # To be fast, let's just inspect the first 20 videos.
            if idx >= 20:
                break
                
            try:
                with yt_dlp.YoutubeDL({'quiet': True, 'skip_download': True}) as ydl_single:
                    vid_info = ydl_single.extract_info(f"https://www.youtube.com/watch?v={vid_id}", download=False)
                    upload_date = vid_info.get("upload_date")
                    print(f"- Title: {title} | ID: {vid_id} | Upload Date: {upload_date}")
            except Exception as e:
                print(f"Error fetching {vid_id}: {e}")
