from __future__ import annotations

import hashlib
import hmac
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile, status

import database
from config import (
    ALLOWED_PI_DEVICES,
    MAX_UPLOAD_MB,
    PI_API_TOKEN,
    STAGING_DIR,
    UPLOAD_CHUNK_BYTES,
    UPLOAD_DIR,
    validate_api_config,
)

NOTICE_KEY_RE = re.compile(r"^[a-f0-9]{64}$")
SOURCE_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")

app = FastAPI(title="RUH Notice Ingestion API", version="1.0.0")


@app.on_event("startup")
def startup() -> None:
    validate_api_config()
    database.init_db()


def _authorize(authorization: str | None, pi_device: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    supplied = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied, PI_API_TOKEN):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token")
    if ALLOWED_PI_DEVICES and (not pi_device or pi_device not in ALLOWED_PI_DEVICES):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Pi device is not allowed")


def _safe_filename(name: str) -> str:
    """
    Preserve the human-readable/original filename while removing
    characters that are unsafe for filesystem paths.
    """

    name = Path(name or "notice.bin").name

    # Keep Unicode, spaces, brackets, etc.
    # Remove only dangerous/path-invalid characters.
    name = re.sub(
        r'[\x00-\x1f\x7f/\\:*?"<>|]+',
        "_",
        name,
    ).strip()

    if not name:
        return "notice.bin"

    # Avoid excessively long filenames.
    if len(name) > 180:
        suffix = Path(name).suffix
        stem = Path(name).stem

        max_stem = max(
            1,
            180 - len(suffix)
        )

        name = stem[:max_stem] + suffix

    return name

async def _save_and_hash(upload: UploadFile, temporary_path: Path) -> tuple[str, int]:
    maximum = MAX_UPLOAD_MB * 1024 * 1024
    digest = hashlib.sha256()
    size = 0
    with temporary_path.open("wb") as output:
        while True:
            chunk = await upload.read(UPLOAD_CHUNK_BYTES)
            if not chunk:
                break
            size += len(chunk)
            if size > maximum:
                raise HTTPException(status_code=413, detail=f"File exceeds {MAX_UPLOAD_MB} MB limit")
            digest.update(chunk)
            output.write(chunk)
        output.flush()
        os.fsync(output.fileno())
    return digest.hexdigest(), size


@app.get("/health")
def health() -> dict:
    database.init_db()
    return {"ok": True, "stats": database.get_stats()}


@app.post("/api/v1/notices", status_code=status.HTTP_201_CREATED)
async def ingest_notice(
    notice_key: str = Form(...),
    source: str = Form(...),
    title: str = Form(...),
    date_on_site: str = Form(""),
    site_timestamp: str = Form(""),
    download_url: str = Form(...),
    file_type: str = Form("unknown"),
    file_sha256: str = Form(...),
    notice_file: UploadFile = File(...),
    authorization: str | None = Header(default=None),
    x_pi_device: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None),
) -> dict:
    _authorize(authorization, x_pi_device)

    notice_key = notice_key.strip().lower()
    file_sha256 = file_sha256.strip().lower()
    source = source.strip().lower()

    if not NOTICE_KEY_RE.fullmatch(notice_key):
        raise HTTPException(status_code=422, detail="notice_key must be a lowercase SHA-256 hex string")
    if idempotency_key and idempotency_key.strip().lower() != notice_key:
        raise HTTPException(status_code=422, detail="Idempotency-Key does not match notice_key")
    if not NOTICE_KEY_RE.fullmatch(file_sha256):
        raise HTTPException(status_code=422, detail="file_sha256 must be a lowercase SHA-256 hex string")
    if not SOURCE_RE.fullmatch(source):
        raise HTTPException(status_code=422, detail="Invalid source")
    if not title.strip() or len(title) > 1000:
        raise HTTPException(status_code=422, detail="Invalid title")
    if not download_url.startswith(("https://", "http://")):
        raise HTTPException(status_code=422, detail="Invalid download URL")

    database.init_db()
    existing = database.get_notice_by_key(notice_key)
    if existing:
        existing_hash = (existing["file_sha256"] or "").lower()
        if existing_hash and existing_hash != file_sha256:
            raise HTTPException(status_code=409, detail="Existing notice has a different file hash")
        existing_path = Path(existing["file_path"] or "")
        if existing_path.is_file():
            return {
                "accepted": True,
                "duplicate": True,
                "notice_key": notice_key,
                "notice_id": int(existing["id"]),
            }

    raw_original_filename = Path(
        notice_file.filename or f"{notice_key}.bin"
    ).name
    
    # Preserve spaces + Unicode for WhatsApp/display,
    # but remove dangerous control characters.
    original_filename = re.sub(
        r"[\x00-\x1f\x7f]+",
        "",
        raw_original_filename,
    ).strip()
    
    if not original_filename:
        original_filename = f"{notice_key}.bin"
    
    # Separate storage-safe version for VM disk.
    original_filename = _safe_filename(
        notice_file.filename
        or f"{notice_key}.bin"
    )
    
    suffix = Path(
        original_filename
    ).suffix.lower()[:15]
    
    date_dir = datetime.now(
        timezone.utc
    ).strftime("%Y/%m")
    
    # Unique directory for this notice.
    notice_dir = (
        UPLOAD_DIR
        / date_dir
        / notice_key
    )
    
    notice_dir.mkdir(
        parents=True,
        exist_ok=True
    )
    
    # IMPORTANT:
    # Actual physical file now has the original filename.
    final_path = (
        notice_dir
        / original_filename
    )
    
    temp_path = STAGING_DIR / f"{notice_key}.{uuid4().hex}.part"

    try:
        actual_hash, _size = await _save_and_hash(notice_file, temp_path)
        if actual_hash != file_sha256:
            raise HTTPException(status_code=422, detail="Uploaded file hash does not match file_sha256")
        os.replace(temp_path, final_path)

        if existing:
            database.repair_notice_file(int(existing["id"]), str(final_path), file_type or suffix.lstrip("."), actual_hash)
            return {
                "accepted": True,
                "duplicate": True,
                "notice_key": notice_key,
                "notice_id": int(existing["id"]),
            }

        notice_id, duplicate = database.insert_received_notice(
            notice_key=notice_key,
            source=source,
            title=title.strip(),
            date_on_site=date_on_site.strip(),
            site_timestamp=site_timestamp.strip(),
            download_url=download_url.strip(),
            file_path=str(final_path),
            file_type=(file_type or suffix.lstrip(".") or "unknown").strip().lower(),
            file_sha256=actual_hash,
            original_filename=original_filename,
        )
        return {
            "accepted": True,
            "duplicate": duplicate,
            "notice_key": notice_key,
            "notice_id": notice_id,
        }
    finally:
        try:
            await notice_file.close()
        finally:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
