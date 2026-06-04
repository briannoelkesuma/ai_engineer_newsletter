import os
import json
import logging
from openai import OpenAI
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from openai import NotFoundError
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception
import tiktoken

load_dotenv()

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

client = OpenAI(
  base_url="https://openrouter.ai/api/v1",
  api_key=OPENROUTER_API_KEY,
  max_retries=0,
)

class VideoInsights(BaseModel):
    newsletter_text: str = Field(description="A fully detailed technical newsletter in Telegram HTML format (using only HTML tags: <b>bold</b>, <i>italic</i>, <code>inline code</code>, <pre>code block</pre>, and <a href='url'>links</a>). Act as an elite technical tutor who explains every key concept, architectural pattern, code logic, or framework in granular detail. Summarize the video sequentially for EACH timestamp/section in full detail so that readers learn everything without watching the video. Do NOT include the video date or video link (they are appended programmatically). Do NOT include meta-commentary, notes about missing URLs/slides, or footnotes.")

def is_retryable_exception(exception: Exception) -> bool:
    if isinstance(exception, NotFoundError):
        return False
    # Check for HTTP status codes that shouldn't be retried
    if hasattr(exception, "status_code") and exception.status_code in (400, 401, 402, 403, 404):
        return False
    return True

# Retry logic for 429 Too Many Requests (Rate Limits)
@retry(
    wait=wait_exponential(multiplier=2, min=15, max=120), 
    stop=stop_after_attempt(6),
    retry=retry_if_exception(is_retryable_exception),
    before_sleep=lambda retry_state: logging.warning(f"Rate limited or API error. Retrying in {retry_state.next_action.sleep} seconds...")
)
def ask_llm(prompt: str, schema: type[BaseModel], model: str = "google/gemini-2.5-flash:free") -> BaseModel:
    logging.info(f"Attempting LLM call with model: {model}")
    
    # We use a simplified template guide instead of the raw JSON schema because small models
    # can get confused and output the schema structure itself rather than filling fields.
    system_content = """You are an expert AI Engineer and technical tutor. You must output a JSON object with the following exact key:
- "newsletter_text": A fully detailed technical newsletter in Telegram HTML format. Act as an elite technical tutor who explains every key concept, architectural pattern, code logic, or framework in granular detail. You must structure the newsletter by providing a detailed summary for EACH timestamp/section of the video sequentially so that readers learn everything without watching the video. Do NOT include the video date or video link. Do NOT include meta-commentary, notes about missing URLs/slides, or footnotes. CRITICAL FORMATTING RULE: Telegram HTML parse mode is strict. DO NOT use block HTML tags like <p>, <br>, <ul>, <li>, <html>, or <body>. Only use <b>, <i>, <code>, <pre>, and <a>. Use double newlines (\\n\\n) for paragraph breaks and simple dashes (-) for bullet points.

You must output ONLY a valid JSON object matching this structure:
{
  "newsletter_text": "..."
}"""

    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_content},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
        max_tokens=8192
    )
    content = completion.choices[0].message.content or ""
    
    # Strip potential markdown code block wrappers
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()
    
    try:
        return schema.model_validate_json(content)
    except Exception as e:
        logging.error(f"JSON validation failed: {e}\nContent was: {content[:1000]}...")
        raise

def count_tokens(text: str) -> int:
    try:
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except Exception:
        # Fallback estimation
        return len(text) // 4

def analyze_transcript(title: str, description: str, upload_date: str, transcript: str, model: str = "google/gemini-2.5-flash:free") -> tuple[VideoInsights | None, str]:
    if not OPENROUTER_API_KEY:
        logging.error("OpenRouter API key missing.")
        return None, model
        
    token_count = count_tokens(transcript)
    logging.info(f"Transcript estimated token count: {token_count}")
    logging.info(f"Using single-pass analysis (model: {model}).")
    
    prompt = f"""
Video Title: {title}
Video Description: {description}

Your task is to provide a comprehensive explanation and write detailed, granular technical 'Deep Dive' teachings.
Synthesize a Telegram Newsletter in HTML format containing all this information in full detail.
Do not truncate; provide detailed technical coverage of EACH timestamp/section sequentially so that readers learn everything without watching the video.
Do NOT include the video date or link in the newsletter text itself. Do NOT include meta-commentary, notes about missing URLs/slides, or footnotes.
CRITICAL FORMATTING RULE: Telegram HTML parse mode is strict. DO NOT use block HTML tags like <p>, <br>, <ul>, <li>, <html>, or <body>. Only use <b>, <i>, <code>, <pre>, and <a>. Use double newlines (\\n\\n) for paragraph breaks and simple dashes (-) for bullet points.

Transcript:
{transcript}
"""
    try:
        return ask_llm(prompt, VideoInsights, model=model), model
    except Exception as e:
        logging.warning(f"Primary model {model} failed: {e}. Falling back to openrouter/free...")
        try:
            fallback_model = "openrouter/free"
            return ask_llm(prompt, VideoInsights, model=fallback_model), fallback_model
        except Exception as fallback_err:
            logging.error(f"Fallback model failed as well: {fallback_err}")
            return None, model
