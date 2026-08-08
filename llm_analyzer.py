import os
import json
import logging
import re
import time
from openai import OpenAI
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from openai import NotFoundError, RateLimitError
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception
import tiktoken

load_dotenv()

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

DEFAULT_FALLBACK_MODELS = [
    "google/gemma-4-26b-a4b-it:free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "openai/gpt-oss-20b:free",
    "openrouter/free"
]

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
    if hasattr(exception, "status_code") and exception.status_code in (400, 401, 402, 403, 404):
        return False
    return True

def extract_json_object(text: str) -> str:
    """
    Extracts the outermost JSON object {...} from text, ignoring any chain-of-thought or markdown wrappers.
    """
    text = text.strip()
    # Strip markdown wrappers if present
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    # Find first '{' and last '}'
    first_brace = text.find('{')
    last_brace = text.rfind('}')
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return text[first_brace:last_brace + 1]
    return text

def clean_json_math_escapes(content: str) -> str:
    latex_ntrbf = {
        'text', 'textbf', 'textit', 'texttt', 'textsf', 'times', 'theta', 'tau', 'tan', 'tilde', 'triangle', 'to', 'top',
        'newline', 'nabla', 'nearrow', 'neg', 'neq', 'num', 'nsub', 'nsup', 'nexists',
        'rightarrow', 'rho', 'rangle', 'rbrace', 'real', 'right', 'rharpoonup', 'rightharpoonup',
        'beta', 'bar', 'begin', 'box', 'bmatrix', 'bmod', 'bot', 'buildrel',
        'frac', 'forall', 'frown', 'flat'
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

@retry(
    wait=wait_exponential(multiplier=1.5, min=3, max=20), 
    stop=stop_after_attempt(3),
    retry=retry_if_exception(is_retryable_exception),
    before_sleep=lambda retry_state: logging.warning(f"Rate limited or API error. Retrying in {retry_state.next_action.sleep} seconds...")
)
def ask_llm(prompt: str, schema: type[BaseModel], model: str = "google/gemma-4-26b-a4b-it:free") -> BaseModel:
    logging.info(f"Attempting LLM call with model: {model}")
    
    if schema == VideoInsights:
        system_content = """You are an expert AI Engineer and technical tutor. You must output a JSON object with the following exact keys:
- "telegram_summary_text": A highly detailed technical, narrative-style newsletter summary (approx 200-400 words) for Telegram. Act as an elite technical tutor who explains the core concepts, problems, business rules, and technical solutions. You MUST include a dedicated bulleted list of Key Learnings (focusing on framework configurations, design patterns, and constraints). Use strict Telegram HTML parse mode format: only use <b>, <i>, <code>, <pre>, and <a> tags. Do NOT use markdown or generic HTML tags. Do NOT include timestamps or video link. Use double newlines (\\n\\n) for paragraph breaks and simple dashes (-) for bullet points.
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
        max_tokens=8192,
        response_format={"type": "json_object"}
    )
    raw_content = completion.choices[0].message.content or ""
    
    json_str = extract_json_object(raw_content)
    json_str = clean_json_math_escapes(json_str)
    
    try:
        return schema.model_validate_json(json_str)
    except Exception as e:
        # Fallback manual json parse
        try:
            parsed = json.loads(json_str)
            return schema.model_validate(parsed)
        except Exception:
            logging.error(f"JSON validation failed: {e}\nRaw content was:\n{raw_content[:500]}")
            raise

def count_tokens(text: str) -> int:
    try:
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except Exception:
        return len(text) // 4

def chunk_transcript(transcript: str, chunk_size_tokens: int = 20000) -> list[str]:
    try:
        encoding = tiktoken.get_encoding("cl100k_base")
        tokens = encoding.encode(transcript)
    except Exception:
        chunk_size_chars = chunk_size_tokens * 4
        return [transcript[i:i + chunk_size_chars] for i in range(0, len(transcript), chunk_size_chars)]
        
    chunks = []
    for i in range(0, len(tokens), chunk_size_tokens):
        chunk_tokens = tokens[i:i + chunk_size_tokens]
        chunks.append(encoding.decode(chunk_tokens))
    return chunks

def get_model_limits(model_name: str) -> tuple[int, int]:
    model_lower = model_name.lower()
    if "gemini" in model_lower:
        return 500000, 100000
    elif any(x in model_lower for x in ["llama-3-8b", "gemma-2", "mistral-7b"]):
        return 6000, 4000
    elif any(x in model_lower for x in ["llama-3.1", "llama-3.2", "llama-3.3", "gemma-4", "nemotron"]):
        return 80000, 30000
    return 30000, 20000

def analyze_transcript(title: str, description: str, upload_date: str, transcript: str, model: str = None) -> tuple[VideoInsights | None, str]:
    if not model:
        model = os.environ.get("DEFAULT_MODEL", "google/gemma-4-26b-a4b-it:free")
    
    candidate_models = [model] + [m for m in DEFAULT_FALLBACK_MODELS if m != model]
    
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

        for current_model in candidate_models:
            try:
                logging.info(f"Attempting analysis with model {current_model}...")
                insights = ask_llm(prompt, VideoInsights, model=current_model)
                return insights, current_model
            except Exception as e:
                logging.warning(f"Model {current_model} failed: {e}. Trying next fallback...")
                
        return None, model

    else:
        logging.info(f"Transcript ({token_count} tokens) exceeds single-pass threshold ({map_reduce_threshold}). Initiating Map-Reduce...")
        
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
            for current_model in candidate_models:
                try:
                    chunk_summary = ask_llm(chunk_prompt, ChunkSummary, model=current_model)
                    if chunk_summary:
                        break
                except Exception as e:
                    logging.warning(f"Model {current_model} failed on chunk {i+1}: {e}")
                    
            if not chunk_summary:
                logging.error(f"Could not map chunk {i+1}. Aborting Map-Reduce.")
                return None, model
                
            summaries.append(chunk_summary.summary)
            time.sleep(2)
            
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
        for current_model in candidate_models:
            try:
                reduced = ask_llm(reduce_prompt, VideoInsights, model=current_model)
                return reduced, current_model
            except Exception as e:
                logging.warning(f"Reduce phase failed with model {current_model}: {e}")
                
        return None, model
