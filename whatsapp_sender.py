import re
import os
import requests
from pathlib import Path
from database import get_unsent_notices, mark_as_sent

INSTANCE_ID = os.getenv("GREEN_API_INSTANCE")
API_TOKEN   = os.getenv("GREEN_API_TOKEN")
GROUP_ID    = os.getenv("WHATSAPP_GROUP_ID")
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

def build_caption(notice, text_content=None):
    # Unpack all 14 columns
    id_, title, url, file_path, file_type, date_on_site, downloaded_at, sent, \
    subject_code, subject_name, degree_programme, semester_exam, deadline, summary = notice

    clean_title = title.replace("Download", "").strip()
    
    date_match = re.search(r"\d{4}-\d{2}-\d{2}[/ ]\d{2}:\d{2}", date_on_site or "")
    clean_date = date_match.group(0) if date_match else date_on_site

    caption_lines = [
        "📢 *New Notice*",
        "",
        f"📌 *{clean_title}*",
        "",
        f"🕐 {clean_date}",
        f"🔗 {url}"
    ]

    if text_content:
        caption_lines.extend([
            "",
            "───────────────",
            "📄 *Notice Content:*",
            text_content.strip()
        ])

    has_subject_code    = subject_code      and str(subject_code).lower()      != "null"
    has_subject_name    = subject_name      and str(subject_name).lower()       != "null"
    has_degree          = degree_programme  and str(degree_programme).lower()   != "null"
    has_semester        = semester_exam     and str(semester_exam).lower()      != "null"
    has_deadline        = deadline          and str(deadline).lower()           != "null"
    has_summary         = summary           and str(summary).lower()            != "null"

    if any([has_subject_code, has_subject_name, has_degree, has_semester, has_deadline, has_summary]):
        caption_lines.extend([
            "",
            "───────────────",
            "🤖 *AI Overview* :-"
        ])

        if has_degree:
            caption_lines.append(f"🎓 *Programme:* {degree_programme}")
        if has_subject_code and has_subject_name:
            caption_lines.append(f"📘 *Subject:* {subject_name} ({subject_code})")
        elif has_subject_name:
            caption_lines.append(f"📘 *Subject:* {subject_name}")
        elif has_subject_code:
            caption_lines.append(f"📘 *Subject Code:* {subject_code}")
        if has_semester:
            caption_lines.append(f"🗓️ *Exam:* {semester_exam}")
        if has_deadline:
            caption_lines.append(f"⏰ *Deadline:* {deadline}")
        if has_summary:
            caption_lines.append(f"📝 *Summary:* _{summary}_")

        caption_lines.extend([
            "",
            "_`⚠️ Note: AI can make mistakes. Please verify with the original notice.`_"
        ])

    return "\n".join(caption_lines)

def send_notices():
    unsent = get_unsent_notices()

    if not unsent:
        print("📭 No new notices to send.")
        return

    print(f"📤 Sending {len(unsent)} notice(s) to WhatsApp...")

    for notice in unsent:
        id_ = notice[0]
        file_path = notice[3]
        
        # Determine file info first
        ext = Path(file_path).suffix.lower() if file_path else ""
        file_exists = file_path and os.path.exists(file_path)
        
        # If it is a text file, read it BEFORE building the caption
        text_content = None
        if file_exists and ext == ".txt":
            try:
                # Grab the first 3000 characters so we don't hit WhatsApp limits
                text_content = open(file_path, encoding="utf-8").read()[:3000]
            except Exception as e:
                print(f"  ⚠️ Could not read text file: {e}")

        # Build the caption and pass the text into it!
        caption = build_caption(notice, text_content=text_content)

        try:
            # If it's a PDF/Image/Word doc, send as a file
            if file_exists and ext in SUPPORTED_EXTENSIONS:
                send_file(file_path, caption=caption)
            
            # If it's a .txt file OR there is no file, just send the text message
            else:
                send_message(caption)

            mark_as_sent(id_)
            print(f"  ✅ Sent: {notice[1][:60]}")

            import time
            time.sleep(2)

        except Exception as e:
            print(f"  ❌ Failed '{notice[1][:40]}': {e}")

    print("✅ All notices sent.")

if __name__ == "__main__":
    send_notices()