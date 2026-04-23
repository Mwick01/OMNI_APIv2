import re
import os
import time
import requests
from pathlib import Path
from database import get_unsent_notices, mark_as_sent

# ── Green API (WhatsApp Group) ─────────────────────────────────────────────
INSTANCE_ID = os.getenv("GREEN_API_INSTANCE")
API_TOKEN   = os.getenv("GREEN_API_TOKEN")
GROUP_ID    = os.getenv("WHATSAPP_GROUP_ID")
BASE_URL    = f"https://api.green-api.com/waInstance{INSTANCE_ID}"

# ── Whapi (WhatsApp Channel) ───────────────────────────────────────────────
WHAPI_TOKEN = os.getenv("WHAPI_TOKEN")
CHANNEL_ID  = os.getenv("WHATSAPP_CHANNEL_ID")   # e.g. 120363171744447809@newsletter

# ── Your group / site links shown to channel subscribers ──────────────────
WHATSAPP_GROUP_INVITE = os.getenv("WHATSAPP_GROUP_INVITE_LINK", "")   # https://chat.whatsapp.com/xxx
OFFICIAL_SITE_URL     = os.getenv("OFFICIAL_SITE_URL", "")            # https://fosmis.kln.ac.lk

# ── File-type config ───────────────────────────────────────────────────────
# Types the Green API group accepts
GROUP_SUPPORTED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".docx", ".doc"}

# Types WhatsApp Channels natively support (documents are NOT allowed)
CHANNEL_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
CHANNEL_VIDEO_EXTENSIONS = {".mp4", ".mov"}

SOURCE_LABELS = {
    "green":  "🟢 Green FOSMIS (fosmis2019)",
    "purple": "🟣 Purple FOSMIS (fosmis)",
}


# ══════════════════════════════════════════════════════════════════════════════
#  GREEN API  –  WhatsApp Group
# ══════════════════════════════════════════════════════════════════════════════

def send_message(text):
    resp = requests.post(
        f"{BASE_URL}/sendMessage/{API_TOKEN}",
        json={"chatId": GROUP_ID, "message": text},
        timeout=30,
    )
    resp.raise_for_status()


def send_file(file_path, caption=""):
    with open(file_path, "rb") as f:
        resp = requests.post(
            f"{BASE_URL}/sendFileByUpload/{API_TOKEN}",
            data={"chatId": GROUP_ID, "caption": caption},
            files={"file": (Path(file_path).name, f)},
            timeout=60,
        )
    resp.raise_for_status()


# ══════════════════════════════════════════════════════════════════════════════
#  WHAPI  –  WhatsApp Channel
# ══════════════════════════════════════════════════════════════════════════════

def _whapi_headers(json_body=False):
    h = {
        "accept": "application/json",
        "authorization": f"Bearer {WHAPI_TOKEN}",
    }
    if json_body:
        h["content-type"] = "application/json"
    return h


def _build_view_links_text():
    """Returns a footer block pointing subscribers to the file."""
    parts = []
    if WHATSAPP_GROUP_INVITE:
        parts.append(f"👥 *Join our WhatsApp Group* to download the file:\n{WHATSAPP_GROUP_INVITE}")
    if OFFICIAL_SITE_URL:
        parts.append(f"🌐 *Official Site:*\n{OFFICIAL_SITE_URL}")
    if parts:
        return "\n\n───────────────\n📎 *View / Download the attachment:*\n" + "\n\n".join(parts)
    return ""


