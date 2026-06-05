from youtube_transcript_api import YouTubeTranscriptApi
import logging

def fetch_transcript(video_id: str) -> str:
    """
    Fetches the transcript for a given YouTube video ID.
    Returns a single string with the full transcript, or an empty string if it fails.
    """
    import os
    os.makedirs("transcripts", exist_ok=True)
    local_path = f"transcripts/{video_id}.txt"
    if os.path.exists(local_path):
        logging.info(f"Using local transcript file for {video_id}")
        with open(local_path, "r") as f:
            return f.read()

    try:
        import subprocess
        import json
        import os
        
        import sys
        
        proxy = os.environ.get("YOUTUBE_PROXY")
        cmd = [
            sys.executable,
            "-m", "yt_dlp",
            "--write-auto-sub",
            "--skip-download",
            "--sub-format", "json3",
            "--quiet"
        ]
        if proxy:
            cmd.extend(["--proxy", proxy])
        cmd.extend([
            f"https://www.youtube.com/watch?v={video_id}",
            "-o", f"transcripts/{video_id}.%(ext)s"
        ])
        subprocess.run(cmd, check=True)
        
        json3_path = f"transcripts/{video_id}.en.json3"
        if not os.path.exists(json3_path):
            logging.error(f"yt-dlp did not generate {json3_path}")
            return ""
            
        with open(json3_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        # Parse JSON3 segments
        segments = []
        for ev in data.get('events', []):
            for seg in ev.get('segs', []):
                if 'utf8' in seg:
                    segments.append(seg['utf8'])
                    
        full_transcript = "".join(segments).replace('\\n', ' ').strip()
        
        # Cleanup
        try:
            os.remove(json3_path)
            # also remove .vtt if it was downloaded previously
            vtt_path = f"transcripts/{video_id}.en.vtt"
            if os.path.exists(vtt_path):
                os.remove(vtt_path)
        except:
            pass
            
        return full_transcript
    except Exception as e:
        logging.error(f"Failed to fetch transcript using yt-dlp for {video_id}: {e}")
        return ""

if __name__ == "__main__":
    # Test with a known video id
    pass
