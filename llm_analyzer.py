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

client = OpenAI(
  base_url="https://openrouter.ai/api/v1",
  api_key=OPENROUTER_API_KEY,
  max_retries=0,
)

class VideoInsights(BaseModel):
    telegram_summary_text: str = Field(description="A highly detailed technical, narrative-style newsletter for Telegram (approx 200-400 words). Explain the core concepts, problems, business rules, and technical solutions covered in the video. Break it down into clear subsections with headers. You MUST include a dedicated bulleted list of Key Learnings (specifically focusing on framework configs, architecture decisions, and implementation constraints). Focus purely on technical substance. Do NOT include timestamps, do NOT include video date/link. CRITICAL FORMATTING RULE: Telegram HTML parse mode is strict. Only use <b>, <i>, <code>, <pre>, and <a> tags. Use double newlines (\\n\\n) for paragraph breaks and simple dashes (-) for bullet points.")
    webpage_detailed_info_text: str = Field(description="An extremely comprehensive, tutorial-grade, highly granular technical deep-dive of the video. Act as an elite principal software engineer and technical educator. You MUST detail every single concept, architecture pattern, code logic block, framework configuration, system design decision, database setup, and step-by-step implementation mentioned in the video. The output must be so detailed, clear, and comprehensive that a developer can fully learn and replicate the systems without watching the video. Organize it sequentially using timestamps/sections. FORMATTING RULE: Use standard Markdown format (headings, lists, bold, italics, tables, and code blocks) so it can be rendered as Markdown on the website.")

class ChunkSummary(BaseModel):
    summary: str = Field(description="A highly detailed technical summary and key insights extracted from this transcript chunk.")

def is_retryable_exception(exception: Exception) -> bool:
    if isinstance(exception, NotFoundError):
        return False
    # Check for HTTP status codes that shouldn't be retried
    if hasattr(exception, "status_code") and exception.status_code in (400, 401, 402, 403, 404):
        return False
    return True

def clean_json_math_escapes(content: str) -> str:
    import re
    # Set of LaTeX commands starting with n, t, r, b, f
    latex_ntrbf = {
        'newline', 'nabla', 'nearrow', 'neg', 'times', 'theta', 'tau', 'tan', 
        'tilde', 'triangle', 'rightarrow', 'rho', 'rangle', 'rbrace', 'real', 
        'beta', 'bar', 'begin', 'box', 'frac', 'forall', 'frown'
    }
    
    def replace_match(match):
        backslash_and_char = match.group(0)
        char = match.group(1)
        rest = match.group(2)
        
        if char not in ('n', 't', 'r', 'b', 'f', 'u'):
            return '\\\\' + char + rest
            
        if char in ('n', 't', 'r', 'b', 'f'):
            word = char + rest
            if word in latex_ntrbf:
                return '\\\\' + word
            return backslash_and_char
            
        if char == 'u':
            if len(rest) >= 4 and all(c in '0123456789abcdefABCDEF' for c in rest[:4]):
                if len(rest) == 4 or not rest[4].isalpha():
                    return backslash_and_char
            return '\\\\' + char + rest
            
        return backslash_and_char

    pattern = r'\\([a-zA-Z])([a-zA-Z]*)'
    return re.sub(pattern, replace_match, content)

# Retry logic for 429 Too Many Requests (Rate Limits)
@retry(
    wait=wait_exponential(multiplier=1.5, min=5, max=30), 
    stop=stop_after_attempt(3),
    retry=retry_if_exception(is_retryable_exception),
    before_sleep=lambda retry_state: logging.warning(f"Rate limited or API error. Retrying in {retry_state.next_action.sleep} seconds...")
)
def ask_llm(prompt: str, schema: type[BaseModel], model: str = "meta-llama/llama-3.3-70b-instruct:free") -> BaseModel:
    logging.info(f"Attempting LLM call with model: {model}")
    
    if schema == VideoInsights:
        system_content = """You are an expert AI Engineer and technical tutor. You must output a JSON object with the following exact keys:
- "telegram_summary_text": A highly detailed technical, narrative-style newsletter summary (approx 200-400 words) for Telegram. Act as an elite technical tutor who explains the core concepts, problems, business rules, and technical solutions. You MUST include a dedicated bulleted list of Key Learnings (focusing on framework configurations, design patterns, and constraints). Use strict Telegram HTML parse mode format: only use <b>, <i>, <code>, <pre>, and <a> tags. Do NOT use block HTML tags or Markdown here. Do NOT include timestamps or video link. Use double newlines (\\n\\n) for paragraph breaks and simple dashes (-) for bullet points.
- "webpage_detailed_info_text": An extremely comprehensive, tutorial-grade, highly granular technical deep-dive of the video. Act as an elite principal software engineer and technical educator. Detail every concept, architecture pattern, code logic block, framework configuration, system design decision, database setup, and step-by-step implementation. Organize it sequentially using timestamps/sections. Use standard Markdown format (headings, lists, bold, italics, tables, and code blocks) so it can be rendered as Markdown on the website.

You must output ONLY a valid JSON object matching this structure:
{
  "telegram_summary_text": "...",
  "webpage_detailed_info_text": "..."
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
        content = clean_json_math_escapes(content)
        return schema.model_validate_json(content)
    except Exception as e:
        logging.error(f"JSON validation failed: {e}\nContent was:\n{content}")
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
    elif any(x in model_lower for x in ["llama-3-8b", "llama3-8b", "gemma-2", "gemma2", "mistral-7b"]):
        return 6000, 4000
    # Large context models (Llama 3.1 / 3.2 / 3.3, Gemma 4, Hermes 3, Nemotron typically have 128k)
    elif any(x in model_lower for x in ["llama-3.1", "llama-3.2", "llama-3.3", "gemma-4", "gemma4", "hermes-3", "nemotron"]):
        return 80000, 30000
    # openrouter/free (safer default for routing)
    elif "openrouter/free" in model_lower or "gpt-oss" in model_lower:
        return 30000, 20000
    
    # Safe fallback
    return 30000, 20000

def analyze_transcript(title: str, description: str, upload_date: str, transcript: str, model: str = None) -> tuple[VideoInsights | None, str]:
    if not model:
        model = os.environ.get("DEFAULT_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
    token_count = count_tokens(transcript)
    logging.info(f"Transcript estimated token count: {token_count}")
    
    map_reduce_threshold, chunk_size = get_model_limits(model)
    logging.info(f"Model limits for '{model}' -> Threshold: {map_reduce_threshold} tokens, Chunk size: {chunk_size} tokens")
    
    if token_count <= map_reduce_threshold:
        logging.info("Transcript size within limit. Running single-pass analysis...")
        prompt = f"""
