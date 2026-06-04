import os
import requests
import logging
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

def send_telegram_message(text: str, silent: bool = False):
    """
    Sends a message to the Telegram chat.
    If silent=True, it sends without a notification sound (great for admin alerts).
    """
    if not TOKEN or not CHAT_ID:
        logging.error("Telegram credentials missing.")
        return

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    
    max_len = 3900 
    paragraphs = text.split('\n\n')
    chunks = []
    current_chunk = ""
    for p in paragraphs:
        if len(current_chunk) + len(p) + 2 > max_len:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = p
        else:
            current_chunk = current_chunk + "\n\n" + p if current_chunk else p
    if current_chunk:
        chunks.append(current_chunk.strip())
    
    for chunk in chunks:
        payload = {
            "chat_id": CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_notification": silent
        }
        
        response = requests.post(url, json=payload)
        if response.status_code != 200:
            logging.warning(f"Failed to send with HTML, trying plain text fallback. Error: {response.text}")
            payload.pop("parse_mode", None)
            fallback_response = requests.post(url, json=payload)
            if fallback_response.status_code != 200:
                logging.error(f"Failed to send Telegram message even as plain text: {fallback_response.text}")
            else:
                logging.info("Successfully sent Telegram message as plain text.")
        else:
            logging.info("Successfully sent Telegram message.")

def send_admin_alert(msg: str):
    logging.info(f"Admin Alert: {msg}")
    send_telegram_message(f"⚙️ <b>Admin Alert</b>\n{msg}", silent=True)
