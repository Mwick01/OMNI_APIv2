from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data"))).expanduser().resolve()
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", str(DATA_DIR / "downloads"))).expanduser().resolve()
LOG_DIR = Path(os.getenv("LOG_DIR", str(BASE_DIR / "logs"))).expanduser().resolve()
DB_PATH = Path(os.getenv("PI_DB_PATH", str(DATA_DIR / "pi_state.db"))).expanduser().resolve()
SESSION_FILE = Path(os.getenv("SESSION_FILE", str(DATA_DIR / "session.json"))).expanduser().resolve()
LOCK_FILE = Path(os.getenv("LOCK_FILE", str(DATA_DIR / "worker.lock"))).expanduser().resolve()

for directory in (DATA_DIR, DOWNLOAD_DIR, LOG_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SITE_USERNAME = os.getenv("SITE_USERNAME", "").strip()
SITE_PASSWORD = os.getenv("SITE_PASSWORD", "").strip()

SESSION_MAX_AGE_MINS = env_int("SESSION_MAX_AGE_MINS", 60)
INITIAL_LOOKBACK_HOURS = env_int("INITIAL_LOOKBACK_HOURS", 24)
BOOTSTRAP_UNDATED_LIMIT = env_int("BOOTSTRAP_UNDATED_LIMIT", 5)
SCAN_ROW_LIMIT = env_int("SCAN_ROW_LIMIT", 200)
SCAN_OVERLAP_HOURS = env_int("SCAN_OVERLAP_HOURS", 24)
EARLY_STOP_OLD_ROWS = env_int("EARLY_STOP_OLD_ROWS", 10)
DOWNLOAD_BATCH_SIZE = env_int("DOWNLOAD_BATCH_SIZE", 20)
UPLOAD_BATCH_SIZE = env_int("UPLOAD_BATCH_SIZE", 10)
MAX_FILE_MB = env_int("MAX_FILE_MB", 25)
VERIFY_FILE_HASH_BEFORE_UPLOAD = env_bool("VERIFY_FILE_HASH_BEFORE_UPLOAD", True)

CONNECT_TIMEOUT_SECONDS = env_int("CONNECT_TIMEOUT_SECONDS", 20)
READ_TIMEOUT_SECONDS = env_int("READ_TIMEOUT_SECONDS", 60)
UPLOAD_TIMEOUT_SECONDS = env_int("UPLOAD_TIMEOUT_SECONDS", 120)

VM_INGEST_URL = os.getenv("VM_INGEST_URL", "").strip()
PI_API_TOKEN = os.getenv("PI_API_TOKEN", "").strip()
PI_DEVICE_ID = os.getenv("PI_DEVICE_ID", "ruh-pi-zero-w").strip()


@dataclass(frozen=True)
class Portal:
    name: str
    label: str
    login_url: str
    notice_url: str
    download_base: str


# Only the currently working FOSMIS portal is scraped.
# Keep source/name as "purple" for compatibility with the existing Pi/VM databases
# and WhatsApp source labels.
PORTALS = [
    Portal(
        name="purple",
        label="FOSMIS",
        login_url=os.getenv("LOGIN_URL_PURPLE", "").strip(),
        notice_url=os.getenv("NOTICE_URL_PURPLE", "").strip(),
        download_base="https://paravi.ruh.ac.lk/fosmis/downloads/Notices/",
    ),
]


def validate_scraper_config() -> None:
    missing: list[str] = []
    if not SITE_USERNAME:
        missing.append("SITE_USERNAME")
    if not SITE_PASSWORD:
        missing.append("SITE_PASSWORD")

    for portal in PORTALS:
        if not portal.login_url:
            missing.append(f"LOGIN_URL_{portal.name.upper()}")
        if not portal.notice_url:
            missing.append(f"NOTICE_URL_{portal.name.upper()}")

    if missing:
        raise RuntimeError("Missing required .env values: " + ", ".join(missing))