Video Title: {title}
Video Description: {description}

Your task is to provide:
1. "telegram_summary_text": A highly detailed technical, narrative-style newsletter summary (approx 200-400 words) for Telegram. Focus on the core message, technical concepts, and implementation strategies without timestamps. Use strict Telegram HTML parse mode format: only use <b>, <i>, <code>, <pre>, and <a> tags. Use double newlines (\\n\\n) for paragraph breaks and simple dashes (-) for bullet points.
2. "webpage_detailed_info_text": An extremely comprehensive, tutorial-grade, highly granular technical deep-dive of the video. Detail every concept, architecture pattern, code logic block, framework configuration, system design decision, database setup, and step-by-step implementation sequentially (using timestamps/sections). Use standard Markdown format (headings, lists, bold, italics, tables, and code blocks) so it can be rendered as Markdown on the website.

Do NOT include the video date or link in the texts.

Transcript:
{transcript}
"""

        if not OPENROUTER_API_KEY:
            logging.error("OpenRouter API key missing.")
            return None, model
            
        logging.info(f"Using OpenRouter single-pass analysis (model: {model}).")
        try:
            return ask_llm(prompt, VideoInsights, model=model), model
        except Exception as e:
            logging.error(f"OpenRouter model {model} failed: {e}")
            fallback_models = ["google/gemma-4-31b-it:free", "openrouter/free"]
            for fallback_model in fallback_models:
                if model != fallback_model:
                    try:
                        logging.info(f"Falling back to {fallback_model}...")
                        return ask_llm(prompt, VideoInsights, model=fallback_model), fallback_model
                    except Exception as fallback_err:
                        logging.error(f"Fallback to {fallback_model} failed: {fallback_err}")
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
            if OPENROUTER_API_KEY:
                try:
                    chunk_summary = ask_llm(chunk_prompt, ChunkSummary, model=model)
                except Exception as e:
                    logging.warning(f"Primary model {model} failed on chunk {i+1}: {e}.")
                    fallback_models = ["google/gemma-4-31b-it:free", "openrouter/free"]
                    for fallback_model in fallback_models:
                        if model != fallback_model:
                            try:
                                logging.info(f"Falling back to {fallback_model} on chunk {i+1}...")
                                chunk_summary = ask_llm(chunk_prompt, ChunkSummary, model=fallback_model)
                                break
                            except Exception as fallback_err:
                                logging.error(f"Fallback to {fallback_model} failed on chunk {i+1}: {fallback_err}")
                        
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
Your task is to combine and synthesize these summaries into a single JSON object containing:
1. "telegram_summary_text": A highly detailed technical, narrative-style newsletter summary (approx 200-400 words) for Telegram. Focus on the core message, technical concepts, and implementation strategies without timestamps. Use strict Telegram HTML parse mode format: only use <b>, <i>, <code>, <pre>, and <a> tags. Use double newlines (\\n\\n) for paragraph breaks and simple dashes (-) for bullet points.
2. "webpage_detailed_info_text": An extremely comprehensive, tutorial-grade, highly granular technical deep-dive of the video. Detail every concept, architecture pattern, code logic block, framework configuration, system design decision, database setup, and step-by-step implementation sequentially (using timestamps/sections). Use standard Markdown format (headings, lists, bold, italics, tables, and code blocks) so it can be rendered as Markdown on the website.

Do NOT include the video date or link in the texts.

Summaries:
{combined_summaries}
"""
        reduced = None
        if OPENROUTER_API_KEY:
            try:
                reduced = ask_llm(reduce_prompt, VideoInsights, model=model)
                return reduced, model
            except Exception as e:
                logging.warning(f"Primary model failed on reduce phase: {e}.")
                fallback_models = ["google/gemma-4-31b-it:free", "openrouter/free"]
                for fallback_model in fallback_models:
                    if model != fallback_model:
                        try:
                            logging.info(f"Falling back to {fallback_model} on reduce phase...")
                            reduced = ask_llm(reduce_prompt, VideoInsights, model=fallback_model)
                            return reduced, fallback_model
                        except Exception as fallback_err:
                            logging.error(f"Fallback to {fallback_model} failed on reduce phase: {fallback_err}")
                            
        return None, model
