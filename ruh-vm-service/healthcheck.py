#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import requests

import database
from config import API_PORT, DB_PATH, UPLOAD_DIR


def main() -> None:
    database.init_db()
    report = {
        "database": str(DB_PATH),
        "database_exists": DB_PATH.exists(),
        "upload_directory": str(UPLOAD_DIR),
        "upload_directory_exists": UPLOAD_DIR.exists(),
        "stats": database.get_stats(),
    }
    try:
        response = requests.get(f"http://127.0.0.1:{API_PORT}/health", timeout=5)
        report["api"] = {"status_code": response.status_code, "body": response.json()}
    except Exception as exc:
        report["api"] = {"error": str(exc)}
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
