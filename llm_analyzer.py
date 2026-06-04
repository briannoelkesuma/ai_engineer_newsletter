import os
import json
import logging
import requests
from openai import OpenAI
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from openai import NotFoundError
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception
import tiktoken

load_dotenv()

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

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
def ask_llm(prompt: str, schema: type[BaseModel], model: str = "openrouter/free") -> BaseModel:
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

def is_gemini_retryable(exception: Exception) -> bool:
    if isinstance(exception, requests.HTTPError):
        # Retry only on 429 or 5xx server errors
        return exception.response.status_code == 429 or exception.response.status_code >= 500
    return True

@retry(
    wait=wait_exponential(multiplier=2, min=5, max=60), 
    stop=stop_after_attempt(5),
    retry=retry_if_exception(is_gemini_retryable),
    before_sleep=lambda retry_state: logging.warning(f"Gemini API rate limited or server error. Retrying in {retry_state.next_action.sleep} seconds...")
)
def ask_gemini_direct(prompt: str, schema: type[BaseModel]) -> BaseModel:
    logging.info("Attempting LLM call with native Google Gemini API (gemini-2.5-flash)...")
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    headers = {"Content-Type": "application/json"}
    params = {"key": GEMINI_API_KEY}
    
    payload = {
        "systemInstruction": {
            "parts": [{
                "text": "You are an expert AI Engineer and technical tutor. You must output a JSON object with the following exact key:\n- \"newsletter_text\": A fully detailed technical newsletter in Telegram HTML format. Act as an elite technical tutor who explains every key concept, architectural pattern, code logic, or framework in granular detail. You must structure the newsletter by providing a detailed summary for EACH timestamp/section of the video sequentially so that readers learn everything without watching the video. Do NOT include the video date or video link. Do NOT include meta-commentary, notes about missing URLs/slides, or footnotes. CRITICAL FORMATTING RULE: Telegram HTML parse mode is strict. DO NOT use block HTML tags like <p>, <br>, <ul>, <li>, <html>, or <body>. Only use <b>, <i>, <code>, <pre>, and <a>. Use double newlines (\\n\\n) for paragraph breaks and simple dashes (-) for bullet points.\n\nYou must output ONLY a valid JSON object matching this structure:\n{\n  \"newsletter_text\": \"...\"\n}"
            }]
        },
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "newsletter_text": {
                        "type": "STRING",
                        "description": "A fully detailed technical newsletter in Telegram HTML format."
                    }
                },
                "required": ["newsletter_text"]
            },
            "temperature": 0.3
        }
    }
    
    response = requests.post(url, json=payload, headers=headers, params=params)
    response.raise_for_status()
    res_data = response.json()
    
    try:
        text_content = res_data["candidates"][0]["content"]["parts"][0]["text"]
        return schema.model_validate_json(text_content)
    except Exception as e:
        logging.error(f"Failed to parse Gemini response: {e}. Raw response: {res_data}")
        raise

def count_tokens(text: str) -> int:
    try:
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except Exception:
        # Fallback estimation
        return len(text) // 4

def analyze_transcript(title: str, description: str, upload_date: str, transcript: str, model: str = "openrouter/free") -> tuple[VideoInsights | None, str]:
    token_count = count_tokens(transcript)
    logging.info(f"Transcript estimated token count: {token_count}")
    
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

    if GEMINI_API_KEY:
        try:
            return ask_gemini_direct(prompt, VideoInsights), "native_gemini_2.5_flash"
        except Exception as gemini_err:
            logging.warning(f"Native Gemini API failed: {gemini_err}. Falling back to OpenRouter...")
            
    if not OPENROUTER_API_KEY:
        logging.error("OpenRouter API key missing.")
        return None, model
        
    logging.info(f"Using OpenRouter single-pass analysis (model: {model}).")
    try:
        return ask_llm(prompt, VideoInsights, model=model), model
    except Exception as e:
        logging.error(f"OpenRouter model {model} failed: {e}")
        if model != "openrouter/free":
            try:
                logging.info("Falling back to openrouter/free...")
                return ask_llm(prompt, VideoInsights, model="openrouter/free"), "openrouter/free"
            except Exception as fallback_err:
                logging.error(f"Fallback to openrouter/free failed: {fallback_err}")
        return None, model
