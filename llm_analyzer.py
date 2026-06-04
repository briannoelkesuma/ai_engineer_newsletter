import os
import json
import logging
import time
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

class ChunkSummary(BaseModel):
    summary: str = Field(description="A highly detailed technical summary and key insights extracted from this transcript chunk.")

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
def ask_llm(prompt: str, schema: type[BaseModel], model: str = "meta-llama/llama-3.3-70b-instruct:free") -> BaseModel:
    logging.info(f"Attempting LLM call with model: {model}")
    
    if schema == VideoInsights:
        system_content = """You are an expert AI Engineer and technical tutor. You must output a JSON object with the following exact key:
- "newsletter_text": A fully detailed, technical, deep-dive newsletter in Telegram HTML format. Act as an elite technical tutor who explains every key concept, architectural pattern, code logic, framework, library, and system design decision in granular detail. The newsletter must be highly detailed and comprehensive, explaining the exact technical 'how' and 'why'. Structure the newsletter by providing a highly detailed coverage of EACH section/timestamp sequentially so that readers learn everything without watching the video. Do NOT skip any details, do NOT write a high-level summary, and be as verbose and detailed as possible. Do NOT include the video date or video link. Do NOT include meta-commentary, notes about missing URLs/slides, or footnotes. CRITICAL FORMATTING RULE: Telegram HTML parse mode is strict. DO NOT use block HTML tags like <p>, <br>, <ul>, <li>, <html>, or <body>. Only use <b>, <i>, <code>, <pre>, and <a>. Use double newlines (\\n\\n) for paragraph breaks and simple dashes (-) for bullet points.

You must output ONLY a valid JSON object matching this structure:
{
  "newsletter_text": "..."
}"""
    else:
        system_content = """You are an expert AI Engineer. Extract all detailed key points, architecture, code, and technical insights from the transcript chunk as a comprehensive detailed summary text. You must output a JSON object with the key 'summary'.

You must output ONLY a valid JSON object matching this structure:
{
  "summary": "..."
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
    
    if schema == VideoInsights:
        system_text = "You are an expert AI Engineer and technical tutor. You must output a JSON object with the following exact key:\n- \"newsletter_text\": A fully detailed, technical, deep-dive newsletter in Telegram HTML format. Act as an elite technical tutor who explains every key concept, architectural pattern, code logic, framework, library, and system design decision in granular detail. The newsletter must be highly detailed and comprehensive, explaining the exact technical 'how' and 'why'. Structure the newsletter by providing a highly detailed coverage of EACH section/timestamp sequentially so that readers learn everything without watching the video. Do NOT skip any details, do NOT write a high-level summary, and be as verbose and detailed as possible. Do NOT include the video date or video link. Do NOT include meta-commentary, notes about missing URLs/slides, or footnotes. CRITICAL FORMATTING RULE: Telegram HTML parse mode is strict. DO NOT use block HTML tags like <p>, <br>, <ul>, <li>, <html>, or <body>. Only use <b>, <i>, <code>, <pre>, and <a>. Use double newlines (\\n\\n) for paragraph breaks and simple dashes (-) for bullet points.\n\nYou must output ONLY a valid JSON object matching this structure:\n{\n  \"newsletter_text\": \"...\"\n}"
        resp_schema = {
            "type": "OBJECT",
            "properties": {
                "newsletter_text": {
                    "type": "STRING",
                    "description": "A fully detailed technical newsletter in Telegram HTML format."
                }
            },
            "required": ["newsletter_text"]
        }
    else:
        system_text = "You are an expert AI Engineer. Extract all detailed key points, architecture, code, and technical insights from the transcript chunk as a comprehensive detailed summary text.\n\nYou must output ONLY a valid JSON object matching this structure:\n{\n  \"summary\": \"...\"\n}"
        resp_schema = {
            "type": "OBJECT",
            "properties": {
                "summary": {
                    "type": "STRING",
                    "description": "A highly detailed technical summary and key insights extracted from this transcript chunk."
                }
            },
            "required": ["summary"]
        }
        
    payload = {
        "systemInstruction": {
            "parts": [{
                "text": system_text
            }]
        },
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": resp_schema,
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

def chunk_transcript(transcript: str, chunk_size_tokens: int = 20000) -> list[str]:
    try:
        encoding = tiktoken.get_encoding("cl100k_base")
        tokens = encoding.encode(transcript)
    except Exception:
        # Fallback character-based chunking if tiktoken fails
        chunk_size_chars = chunk_size_tokens * 4
        return [transcript[i:i + chunk_size_chars] for i in range(0, len(transcript), chunk_size_chars)]
        
    chunks = []
    for i in range(0, len(tokens), chunk_size_tokens):
        chunk_tokens = tokens[i:i + chunk_size_tokens]
        chunks.append(encoding.decode(chunk_tokens))
    return chunks

def get_model_limits(model_name: str) -> tuple[int, int]:
    """
    Returns (map_reduce_threshold, chunk_size_tokens) for a given model.
    """
    model_lower = model_name.lower()
    
    # Native Gemini API or Gemini model on OpenRouter
    if "gemini" in model_lower:
        # Gemini context window is 1M+, so we can safely do single-pass up to 500k tokens
        return 500000, 100000
    # Smaller models or local models on OpenRouter (typically 8k context)
    elif any(x in model_lower for x in ["llama-3-8b", "llama3-8b", "gemma", "mistral-7b"]):
        return 6000, 4000
    # Large context models (Llama 3.1 / 3.2 / 3.3 typically have 128k)
    elif any(x in model_lower for x in ["llama-3.1", "llama-3.2", "llama-3.3", "hermes-3", "nemotron"]):
        return 80000, 30000
    # openrouter/free (safer default for routing)
    elif "openrouter/free" in model_lower:
        return 30000, 20000
    
    # Safe fallback
    return 30000, 20000

def analyze_transcript(title: str, description: str, upload_date: str, transcript: str, model: str = "meta-llama/llama-3.3-70b-instruct:free") -> tuple[VideoInsights | None, str]:
    token_count = count_tokens(transcript)
    logging.info(f"Transcript estimated token count: {token_count}")
    
    # Determine the model being targeted
    target_model = "native_gemini_2.5_flash" if GEMINI_API_KEY else model
    map_reduce_threshold, chunk_size = get_model_limits(target_model)
    logging.info(f"Model limits for '{target_model}' -> Threshold: {map_reduce_threshold} tokens, Chunk size: {chunk_size} tokens")
    
    if token_count <= map_reduce_threshold:
        logging.info("Transcript size within limit. Running single-pass analysis...")
        prompt = f"""
