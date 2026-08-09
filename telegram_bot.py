import os
import requests
import logging
import time
from dotenv import load_dotenv

load_dotenv()

def get_credentials():
    load_dotenv(override=True)
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    summary_thread_id = os.environ.get("TELEGRAM_SUMMARY_THREAD_ID", "").strip()
    digest_chat_id = os.environ.get("TELEGRAM_DIGEST_CHAT_ID", "").strip() or chat_id
    digest_thread_id = os.environ.get("TELEGRAM_DIGEST_THREAD_ID", "").strip()
    return token, chat_id, summary_thread_id, digest_chat_id, digest_thread_id

def send_telegram_message(text: str, silent: bool = False, target_chat_id: str = None, thread_id: str | int = None, video_id: str = None) -> bool:
    """
    Sends a message to the Telegram chat or a specific Topic / Sub-channel (message_thread_id).
    If video_id is provided, attaches an inline 'Mark as Read' button.
    Returns True if successful, False otherwise.
    """
    token, default_chat_id, default_thread_id, _, _ = get_credentials()
    chat_id = target_chat_id or default_chat_id
    active_thread_id = thread_id if thread_id is not None else (default_thread_id or None)
    
    if not token or not chat_id:
        logging.error("Telegram credentials missing (TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID).")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    
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
    
    all_success = True
    for chunk in chunks:
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_notification": silent
        }
        if active_thread_id:
            payload["message_thread_id"] = int(active_thread_id)
            
        # Only attach the button to the last chunk of the message if video_id is present
        if video_id and chunk == chunks[-1]:
            payload["reply_markup"] = {
                "inline_keyboard": [[
                    {"text": "📬 Mark as Read", "callback_data": f"markread_{video_id}"}
                ]]
            }
        
        try:
            response = requests.post(url, json=payload, timeout=15)
            if response.status_code != 200:
                logging.warning(f"Failed to send with HTML, trying plain text fallback. Error: {response.text}")
                payload.pop("parse_mode", None)
                fallback_response = requests.post(url, json=payload, timeout=15)
                if fallback_response.status_code != 200:
                    logging.error(f"Failed to send Telegram message: {fallback_response.text}")
                    all_success = False
                else:
                    logging.info("Successfully sent Telegram message as plain text.")
            else:
                logging.info("Successfully sent Telegram message.")
        except Exception as e:
            logging.error(f"Exception sending Telegram message: {e}")
            all_success = False

    return all_success

def send_digest_message(text: str, silent: bool = False) -> bool:
    """
    Sends the Executive Catch-Up Digest to the configured digest sub-channel / chat.
    """
    token, chat_id, _, digest_chat_id, digest_thread_id = get_credentials()
    target_chat = digest_chat_id or chat_id
    return send_telegram_message(text, silent=silent, target_chat_id=target_chat, thread_id=digest_thread_id or None)

def send_admin_alert(msg: str) -> bool:
    logging.info(f"Admin Alert: {msg}")
    return send_telegram_message(f"⚙️ <b>Admin Alert</b>\n{msg}", silent=True)

def handle_telegram_command(command: str, from_chat_id: str, from_thread_id: str = None, message_id: str = None):
    """
    Handles commands like /digest, /unread, /markread, /help and callbacks sent to the bot.
    """
    from catchup_digest import get_unopened_videos, generate_catchup_digest, mark_all_as_read
    cmd = command.strip().lower()
    
    # Check if this is a callback query
    if cmd == "callback:already_read":
        return
    elif cmd.startswith("callback:markread_"):
        video_id = cmd.replace("callback:markread_", "")
        handle_callback(video_id, from_chat_id, message_id)
        return

    # Send replies back to the exact topic where the command was typed
    thread = from_thread_id if from_thread_id else None

    
    if cmd in ["/digest", "/catchup"]:
        send_telegram_message("⚡ <i>Synthesizing your unopened video summaries into an executive digest...</i>", target_chat_id=from_chat_id, thread_id=thread)
        digest = generate_catchup_digest()
        if digest and not digest.startswith("🎉"):
            # Digest already sent within generate_catchup_digest()
            pass
        elif digest:
            send_telegram_message(digest, target_chat_id=from_chat_id, thread_id=thread)
            
    elif cmd in ["/unread", "/status"]:
        unopened = get_unopened_videos()
        count = len(unopened)
        if count == 0:
            msg = "🎉 <b>You're all caught up!</b>\n0 unopened video summaries."
        else:
            msg = f"📬 <b>Unopened Updates:</b> {count} video summaries waiting for you.\n\nSend /digest to get an AI synthesized brief of all {count} unopened updates!"
        send_telegram_message(msg, target_chat_id=from_chat_id, thread_id=thread)
        
    elif cmd in ["/markread", "/clear"]:
        total = mark_all_as_read()
        send_telegram_message(f"✅ Marked {total} video summaries as read. Your unopened backlog is cleared!", target_chat_id=from_chat_id, thread_id=thread)
        
    elif cmd in ["/help", "/start"]:
        msg = (
            "🤖 <b>AI Engineer Newsletter Bot</b>\n\n"
            "Here are the available commands:\n"
            "• <code>/digest</code> - Synthesize all unopened video summaries into an executive briefing\n"
            "• <code>/unread</code> - Check how many unopened video updates are in your queue\n"
            "• <code>/markread</code> - Mark all existing videos as read/opened\n"
            "• <code>/help</code> - Show this menu"
        )
        send_telegram_message(msg, target_chat_id=from_chat_id, thread_id=thread)

