import os
import hmac
import hashlib
import requests
from dotenv import load_dotenv

load_dotenv()

CALLBACK_URL = "https://youtube-websub-worker.2612brian.workers.dev"
SECRET = os.environ.get("WEBHOOK_SECRET", "")
VIDEO_ID = "wcUJWP6WpGM"
TITLE = "SWE-rebench: Lessons from Evaluating Coding Agents — Ibragim Badertdinov, Nebius"
CHANNEL_ID = "UCLKPca3kwwd-B59HNr-_lvA"

if not SECRET:
    print("Error: WEBHOOK_SECRET not found in environment.")
    exit(1)

# XML payload matching YouTube WebSub format
xml_payload = f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015">
  <link rel="hub" href="http://pubsubhubbub.appspot.com"/>
  <link rel="self" href="https://www.youtube.com/xml/feeds/videos.xml?channel_id={CHANNEL_ID}"/>
  <title>YouTube video feed</title>
  <updated>2026-06-04T15:00:00+00:00</updated>
  <entry>
    <id>yt:video:{VIDEO_ID}</id>
    <yt:videoId>{VIDEO_ID}</yt:videoId>
    <yt:channelId>{CHANNEL_ID}</yt:channelId>
    <title>{TITLE}</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v={VIDEO_ID}"/>
    <author>
      <name>AI Engineer</name>
      <uri>https://www.youtube.com/channel/{CHANNEL_ID}</uri>
    </author>
    <published>2026-06-04T15:00:00+00:00</published>
    <updated>2026-06-04T15:00:00+00:00</updated>
  </entry>
</feed>
"""

# Calculate HMAC-SHA1 signature
hashed = hmac.new(SECRET.encode('utf-8'), xml_payload.encode('utf-8'), hashlib.sha1)
signature = f"sha1={hashed.hexdigest()}"

print(f"Sending mock WebSub webhook notification for video: {VIDEO_ID}")
print(f"Callback URL: {CALLBACK_URL}")
print(f"X-Hub-Signature: {signature}\n")

headers = {
    "Content-Type": "application/atom+xml",
    "x-hub-signature": signature
}

try:
    response = requests.post(CALLBACK_URL, data=xml_payload, headers=headers)
    print(f"Response Status Code: {response.status_code}")
    print(f"Response Body: {response.text}")
except Exception as e:
    print(f"Failed to send request: {e}")