Video Title: {title}
Video Description: {description}

Your task is to provide an extensive, deep-dive explanation and write highly detailed, granular technical 'Deep Dive' teachings.
Synthesize a Telegram Newsletter in HTML format containing all this information in full detail.
Do not truncate, summarize, or simplify; provide maximum detailed technical coverage of EACH timestamp/section sequentially so that readers learn everything without watching the video. Cover all code listings, design patterns, and systems discussed.
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

    else:
        logging.info(f"Transcript ({token_count} tokens) exceeds single-pass threshold ({map_reduce_threshold}). Initiating Map-Reduce...")
        
        # 1. Map phase: Chunk and summarize
        chunks = chunk_transcript(transcript, chunk_size_tokens=chunk_size)
        logging.info(f"Split transcript into {len(chunks)} chunks using chunk size {chunk_size} tokens.")
        
        summaries = []
        for i, chunk in enumerate(chunks):
            logging.info(f"Mapping chunk {i+1}/{len(chunks)}...")
            chunk_prompt = f"""
You are mapping a segment of a video transcript. Extract extremely comprehensive, highly detailed, granular technical points, architecture design patterns, code logic, framework configurations, and technical takeaways from this segment.
Do not omit details or summarize briefly; act as an elite technical transcriber writing for an expert developer audience.

Transcript Segment:
{chunk}
"""
            chunk_summary = None
            if GEMINI_API_KEY:
                try:
                    chunk_summary = ask_gemini_direct(chunk_prompt, ChunkSummary)
                except Exception as gemini_err:
                    logging.warning(f"Native Gemini failed on chunk {i+1}: {gemini_err}. Trying OpenRouter...")
            
            if not chunk_summary and OPENROUTER_API_KEY:
                try:
                    chunk_summary = ask_llm(chunk_prompt, ChunkSummary, model=model)
                except Exception as e:
                    logging.warning(f"Primary model {model} failed on chunk {i+1}: {e}. Trying fallback openrouter/free...")
                    try:
                        chunk_summary = ask_llm(chunk_prompt, ChunkSummary, model="openrouter/free")
                    except Exception as fallback_err:
                        logging.error(f"Map phase failed entirely on chunk {i+1}: {fallback_err}")
                        
            if not chunk_summary:
                logging.error(f"Could not map chunk {i+1}. Aborting Map-Reduce.")
                return None, model
                
            summaries.append(chunk_summary.summary)
            # Short sleep to prevent hitting prompt rate limits
            time.sleep(5)
            
        # 2. Reduce phase: Combine and format the final newsletter
        logging.info("Entering Reduce phase...")
        combined_summaries = "\n\n--- NEXT SECTION SUMMARY ---\n\n".join(summaries)
        
        reduce_prompt = f"""
Video Title: {title}
Video Description: {description}

You are provided with several sequential detailed technical summaries of different parts of a video transcript.
Your task is to combine and synthesize these summaries into a single, highly comprehensive, granular, deep-dive technical newsletter in Telegram HTML format.
Do not truncate, simplify, or skip sections; provide detailed technical coverage of the entire video sequentially so that readers learn everything. Do NOT omit code blocks, architectural details, or system components mentioned in the summaries.
Do NOT include the video date or link in the newsletter text itself. Do NOT include meta-commentary, notes about missing URLs/slides, or footnotes.
CRITICAL FORMATTING RULE: Telegram HTML parse mode is strict. DO NOT use block HTML tags like <p>, <br>, <ul>, <li>, <html>, or <body>. Only use <b>, <i>, <code>, <pre>, and <a>. Use double newlines (\\n\\n) for paragraph breaks and simple dashes (-) for bullet points.

Summaries:
{combined_summaries}
"""
        reduced = None
        if GEMINI_API_KEY:
            try:
                reduced = ask_gemini_direct(reduce_prompt, VideoInsights)
                return reduced, "native_gemini_2.5_flash"
            except Exception as gemini_err:
                logging.warning(f"Native Gemini failed on reduce phase: {gemini_err}. Trying OpenRouter...")
                
        if OPENROUTER_API_KEY:
            try:
                reduced = ask_llm(reduce_prompt, VideoInsights, model=model)
                return reduced, model
            except Exception as e:
                logging.warning(f"Primary model failed on reduce phase: {e}. Trying fallback openrouter/free...")
                try:
                    reduced = ask_llm(reduce_prompt, VideoInsights, model="openrouter/free")
                    return reduced, "openrouter/free"
                except Exception as fallback_err:
                    logging.error(f"Reduce phase failed entirely: {fallback_err}")
                    
        return None, model