def send_to_channel_whapi(caption, file_path=None, notice_url=None):
    """
    Broadcast to the WhatsApp Channel via Whapi.

    • Images / videos  → sent as media with caption
    • PDFs / docs      → sent as text with a link footer pointing to the group
                         or the official site where the file can be downloaded
    • No file          → plain text
    """
    if not WHAPI_TOKEN or not CHANNEL_ID:
        print("    ⚠️  Whapi config missing. Skipping Channel broadcast.")
        return

    ext = Path(file_path).suffix.lower() if file_path else ""
    file_exists = file_path and os.path.exists(file_path)

    # ── Case 1: image ──────────────────────────────────────────────────────
    if file_exists and ext in CHANNEL_IMAGE_EXTENSIONS:
        url = "https://gate.whapi.cloud/messages/image"
        try:
            with open(file_path, "rb") as f:
                resp = requests.post(
                    url,
                    data={"to": CHANNEL_ID, "caption": caption},
                    files={"media": (os.path.basename(file_path), f)},
                    headers=_whapi_headers(),
                    timeout=60,
                )
            resp.raise_for_status()
            print("    📡 [Channel] Image sent")
        except Exception as e:
            print(f"    ❌ [Channel] Image failed: {e}")
        return

    # ── Case 2: video ──────────────────────────────────────────────────────
    if file_exists and ext in CHANNEL_VIDEO_EXTENSIONS:
        url = "https://gate.whapi.cloud/messages/video"
        try:
            with open(file_path, "rb") as f:
                resp = requests.post(
                    url,
                    data={"to": CHANNEL_ID, "caption": caption},
                    files={"media": (os.path.basename(file_path), f)},
                    headers=_whapi_headers(),
                    timeout=60,
                )
            resp.raise_for_status()
            print("    📡 [Channel] Video sent")
        except Exception as e:
            print(f"    ❌ [Channel] Video failed: {e}")
        return

    # ── Case 3: PDF / DOC / unsupported file  →  text + link footer ────────
    if file_exists and ext in {".pdf", ".docx", ".doc"}:
        print(f"    ℹ️  [Channel] '{ext}' not supported on Channels — sending text + link.")

    # Build the text body:
    # Use the notice URL as the primary link, fall back to group/site links
    link_footer = ""
    if notice_url:
        link_footer = (
            "\n\n───────────────\n"
            f"📎 *View / Download the full notice:*\n{notice_url}\nJoin group to see the PDF"
        )
        # Append group / site links as secondary options
        secondary = _build_view_links_text()
        if secondary:
            link_footer += "\n" + secondary
    else:
        link_footer = _build_view_links_text()

    full_text = caption + link_footer

    url = "https://gate.whapi.cloud/messages/text"
    try:
        resp = requests.post(
            url,
            json={"to": CHANNEL_ID, "body": full_text},
            headers=_whapi_headers(json_body=True),
            timeout=60,
        )
        resp.raise_for_status()
        print("    📡 [Channel] Text + link sent")
    except Exception as e:
        print(f"    ❌ [Channel] Text failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  Caption builder  (shared by both group & channel)
# ══════════════════════════════════════════════════════════════════════════════

def build_caption(notice, text_content=None):
    (id_, title, url, file_path, file_type, date_on_site, downloaded_at, sent,
     subject_code, subject_name, degree_programme, semester_exam,
     deadline, summary, source) = notice

    clean_title = title.replace("Download", "").strip()
    date_match  = re.search(r"\d{4}-\d{2}-\d{2}[/ ]\d{2}:\d{2}", date_on_site or "")
    clean_date  = date_match.group(0) if date_match else (date_on_site or "")

    source_label = SOURCE_LABELS.get(source or "green", "🟢 Green FOSMIS")

    lines = [
        "📢 *New Notice*",
        "",
        f"📌 *{clean_title}*",
        "",
        f"🕐 {clean_date}",
        f"🏛️ {source_label}",
        f"🔗 {url}",
    ]

    if text_content:
        lines += ["", "───────────────", "📄 *Notice Content:*", text_content.strip()]

    has = lambda v: v and str(v).lower() not in ("null", "none", "")
    if any(has(x) for x in [subject_code, subject_name, degree_programme,
                              semester_exam, deadline, summary]):
        lines += ["", "───────────────", "🤖 *AI Overview* :-"]
        if has(degree_programme):
            lines.append(f"🎓 *Programme:* {degree_programme}")
        if has(subject_name) and has(subject_code):
            lines.append(f"📘 *Subject:* {subject_name} ({subject_code})")
        elif has(subject_name):
            lines.append(f"📘 *Subject:* {subject_name}")
        elif has(subject_code):
            lines.append(f"📘 *Subject Code:* {subject_code}")
        if has(semester_exam):
            lines.append(f"🗓️ *Exam:* {semester_exam}")
        if has(deadline):
            lines.append(f"⏰ *Deadline:* {deadline}")
        if has(summary):
            lines.append(f"📝 *Summary:* _{summary}_")
        lines += ["", "_`⚠️ AI can make mistakes. Verify with original notice.`_"]

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
#  Main send loop
# ══════════════════════════════════════════════════════════════════════════════

def send_notices():
    unsent = get_unsent_notices()

    if not unsent:
        print("📭 No new notices to send.")
        return

    print(f"📤 Sending {len(unsent)} notice(s)...")

    for notice in unsent:
        id_        = notice[0]
        notice_url = notice[2]   # original URL on the website
        file_path  = notice[3]
        ext        = Path(file_path).suffix.lower() if file_path else ""
        file_exists = file_path and os.path.exists(file_path)

        # Read .txt content inline (for group caption)
        text_content = None
        if file_exists and ext == ".txt":
            try:
                text_content = open(file_path, encoding="utf-8").read()[:3000]
            except Exception:
                pass

        caption = build_caption(notice, text_content=text_content)

        # ── 1. Send to WhatsApp Group (Green API) ──────────────────────────
        try:
            if file_exists and ext in GROUP_SUPPORTED_EXTENSIONS:
                send_file(file_path, caption=caption)
            else:
                send_message(caption)

            source = notice[14] if len(notice) > 14 else "?"
            print(f"  ✅ [Group/{source}] {notice[1][:55]}")
        except Exception as e:
            print(f"  ❌ [Group] Failed '{notice[1][:40]}': {e}")

        time.sleep(2)

        # ── 2. Send to WhatsApp Channel (Whapi) ────────────────────────────
        send_to_channel_whapi(caption, file_path=file_path, notice_url=notice_url)

        time.sleep(2)

        mark_as_sent(id_)

    print("✅ All notices sent.")


if __name__ == "__main__":
    send_notices()