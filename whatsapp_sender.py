"""
whatsapp_sender.py
Sends unsent notices to a WhatsApp group using Green API (free tier).
No Node.js, no puppeteer, no session files needed.
"""
import re
import os
import requests
from pathlib import Path
from database import get_unsent_notices, mark_as_sent

INSTANCE_ID = os.getenv("GREEN_API_INSTANCE")
API_TOKEN   = os.getenv("GREEN_API_TOKEN")
GROUP_ID    = os.getenv("WHATSAPP_GROUP_ID")   # e.g. 120363XXXXXXXXXX@g.us
BASE_URL    = f"https://api.green-api.com/waInstance{INSTANCE_ID}"

SUPPORTED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".docx", ".doc"}


def send_message(text):
    """Send a plain text message."""
    url = f"{BASE_URL}/sendMessage/{API_TOKEN}"
    payload = {
        "chatId": GROUP_ID,
        "message": text
    }
    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def send_file(file_path, caption=""):
    """Send a file (PDF, image, docx) with caption."""
    url = f"{BASE_URL}/sendFileByUpload/{API_TOKEN}"
    with open(file_path, "rb") as f:
        filename = Path(file_path).name
        resp = requests.post(
            url,
            data={"chatId": GROUP_ID, "caption": caption},
            files={"file": (filename, f)},
            timeout=60
        )
    resp.raise_for_status()
    return resp.json()


def build_caption(notice):
    id_, title, url, file_path, file_type, date_on_site, downloaded_at, _ = notice
    
    # Clean title — remove trailing "Download"
    clean_title = title.replace("Download", "").strip()
    
    # Clean date — extract just the date/time part (e.g. "2026-03-23/16:07")
    # Sometimes date_on_site gets extra text concatenated
    date_match = re.search(r"\d{4}-\d{2}-\d{2}[/ ]\d{2}:\d{2}", date_on_site or "")
    clean_date = date_match.group(0) if date_match else date_on_site

    return "\n".join([
        "📢 *New Notice*",
        "",
        f"📌 *{clean_title}*",
        f"🕐 {clean_date}",
        f"🔗 {url}",
    ])


def send_notices():
    unsent = get_unsent_notices()

    if not unsent:
        print("📭 No new notices to send.")
        return

    print(f"📤 Sending {len(unsent)} notice(s) to WhatsApp...")

    for notice in unsent:
        id_ = notice[0]
        file_path = notice[3]
        caption = build_caption(notice)

        try:
            ext = Path(file_path).suffix.lower() if file_path else ""
            file_exists = file_path and os.path.exists(file_path)

            if file_exists and ext == ".txt":
                # Send text content inline
                content = open(file_path, encoding="utf-8").read()[:3000]
                send_message(f"{caption}\n\n─────────────\n{content}")

            elif file_exists and ext in SUPPORTED_EXTENSIONS:
                # Send file with caption
                send_file(file_path, caption=caption)

            else:
                # No file or unsupported type — send caption + link only
                send_message(caption)

            mark_as_sent(id_)
            print(f"  ✅ Sent: {notice[1][:60]}")

            # Small delay between messages
            import time
            time.sleep(2)

        except Exception as e:
            print(f"  ❌ Failed '{notice[1][:40]}': {e}")

    print("✅ All notices sent.")


if __name__ == "__main__":
    send_notices()