def handle_callback(video_id: str, chat_id: str, message_id: str):
    """
    Handles inline button clicks. Updates user state and modifies the button.
    """
    from catchup_digest import load_user_state, save_user_state
    import json
    
    # 1. Update user state
    state = load_user_state()
    read_ids = set(state.get("read_video_ids", []))
    read_ids.add(video_id)
    state["read_video_ids"] = list(read_ids)
    save_user_state(state)
    logging.info(f"Marked video {video_id} as read via inline button.")
    
    # 2. Edit the Telegram message to change the button to ✅ Read
    token, _, _, _, _ = get_credentials()
    if not token or not message_id:
        return
        
    url = f"https://api.telegram.org/bot{token}/editMessageReplyMarkup"
    payload = {
        "chat_id": chat_id,
        "message_id": int(message_id),
        "reply_markup": {
            "inline_keyboard": [[
                {"text": "✅ Read", "callback_data": "already_read"}
            ]]
        }
    }
    requests.post(url, json=payload, timeout=10)

def poll_updates_once():
    """
    Checks for any pending commands sent by the user and executes them.
    """
    token, _ = get_credentials()
    if not token:
        return
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    try:
        res = requests.get(url, timeout=10).json()
        if not res.get("ok"):
            return
        results = res.get("result", [])
        if not results:
            return
        latest_update_id = results[-1].get("update_id", 0)
        for update in results:
            msg = update.get("message") or update.get("channel_post")
            if not msg:
                continue
            text = (msg.get("text") or "").strip()
            chat_id = str(msg.get("chat", {}).get("id", ""))
            if text.startswith("/"):
                handle_telegram_command(text, chat_id)
        # Acknowledge offset so we don't re-process old messages
        requests.get(f"{url}?offset={latest_update_id + 1}", timeout=10)
    except Exception as e:
        logging.warning(f"Error polling Telegram updates: {e}")

def detect_and_save_chat_id():
    """
    Checks getUpdates on the bot to find the most recent user chat ID and saves it to .env.
    """
    token, _ = get_credentials()
    if not token:
        print("ERROR: TELEGRAM_BOT_TOKEN is not set in .env")
        return None
    
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    try:
        res = requests.get(url, timeout=10).json()
        if not res.get("ok"):
            print(f"Telegram API Error: {res}")
            return None
        
        results = res.get("result", [])
        if not results:
            print("No new messages found. Please open your Telegram app, search for your bot, and send /start or any message.")
            return None
        
        latest_msg = results[-1]
        chat = latest_msg.get("message", {}).get("chat") or latest_msg.get("channel_post", {}).get("chat")
        if not chat:
            print("Could not parse chat from updates:", latest_msg)
            return None
        
        chat_id = str(chat.get("id"))
        username = chat.get("username", "")
        first_name = chat.get("first_name", "")
        print(f"Found active chat ID: {chat_id} (User: {first_name} @{username})")
        
        # Update .env
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                lines = f.readlines()
            new_lines = []
            found = False
            for line in lines:
                if line.startswith("TELEGRAM_CHAT_ID="):
                    new_lines.append(f"TELEGRAM_CHAT_ID={chat_id}\n")
                    found = True
                else:
                    new_lines.append(line)
            if not found:
                new_lines.append(f"TELEGRAM_CHAT_ID={chat_id}\n")
            with open(env_path, "w") as f:
                f.writelines(new_lines)
            print(f"Successfully updated TELEGRAM_CHAT_ID={chat_id} in .env")
        
        # Send confirmation message
        os.environ["TELEGRAM_CHAT_ID"] = chat_id
        send_telegram_message("🎉 <b>AI Engineer Digest Bot Connected!</b>\nYour Telegram account is now connected and ready to receive updates.\n\nSend <code>/help</code> or <code>/digest</code> anytime to catch up on unopened updates!", silent=False)
        return chat_id
    except Exception as e:
        print(f"Error checking updates: {e}")
        return None

