import os
import sys
import logging

# Add parent directory to path so we can import our modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from transcript_fetcher import fetch_transcript
from llm_analyzer import analyze_transcript

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def test_video(video_id: str):
    logging.info(f"Testing pipeline for video ID: {video_id}")
    
    # 1. Fetch transcript
    logging.info("Fetching transcript...")
    transcript = fetch_transcript(video_id)
    if not transcript:
        logging.error("Failed to fetch transcript.")
        return
        
    logging.info(f"Successfully fetched transcript ({len(transcript)} chars).")
    
    # 2. Run LLM Analysis
    logging.info("Running LLM analysis (Llama 3.3 70B)...")
    try:
        insights, model_used = analyze_transcript(
            title="Test Video Title",
            description="Test Description",
            upload_date="2026-06-05",
            transcript=transcript
        )
        
        if insights:
            print("\n" + "="*50)
            print(f"SUCCESS! Model Used: {model_used}")
            print("="*50)
            print("GENERATED NEWSLETTER TEXT:")
            print("-"*50)
            print(insights.newsletter_text)
            print("="*50 + "\n")
        else:
            logging.error("LLM Analysis returned None.")
    except Exception as e:
        logging.error(f"Error during analysis: {e}")

if __name__ == "__main__":
    # Using one of the recent AI Engineer videos
    test_video("V-L0INGTEOg")
