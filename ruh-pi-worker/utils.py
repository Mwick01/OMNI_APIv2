from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

SL_TZ = ZoneInfo("Asia/Colombo")
SITE_TS_PATTERN = re.compile(r"(20\d{2}-\d{2}-\d{2})[/ ](\d{2}:\d{2})")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def sl_now() -> datetime:
    return datetime.now(SL_TZ)


def iso_utc(value: datetime | None = None) -> str:
    return (value or utc_now()).astimezone(timezone.utc).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def parse_site_timestamp(value: str) -> datetime | None:
    match = SITE_TS_PATTERN.search(value or "")
    if not match:
        return None
    try:
        naive = datetime.strptime(
            f"{match.group(1)} {match.group(2)}", "%Y-%m-%d %H:%M"
        )
        return naive.replace(tzinfo=SL_TZ)
    except ValueError:
        return None


def clean_site_timestamp_text(value: str) -> str:
    match = SITE_TS_PATTERN.search(value or "")
    if not match:
        return (value or "").strip()
    return f"{match.group(1)} {match.group(2)}"


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def normalize_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, "")
    )


def build_notice_key(source: str, title: str, date_on_site: str, download_url: str) -> str:
    raw = "|".join(
        [
            normalize_text(source),
            normalize_text(title),
            normalize_text(date_on_site),
            normalize_url(download_url),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def safe_filename(value: str) -> str:
    name = os.path.basename((value or "").split("?")[0])
    name = re.sub(r"[\\/:*?\"<>|&=]", "_", name)
    name = re.sub(r"\s+", "_", name).strip("._")
    return name[:180] or "notice_file"


def get_file_type(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip(".") or "unknown"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def retry_delay_minutes(attempts: int) -> int:
    # attempts is the new attempt count after a failure.
    schedule = [1, 5, 15, 30, 60, 360]
    return schedule[min(max(attempts - 1, 0), len(schedule) - 1)]


def next_retry_iso(attempts: int) -> str:
    return iso_utc(utc_now() + timedelta(minutes=retry_delay_minutes(attempts)))
