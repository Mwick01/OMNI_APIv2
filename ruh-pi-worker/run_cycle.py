#!/usr/bin/env python3
from __future__ import annotations

import fcntl
import logging
import sys
from logging.handlers import RotatingFileHandler

import outbox_db
from config import LOCK_FILE, LOG_DIR
from scraper_worker import run_scraper_cycle
from sender_worker import run_sender_cycle


def configure_logging() -> None:
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        LOG_DIR / "pi-worker.log",
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


def main() -> int:
    configure_logging()
    logger = logging.getLogger("run_cycle")
    outbox_db.init_db()

    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("w") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.warning("Previous worker cycle is still running; skipping overlap")
            return 0

        logger.info("Starting Raspberry Pi notice-worker cycle")
        try:
            run_scraper_cycle()
        except Exception as exc:
            logger.exception("Scraper cycle stopped: %s", exc)

        # Upload failures must never stop future scrape cycles, and scrape failures
        # must never stop already queued notices from being uploaded.
        try:
            run_sender_cycle()
        except Exception as exc:
            logger.exception("Sender cycle stopped: %s", exc)

        logger.info("Outbox status: %s", outbox_db.get_stats())
        logger.info("Worker cycle complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
