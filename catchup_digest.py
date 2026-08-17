import logging
from datetime import datetime, timezone
from dotenv import load_dotenv
from db import get_db_client, get_processed_videos
from llm_analyzer import ask_llm
from telegram_bot import send_telegram_message, send_digest_message
from pydantic import BaseModel, Field

load_dotenv()

class DigestInsights(BaseModel):
    summary: str = Field(
        default="",
        description="A cohesive executive catch-up briefing formatted in strict Telegram HTML (<b>, <i>, <code>, <a>). Group the unopened videos into key themes/takeaways, bulleted highlights per video with insights, and a 'Top 2 Recommended Videos to Deep Dive' section. Concise and non-intimidating."
    )
    executive_summary_html: str = Field(
        default="",
        description="Alternative key for the executive catch-up briefing formatted in strict Telegram HTML."
    )

    @property
    def digest_text(self) -> str:
        return self.summary or self.executive_summary_html



def get_unopened_videos(limit: int = 50) -> list[dict]:
    # Since get_processed_videos only fetches status='processed' and NOT 'read',
    # all returned videos are unopened.
    return get_processed_videos(limit=limit)

def generate_catchup_digest(max_videos: int = 30) -> str | None:
    """
    Synthesizes all unopened video summaries into an executive catch-up briefing.
    Marks them as read once successfully delivered to Telegram.
    """
    unopened = get_unopened_videos(limit=max_videos)
    
    if not unopened:
        msg = "🎉 <b>You're all caught up!</b>\n\nThere are no unopened video summaries waiting for you."
        logging.info("No unopened videos found.")
        return msg

    logging.info(f"Generating catch-up digest for {len(unopened)} unopened videos...")
    
    summaries_text = ""
    for idx, v in enumerate(unopened, 1):
        title = v.get("title", "Untitled Video")
        vid_id = v.get("video_id", "")
        summary = v.get("telegram_summary_text", "")
        # Strip trailing html link tags for clean prompt context
        clean_summary = summary.split("📖 <a href")[0].strip() if summary else "No summary available."
        summaries_text += f"\n\n--- VIDEO {idx}: {title} (ID: {vid_id}) ---\n{clean_summary}\n"

    prompt = f"""
You are an executive AI engineering intelligence advisor. The user has {len(unopened)} UNOPENED video summaries and feels intimidated by the backlog.
Create a high-impact, easy-to-read "Executive Catch-Up Digest" synthesizing all these unopened items into a single digestible Telegram newsletter.

Structure the HTML response strictly using Telegram HTML tags (<b>, <i>, <code>, <a>):

1. <b>⚡ Executive Catch-Up Brief ({len(unopened)} Unopened Updates)</b>
2. <b>🧠 Major Meta-Trends & Patterns</b> (2-3 concise bullet points identifying recurring themes across these talks)
3. <b>📌 Key Video Takeaways</b> (One punchy bullet per talk: <b>[Video Title]</b>: Core innovation/decision + why it matters + <a href="https://youtube.com/watch?v=[ID]">Watch</a>)
4. <b>🎯 Top 2 Must-Read Deep Dives</b> (Pick the 2 highest-value videos from the list and explain why the user should check them first).

Formatting rules:
- Strict Telegram HTML only (<b>, <i>, <code>, <pre>, <a>).
- NO markdown asterisks (**) or raw markdown headers (###).
- Keep total length concise (~300-500 words) so it is fast and rewarding to read.

Here are the unopened video summaries:
{summaries_text}
"""
    insights = None
    fallback_models = [
        "google/gemma-4-26b-a4b-it:free",
        "google/gemma-4-31b-it:free",
        "nvidia/nemotron-3-super-120b-a12b:free",
        "openrouter/free"
    ]
    
    for model in fallback_models:
        try:
            logging.info(f"Calling LLM for digest with model {model}...")
            insights = ask_llm(prompt, DigestInsights, model=model)
            if insights and insights.digest_text:
                break
        except Exception as e:
            logging.warning(f"Digest LLM generation failed with {model}: {e}")

    if not insights or not insights.digest_text:
        logging.error("Failed to generate catch-up digest via LLM.")
        return None

    digest_message = insights.digest_text
    
    # Send to Telegram (routes to digest topic if configured)
    send_digest_message(digest_message)
    
    # Mark videos as read in database
    from db import update_video_status
    for v in unopened:
        if v.get("video_id"):
            update_video_status(v.get("video_id"), "read")
    
    logging.info(f"Successfully sent catch-up digest for {len(unopened)} videos and updated state.")
    return digest_message

def mark_all_as_read():
    all_processed = get_processed_videos(limit=200)
    from db import update_video_status
    count = 0
    for v in all_processed:
        if v.get("video_id"):
            update_video_status(v.get("video_id"), "read")
            count += 1
    return count

if __name__ == "__main__":
    generate_catchup_digest()
