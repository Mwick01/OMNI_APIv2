#!/usr/bin/env python3
from __future__ import annotations

import fcntl
import logging
from logging.handlers import RotatingFileHandler

import database
from config import LOG_DIR, WORKER_LOCK_FILE
from processor_worker import run_processor_cycle
from whatsapp_sender import run_sender_cycle


def configure_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not root.handlers:
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)
        file_handler = RotatingFileHandler(LOG_DIR / "worker.log", maxBytes=5_000_000, backupCount=3)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)


def main() -> None:
    configure_logging()
    logger = logging.getLogger("worker_cycle")
    database.init_db()
    WORKER_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with WORKER_LOCK_FILE.open("w") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.warning("Another worker cycle is active; skipping")
            return
        run_processor_cycle()
        run_sender_cycle()
        logger.info("Worker cycle completed")


if __name__ == "__main__":
    main()
