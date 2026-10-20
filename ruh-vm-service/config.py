from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc


def env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number") from exc


def env_csv(name: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, "").split(",") if item.strip()]


DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data"))).expanduser().resolve()
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(DATA_DIR / "uploads"))).expanduser().resolve()
STAGING_DIR = Path(os.getenv("STAGING_DIR", str(DATA_DIR / "staging"))).expanduser().resolve()
LOG_DIR = Path(os.getenv("LOG_DIR", str(BASE_DIR / "logs"))).expanduser().resolve()
RUN_DIR = Path(os.getenv("RUN_DIR", str(DATA_DIR / "run"))).expanduser().resolve()
DB_PATH = Path(os.getenv("DB_PATH", str(DATA_DIR / "database.db"))).expanduser().resolve()

for directory in (DATA_DIR, UPLOAD_DIR, STAGING_DIR, LOG_DIR, RUN_DIR):
    directory.mkdir(parents=True, exist_ok=True)

PI_API_TOKEN = os.getenv("PI_API_TOKEN", "").strip()
ALLOWED_PI_DEVICES = set(env_csv("ALLOWED_PI_DEVICES"))
MAX_UPLOAD_MB = env_int("MAX_UPLOAD_MB", 25)
UPLOAD_CHUNK_BYTES = env_int("UPLOAD_CHUNK_BYTES", 1024 * 1024)

API_HOST = os.getenv("API_HOST", "127.0.0.1").strip()
API_PORT = env_int("API_PORT", 8100)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-nano").strip()
PROCESS_BATCH_SIZE = env_int("PROCESS_BATCH_SIZE", 2)
MAX_ANALYSIS_ATTEMPTS = env_int("MAX_ANALYSIS_ATTEMPTS", 5)
PROCESSING_STALE_MINUTES = env_int("PROCESSING_STALE_MINUTES", 30)

GREEN_API_INSTANCE = os.getenv("GREEN_API_INSTANCE", "").strip()
GREEN_API_TOKEN = os.getenv("GREEN_API_TOKEN", "").strip()
WHATSAPP_GROUP_IDS = env_csv("WHATSAPP_GROUP_IDS")
DELIVERY_BATCH_SIZE = env_int("DELIVERY_BATCH_SIZE", 10)
MAX_DELIVERY_ATTEMPTS = env_int("MAX_DELIVERY_ATTEMPTS", 30)
DELIVERY_STALE_MINUTES = env_int("DELIVERY_STALE_MINUTES", 15)
SEND_DELAY_SECONDS = env_float("SEND_DELAY_SECONDS", 2.0)
GREEN_CONNECT_TIMEOUT = env_int("GREEN_CONNECT_TIMEOUT", 20)
GREEN_READ_TIMEOUT = env_int("GREEN_READ_TIMEOUT", 90)

WORKER_LOCK_FILE = RUN_DIR / "worker-cycle.lock"
API_PID_FILE = RUN_DIR / "api.pid"


def validate_api_config() -> None:
    if not PI_API_TOKEN:
        raise RuntimeError("PI_API_TOKEN is required before starting the ingestion API")


def green_base_url() -> str:
    return f"https://7107.api.green-api.com/waInstance{GREEN_API_INSTANCE}"
