import os
import json
import logging
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import VideoUnplayable, TranscriptsDisabled, NoTranscriptFound

class VideoUpcomingException(Exception):
    """Raised when a video has not premiered yet."""
    pass

def fetch_transcript(video_id: str) -> str:
    """
    Fetches the transcript for a given YouTube video ID.
    Returns a single string with the full transcript, or an empty string if it fails.
    Raises VideoUpcomingException if the video is an upcoming premiere/live stream.
    """
    os.makedirs("transcripts", exist_ok=True)
    local_path = f"transcripts/{video_id}.txt"
    if os.path.exists(local_path):
        logging.info(f"Using local transcript file for {video_id}")
        with open(local_path, "r", encoding="utf-8") as f:
            return f.read()

    # 1. Try native YouTubeTranscriptApi (fastest & most reliable)
    try:
        logging.info(f"Fetching transcript via YouTubeTranscriptApi for {video_id}...")
        api = YouTubeTranscriptApi()
        transcript_data = api.fetch(video_id)
        full_transcript = " ".join([item.text for item in transcript_data if hasattr(item, 'text') or isinstance(item, dict)])
        if not full_transcript and transcript_data:
            full_transcript = " ".join([item.get('text', '') if isinstance(item, dict) else str(item) for item in transcript_data])
            
        if full_transcript.strip():
            logging.info(f"Successfully fetched transcript via YouTubeTranscriptApi ({len(full_transcript)} chars)")
            with open(local_path, "w", encoding="utf-8") as f:
                f.write(full_transcript)
            return full_transcript
    except VideoUnplayable as e:
        err_msg = str(e)
        if "premieres" in err_msg.lower() or "upcoming" in err_msg.lower() or "live" in err_msg.lower():
            logging.warning(f"Video {video_id} is an upcoming premiere / live stream: {err_msg}")
            raise VideoUpcomingException(f"Video {video_id} is upcoming: {err_msg}")
        logging.warning(f"YouTubeTranscriptApi unplayable for {video_id}: {e}")
    except (TranscriptsDisabled, NoTranscriptFound) as e:
        logging.warning(f"YouTubeTranscriptApi: No transcript available for {video_id}: {e}")
    except Exception as e:
        logging.warning(f"YouTubeTranscriptApi failed for {video_id}: {e}. Trying public API / yt-dlp...")

    # 2. Try public API fallback
    try:
        import urllib.request
        logging.info(f"Attempting to fetch transcript from public API for {video_id}...")
        url = f"https://youtube-transcript.ai/transcript/{video_id}.txt"
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                content = response.read().decode('utf-8')
                if content.strip() and "not found" not in content.lower() and "<html" not in content.lower():
                    logging.info(f"Successfully fetched transcript from public API for {video_id}")
                    with open(local_path, "w", encoding="utf-8") as f:
                        f.write(content)
                    return content
    except Exception as e:
        logging.warning(f"Public API fetch failed for {video_id}: {e}. Falling back to yt-dlp...")

    # 3. Try yt-dlp fallback (first with direct connection, then optional proxy)
    try:
        import subprocess
        import sys
        
        cmd = [
            sys.executable,
            "-m", "yt_dlp",
            "--write-auto-sub",
            "--skip-download",
            "--sub-format", "json3",
            "--quiet",
            f"https://www.youtube.com/watch?v={video_id}",
            "-o", f"transcripts/{video_id}.%(ext)s"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            if "premieres" in result.stderr.lower() or "upcoming" in result.stderr.lower():
                raise VideoUpcomingException(f"Video {video_id} is upcoming premiere: {result.stderr}")
            logging.error(f"yt-dlp failed for {video_id}: {result.stderr}")
            return ""
            
        json3_path = f"transcripts/{video_id}.en.json3"
        if not os.path.exists(json3_path):
            # Check for other language codes e.g. en-US, en-orig
            import glob
            matches = glob.glob(f"transcripts/{video_id}.*.json3")
            if matches:
                json3_path = matches[0]
            else:
                logging.error(f"yt-dlp did not generate json3 transcript for {video_id}")
                return ""
            
        with open(json3_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        segments = []
        for ev in data.get('events', []):
            for seg in ev.get('segs', []):
                if 'utf8' in seg:
                    segments.append(seg['utf8'])
                    
        full_transcript = "".join(segments).replace('\\n', ' ').strip()
        
        # Cleanup temporary files
        try:
            os.remove(json3_path)
        except Exception:
            pass
            
        if full_transcript:
            with open(local_path, "w", encoding="utf-8") as f:
                f.write(full_transcript)
        return full_transcript
    except VideoUpcomingException:
        raise
    except Exception as e:
        logging.error(f"Failed to fetch transcript using yt-dlp for {video_id}: {e}")
        return ""

if __name__ == "__main__":
    pass
