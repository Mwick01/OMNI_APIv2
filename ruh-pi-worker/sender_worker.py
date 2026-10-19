from __future__ import annotations

import json
import logging
import mimetypes
from pathlib import Path
from typing import Any

import requests

import outbox_db
from config import (
    CONNECT_TIMEOUT_SECONDS,
    PI_API_TOKEN,
    PI_DEVICE_ID,
    UPLOAD_BATCH_SIZE,
    UPLOAD_TIMEOUT_SECONDS,
    VERIFY_FILE_HASH_BEFORE_UPLOAD,
    VM_INGEST_URL,
)
from utils import sha256_file

logger = logging.getLogger(__name__)


def _parse_acknowledgement(response: requests.Response, notice_key: str) -> int | None:
    if response.status_code not in {200, 201, 409}:
        response.raise_for_status()

    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError("VM returned non-JSON acknowledgement") from exc

    accepted = payload.get("accepted") is True
    duplicate = payload.get("duplicate") is True
    returned_key = payload.get("notice_key")

    if returned_key and returned_key != notice_key:
        raise RuntimeError("VM acknowledgement notice_key does not match upload")

    if not (accepted or duplicate):
        raise RuntimeError(f"VM did not accept notice: {payload}")

    notice_id = payload.get("notice_id")
    return int(notice_id) if notice_id is not None else None


def upload_notice(row: Any) -> int | None:
    file_path = Path(row["local_file_path"] or "")
    if not file_path.is_file():
        raise FileNotFoundError(f"Queued file is missing: {file_path}")

    if VERIFY_FILE_HASH_BEFORE_UPLOAD:
        current_hash = sha256_file(file_path)
        if current_hash != row["file_sha256"]:
            raise ValueError("Local file hash no longer matches the stored hash")

    mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    headers = {
        "Authorization": f"Bearer {PI_API_TOKEN}",
        "X-Pi-Device": PI_DEVICE_ID,
        "Idempotency-Key": row["notice_key"],
    }
    fields = {
        "notice_key": row["notice_key"],
        "source": row["source"],
        "title": row["title"],
        "date_on_site": row["date_on_site"] or "",
        "site_timestamp": row["site_timestamp"] or "",
        "download_url": row["download_url"],
        "file_type": row["file_type"] or "unknown",
        "file_sha256": row["file_sha256"],
    }

    with file_path.open("rb") as file:
        response = requests.post(
            VM_INGEST_URL,
            data=fields,
            files={"notice_file": (file_path.name, file, mime_type)},
            headers=headers,
            timeout=(CONNECT_TIMEOUT_SECONDS, UPLOAD_TIMEOUT_SECONDS),
        )

    return _parse_acknowledgement(response, row["notice_key"])


def run_sender_cycle() -> None:
    rows = outbox_db.get_upload_due(UPLOAD_BATCH_SIZE)
    if not rows:
        logger.info("No notices waiting for VM upload")
        return

    if not VM_INGEST_URL:
        logger.warning(
            "%d notice(s) are safely queued, but VM_INGEST_URL is not configured yet",
            len(rows),
        )
        return
    if not PI_API_TOKEN:
        logger.error("PI_API_TOKEN is missing; refusing to upload queued notices")
        return

    logger.info("Uploading up to %d queued notice(s) to the VM", len(rows))
    for row in rows:
        try:
            vm_notice_id = upload_notice(row)
            outbox_db.mark_upload_success(row["id"], vm_notice_id)
            logger.info(
                "VM acknowledged [%s] %s", row["source"], row["title"][:80]
            )
        except (FileNotFoundError, ValueError) as exc:
            outbox_db.reset_for_redownload(row["id"], str(exc))
            logger.error("Re-queueing file for download: %s", exc)
        except Exception as exc:
            outbox_db.mark_upload_failed(row["id"], str(exc))
            logger.exception("VM upload failed for %s: %s", row["title"][:80], exc)
