#!/usr/bin/env python3
from __future__ import annotations

import shutil
from datetime import datetime

import outbox_db
from config import DATA_DIR, DB_PATH, DOWNLOAD_DIR, VM_INGEST_URL


def main() -> None:
    outbox_db.init_db()
    total, used, free = shutil.disk_usage(DATA_DIR)

    print("RUH Pi Worker health")
    print("====================")
    print(f"Database: {DB_PATH}")
    print(f"Downloads: {DOWNLOAD_DIR}")
    print(f"VM configured: {'yes' if VM_INGEST_URL else 'no'}")
    print(f"Free disk: {free / 1024 / 1024:.1f} MB")
    print(f"Outbox: {outbox_db.get_stats()}")
    print("Portals:")
    for state in outbox_db.get_portal_states():
        print(
            f"  {state['portal']}: bootstrapped={bool(state['bootstrapped'])}, "
            f"last_success={state['last_successful_scrape_at']}, "
            f"failures={state['consecutive_failures']}, "
            f"next_retry={state['next_scrape_at']}, "
            f"last_error={state['last_error']}"
        )


if __name__ == "__main__":
    main()