def detect_topics_and_save():
    """
    Scans getUpdates for group/supergroup messages and topic (message_thread_id) events.
    Saves TELEGRAM_CHAT_ID, TELEGRAM_SUMMARY_THREAD_ID, TELEGRAM_DIGEST_THREAD_ID to .env.
    """
    token, _, _, _, _ = get_credentials()
    if not token:
        print("ERROR: TELEGRAM_BOT_TOKEN is not set in .env")
        return None
    
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    try:
        res = requests.get(url, timeout=10).json()
        if not res.get("ok"):
            print(f"Telegram API Error: {res}")
            return None
        
        results = res.get("result", [])
        if not results:
            print("No updates found. Please create a group, enable Topics, add @aidotengineerbot, and send a message in each topic.")
            return None
        
        detected_chat_id = None
        topics = {}
        
        for item in results:
            msg = item.get("message") or item.get("channel_post")
            if not msg:
                continue
            chat = msg.get("chat", {})
            c_id = str(chat.get("id"))
            c_type = chat.get("type", "")
            
            thread_id = msg.get("message_thread_id")
            text = (msg.get("text") or "").strip()
            topic_created = msg.get("forum_topic_created", {}).get("name")
            
            if c_type in ["group", "supergroup", "channel"]:
                detected_chat_id = c_id
                if thread_id:
                    name = topic_created or text or f"Topic {thread_id}"
                    topics[str(thread_id)] = name
            elif not detected_chat_id:
                detected_chat_id = c_id
                
        print(f"Detected Group/Chat ID: {detected_chat_id}")
        print(f"Detected Topics (message_thread_id): {topics}")
        
        # Update .env
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        env_updates = {}
        if detected_chat_id:
            env_updates["TELEGRAM_CHAT_ID"] = detected_chat_id
            
        topic_keys = list(topics.keys())
        if len(topic_keys) >= 2:
            # Assign first as summary, second as digest or vice versa based on name keywords
            t1, t2 = topic_keys[0], topic_keys[1]
            if "digest" in topics.get(t1, "").lower() or "catch" in topics.get(t1, "").lower():
                env_updates["TELEGRAM_DIGEST_THREAD_ID"] = t1
                env_updates["TELEGRAM_SUMMARY_THREAD_ID"] = t2
            else:
                env_updates["TELEGRAM_SUMMARY_THREAD_ID"] = t1
                env_updates["TELEGRAM_DIGEST_THREAD_ID"] = t2
        elif len(topic_keys) == 1:
            env_updates["TELEGRAM_SUMMARY_THREAD_ID"] = topic_keys[0]

        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                lines = f.readlines()
            new_lines = []
            for line in lines:
                key = line.split("=")[0].strip() if "=" in line else None
                if key in env_updates:
                    new_lines.append(f"{key}={env_updates.pop(key)}\n")
                else:
                    new_lines.append(line)
            for k, v in env_updates.items():
                new_lines.append(f"{k}={v}\n")
            with open(env_path, "w") as f:
                f.writelines(new_lines)
            print("Successfully updated .env with group and topic settings!")
            
        return detected_chat_id, topics
    except Exception as e:
        print(f"Error detecting topics: {e}")
        return None

def set_webhook(url: str):
    """
    Registers a webhook URL with Telegram to receive updates automatically.
    """
    token, _, _, _, _ = get_credentials()
    if not token:
        print("ERROR: TELEGRAM_BOT_TOKEN missing.")
        return
    
    api_url = f"https://api.telegram.org/bot{token}/setWebhook"
    try:
        res = requests.post(api_url, json={"url": url}, timeout=10).json()
        if res.get("ok"):
            print(f"Successfully set webhook to: {url}")
        else:
            print(f"Failed to set webhook: {res}")
    except Exception as e:
        print(f"Error setting webhook: {e}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "detect":
        detect_topics_and_save()
    elif len(sys.argv) > 1 and sys.argv[1] == "test":
        success = send_telegram_message("🚀 <b>Test Message</b> from AI Engineer Pipeline!")
        print("Send successful:" if success else "Send failed.")
    elif len(sys.argv) > 1 and sys.argv[1] == "poll":
        poll_updates_once()
    elif len(sys.argv) >= 4 and sys.argv[1] == "handle":
        thread_id = sys.argv[4] if len(sys.argv) > 4 else None
        message_id = sys.argv[5] if len(sys.argv) > 5 else None
        handle_telegram_command(sys.argv[2], sys.argv[3], thread_id, message_id)
    elif len(sys.argv) > 2 and sys.argv[1] == "webhook":
        set_webhook(sys.argv[2])
    else:
        detect_topics_and_save()

