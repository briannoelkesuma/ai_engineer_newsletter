import yt_dlp
from datetime import datetime, timedelta
import logging

def get_recent_videos(channel_url: str, days_back: int = 30):
    """
    Fetches videos from the past `days_back` days.
    Returns a list of dicts: [{'id': ..., 'title': ..., 'description': ..., 'upload_date': ...}]
    """
    date_limit_str = (datetime.now() - timedelta(days=days_back)).strftime('%Y%m%d')
    
    ydl_opts = {
        'extract_flat': True,
        'quiet': True,
        'daterange': yt_dlp.utils.DateRange(date_limit_str, '99991231'), 
        'playlistend': 50 
    }

    videos = []
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(channel_url, download=False)
            if 'entries' in info:
                for entry in info['entries']:
                    videos.append({
                        'id': entry.get('id'),
                        'title': entry.get('title'),
                        'description': entry.get('description', ''),
                        'upload_date': entry.get('upload_date') # Format: YYYYMMDD
                    })
        except Exception as e:
            logging.error(f"Error fetching channel data: {e}")
            
    return videos
