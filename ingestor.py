import os
import random
import logging
from datetime import datetime, timedelta
import yt_dlp

def get_recent_videos(channel_url: str, days_back: int = 14):
    """
    Fetches videos from the past `days_back` days.
    Returns a list of dicts: [{'id': ..., 'title': ..., 'description': ..., 'upload_date': ...}]
    Filters out upcoming premieres and live broadcasts that have not finished.
    """
    date_limit_str = (datetime.now() - timedelta(days=days_back)).strftime('%Y%m%d')
    
    ydl_opts = {
        'extract_flat': True,
        'quiet': True,
        'daterange': yt_dlp.utils.DateRange(date_limit_str, '99991231'), 
        'playlistend': 20
    }
    
    proxy_env = os.environ.get("YOUTUBE_PROXY")
    if proxy_env:
        proxies = [p.strip() for p in proxy_env.split(",") if p.strip()]
        proxy = random.choice(proxies) if proxies else None
        if proxy:
            ydl_opts['proxy'] = proxy

    videos = []
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(channel_url, download=False)
            if 'entries' in info:
                for entry in info['entries']:
                    if not entry or not entry.get('id'):
                        continue
                    
                    # Skip upcoming premieres and active live streams
                    live_status = entry.get('live_status')
                    if live_status in ['is_upcoming', 'is_live', 'post_live_recording']:
                        logging.info(f"Skipping upcoming/live video {entry.get('id')} ({entry.get('title')}) with status: {live_status}")
                        continue
                    
                    title = entry.get('title', '')
                    if "premiere" in title.lower() and "live" in title.lower():
                        continue

                    videos.append({
                        'id': entry.get('id'),
                        'title': title,
                        'description': entry.get('description', ''),
                        'upload_date': entry.get('upload_date') # Format: YYYYMMDD if available
                    })
    except Exception as e:
        logging.error(f"Error fetching channel data with proxy: {e}. Retrying with direct connection...")
        # Direct fallback without proxy
        ydl_opts.pop('proxy', None)
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(channel_url, download=False)
                if 'entries' in info:
                    for entry in info['entries']:
                        if not entry or not entry.get('id'):
                            continue
                        live_status = entry.get('live_status')
                        if live_status in ['is_upcoming', 'is_live']:
                            continue
                        videos.append({
                            'id': entry.get('id'),
                            'title': entry.get('title', ''),
                            'description': entry.get('description', ''),
                            'upload_date': entry.get('upload_date')
                        })
        except Exception as err:
            logging.error(f"Error fetching channel data directly: {err}")
            
    return videos
