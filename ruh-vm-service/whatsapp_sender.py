from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path

import requests

import database
from config import (
    DELIVERY_BATCH_SIZE,
    DELIVERY_STALE_MINUTES,
    GREEN_API_INSTANCE,
    GREEN_API_TOKEN,
    GREEN_CONNECT_TIMEOUT,
    GREEN_READ_TIMEOUT,
    SEND_DELAY_SECONDS,
    WHATSAPP_GROUP_IDS,
    green_base_url,
)

logger = logging.getLogger(__name__)
SUPPORTED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".docx", ".doc"}
SOURCE_LABELS = {
    "green": "🟢 Green FOSMIS (fosmis2019)",
    "purple": "🟣 Purple FOSMIS (fosmis)",
}


def _configured() -> bool:
    if not GREEN_API_INSTANCE or not GREEN_API_TOKEN:
        logger.error("GREEN_API_INSTANCE or GREEN_API_TOKEN is missing")
        return False
    if not WHATSAPP_GROUP_IDS:
        logger.error("WHATSAPP_GROUP_IDS is empty")
        return False
    return True


def send_message(text: str, group_id: str) -> None:
    response = requests.post(
        f"{green_base_url()}/sendMessage/{GREEN_API_TOKEN}",
        json={"chatId": group_id, "message": text},
        timeout=(GREEN_CONNECT_TIMEOUT, GREEN_READ_TIMEOUT),
    )
    response.raise_for_status()


def send_file(
    file_path,
    group_id,
    caption,
):
    with open(file_path, "rb") as file:

        response = requests.post(
            f"{green_base_url()}/sendFileByUpload/{GREEN_API_TOKEN}",
            data={
                "chatId": group_id,
                "caption": caption,
            },
            files={
                "file": (
                    Path(file_path).name,
                    file,
                )
            },
            timeout=(
                GREEN_CONNECT_TIMEOUT,
                GREEN_READ_TIMEOUT,
            ),
        )

    response.raise_for_status()


def _has(value: object) -> bool:
    return value is not None and str(value).strip().lower() not in {"", "none", "null"}


def build_caption(notice) -> str:
    title = re.sub(r"\s*Download\s*", " ", notice["title"] or "").strip()
    date_match = re.search(r"\d{4}-\d{2}-\d{2}[/ ]\d{2}:\d{2}", notice["date_on_site"] or "")
    clean_date = date_match.group(0) if date_match else (notice["date_on_site"] or "")
    source_label = SOURCE_LABELS.get(notice["source"] or "green", "🟢 Green FOSMIS")

    lines = [
        "📢 *New Notice*",
        "",
        f"📌 *{title}*",
        "",
        f"🕐 {clean_date}",
        f"🏛️ {source_label}",
        f"🔗 {notice['url']}",
    ]

    path = Path(notice["file_path"] or "")
    if path.is_file() and path.suffix.lower() == ".txt":
        try:
            content = path.read_text(encoding="utf-8", errors="replace")[:3000].strip()
            if content:
                lines += ["", "───────────────", "📄 *Notice Content:*", content]
        except OSError:
            pass

    ai_fields = [
        notice["subject_code"], notice["subject_name"], notice["degree_programme"],
        notice["semester_exam"], notice["deadline"], notice["summary"],
    ]
    if any(_has(value) for value in ai_fields):
        lines += ["", "───────────────", "🤖 *AI Overview* :-"]
        if _has(notice["degree_programme"]):
            lines.append(f"🎓 *Programme:* {notice['degree_programme']}")
        if _has(notice["subject_name"]) and _has(notice["subject_code"]):
            lines.append(f"📘 *Subject:* {notice['subject_name']} ({notice['subject_code']})")
        elif _has(notice["subject_name"]):
            lines.append(f"📘 *Subject:* {notice['subject_name']}")
        elif _has(notice["subject_code"]):
            lines.append(f"📘 *Subject Code:* {notice['subject_code']}")
        if _has(notice["semester_exam"]):
            lines.append(f"🗓️ *Exam:* {notice['semester_exam']}")
        if _has(notice["deadline"]):
            lines.append(f"⏰ *Deadline:* {notice['deadline']}")
        if _has(notice["summary"]):
            lines.append(f"📝 *Summary:* _{notice['summary']}_")
        lines += ["", "_`⚠️ AI can make mistakes. Verify with the original notice.`_"]

    return "\n".join(lines)


def run_sender_cycle() -> None:
    if not _configured():
        return

    database.init_db()
    recovered = database.recover_stale_deliveries(DELIVERY_STALE_MINUTES)
    if recovered:
        logger.warning("Recovered %d stale WhatsApp delivery job(s)", recovered)

    rows = database.claim_delivery_batch(DELIVERY_BATCH_SIZE)
    if not rows:
        logger.info("No group deliveries waiting")
        return

    for row in rows:
        delivery_id = int(row["delivery_id"])
        notice_id = int(row["notice_id"])
        group_id = row["group_id"]
        try:
            path = Path(row["file_path"] or "")
            caption = build_caption(row)
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                    send_file(
                        str(path),
                        group_id,
                        caption,
                    )
            else:
                    send_message(caption, group_id)
            database.mark_delivery_success(delivery_id, notice_id)
            logger.info("Sent notice %s to group %s", notice_id, group_id)
        except Exception as exc:
            dead = database.mark_delivery_failure(delivery_id, notice_id, str(exc))
            if dead:
                logger.exception("Delivery moved to dead-letter state: notice=%s group=%s", notice_id, group_id)
            else:
                logger.exception("Delivery failed and will retry: notice=%s group=%s", notice_id, group_id)
        time.sleep(max(SEND_DELAY_SECONDS, 0))
