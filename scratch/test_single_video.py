import os
import sys
import logging

# Add parent directory to path so we can import our modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from transcript_fetcher import fetch_transcript
from llm_analyzer import analyze_transcript

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def test_video(video_id: str, model: str = None):
    logging.info(f"Testing pipeline for video ID: {video_id}")
    
    # 1. Fetch transcript
    logging.info("Fetching transcript...")
    transcript = fetch_transcript(video_id)
    if not transcript:
        logging.error("Failed to fetch transcript.")
        return
        
    logging.info(f"Successfully fetched transcript ({len(transcript)} chars).")
    
    # 2. Run LLM Analysis
    logging.info("Running LLM analysis...")
    try:
        insights, model_used = analyze_transcript(
            title="Test Video Title",
            description="Test Description",
            upload_date="2026-06-05",
            transcript=transcript,
            model=model if model else "meta-llama/llama-3.3-70b-instruct:free"
        )
        
        if insights:
            print("\n" + "="*50)
            print(f"SUCCESS! Model Used: {model_used}")
            print("="*50)
            print("TELEGRAM SUMMARY TEXT:")
            print("-"*50)
            print(insights.telegram_summary_text)
            print("-"*50)
            print("STATIC SITE WEBPAGE DETAILED INFO TEXT (DETAILED):")
            print("-"*50)
            print(insights.webpage_detailed_info_text)
            print("="*50 + "\n")
        else:
            logging.error("LLM Analysis returned None.")
    except Exception as e:
        logging.error(f"Error during analysis: {e}")

if __name__ == "__main__":
    # Use provided video ID or default to the example video
    video_id = sys.argv[1] if len(sys.argv) > 1 else "wcUJWP6WpGM"
    # Optional model name as second argument
    model_name = sys.argv[2] if len(sys.argv) > 2 else None
    test_video(video_id, model_name)
