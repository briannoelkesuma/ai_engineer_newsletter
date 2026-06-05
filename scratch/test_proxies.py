import os
import subprocess
import sys

proxies = [
    "http://xfvlbqlj:o7k5f90c1ssg@38.154.203.95:5863",
    "http://xfvlbqlj:o7k5f90c1ssg@198.105.121.200:6462",
    "http://xfvlbqlj:o7k5f90c1ssg@64.137.96.74:6641",
    "http://xfvlbqlj:o7k5f90c1ssg@209.127.138.10:5784",
    "http://xfvlbqlj:o7k5f90c1ssg@38.154.185.97:6370",
    "http://xfvlbqlj:o7k5f90c1ssg@84.247.60.125:6095",
    "http://xfvlbqlj:o7k5f90c1ssg@142.111.67.146:5611",
    "http://xfvlbqlj:o7k5f90c1ssg@191.96.254.138:6185",
    "http://xfvlbqlj:o7k5f90c1ssg@31.58.9.4:6077",
    "http://xfvlbqlj:o7k5f90c1ssg@104.239.107.47:5699"
]

video_id = "r305-aQTaU0"
url = f"https://www.youtube.com/watch?v={video_id}"

for idx, proxy in enumerate(proxies):
    print(f"\n--- Testing Proxy {idx+1}: {proxy} ---")
    cmd = [
        sys.executable,
        "-m", "yt_dlp",
        "--write-auto-sub",
        "--skip-download",
        "--sub-format", "json3",
        "--quiet",
        "--proxy", proxy,
        url,
        "-o", f"transcripts/test_{idx}.%(ext)s"
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("✅ Success!")
        # Clean up files
        try:
            os.remove(f"transcripts/test_{idx}.en.json3")
        except:
            pass
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed: {e.stderr.strip() or e.stdout.strip()}")
