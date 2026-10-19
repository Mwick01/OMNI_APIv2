from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from config import DB_PATH
from utils import iso_utc, next_retry_iso, parse_iso, utc_now


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS portal_state (
                portal                    TEXT PRIMARY KEY,
                bootstrapped              INTEGER NOT NULL DEFAULT 0,
                last_seen_site_ts         TEXT,
                last_successful_scrape_at TEXT,
                consecutive_failures      INTEGER NOT NULL DEFAULT 0,
                next_scrape_at            TEXT,
                last_error                TEXT
            );

            CREATE TABLE IF NOT EXISTS notice_outbox (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                notice_key          TEXT NOT NULL UNIQUE,
                source              TEXT NOT NULL,
                title               TEXT NOT NULL,
                date_on_site        TEXT,
                site_timestamp      TEXT,
                download_url        TEXT NOT NULL,
                original_filename   TEXT,
                local_file_path     TEXT,
                file_type           TEXT,
                file_sha256         TEXT,
                status              TEXT NOT NULL DEFAULT 'discovered',
                download_attempts   INTEGER NOT NULL DEFAULT 0,
                next_download_at    TEXT,
                upload_attempts     INTEGER NOT NULL DEFAULT 0,
                next_upload_at      TEXT,
                last_error          TEXT,
                discovered_at       TEXT NOT NULL,
                downloaded_at       TEXT,
                acknowledged_at     TEXT,
                vm_notice_id        INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_outbox_download_due
            ON notice_outbox(status, next_download_at);

            CREATE INDEX IF NOT EXISTS idx_outbox_upload_due
            ON notice_outbox(status, next_upload_at);
            """
        )


def get_portal_state(portal: str) -> sqlite3.Row:
    with connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO portal_state(portal) VALUES (?)", (portal,)
        )
        row = conn.execute(
            "SELECT * FROM portal_state WHERE portal = ?", (portal,)
        ).fetchone()
        assert row is not None
        return row


def portal_is_due(portal: str) -> bool:
    state = get_portal_state(portal)
    next_at = parse_iso(state["next_scrape_at"])
    return next_at is None or next_at <= utc_now()


def mark_portal_success(portal: str, last_seen_site_ts: str | None) -> None:
    with connection() as conn:
        existing = conn.execute(
            "SELECT last_seen_site_ts FROM portal_state WHERE portal = ?", (portal,)
        ).fetchone()
        current = existing["last_seen_site_ts"] if existing else None

        chosen = current
        if last_seen_site_ts:
            current_dt = parse_iso(current)
            new_dt = parse_iso(last_seen_site_ts)
            if current_dt is None or (new_dt is not None and new_dt > current_dt):
                chosen = last_seen_site_ts

        conn.execute(
            """
            INSERT INTO portal_state(
                portal, bootstrapped, last_seen_site_ts,
                last_successful_scrape_at, consecutive_failures,
                next_scrape_at, last_error
            ) VALUES (?, 1, ?, ?, 0, NULL, NULL)
            ON CONFLICT(portal) DO UPDATE SET
                bootstrapped = 1,
                last_seen_site_ts = excluded.last_seen_site_ts,
                last_successful_scrape_at = excluded.last_successful_scrape_at,
                consecutive_failures = 0,
                next_scrape_at = NULL,
                last_error = NULL
            """,
            (portal, chosen, iso_utc()),
        )


def mark_portal_failure(portal: str, error: str) -> None:
    with connection() as conn:
        row = conn.execute(
            "SELECT consecutive_failures FROM portal_state WHERE portal = ?", (portal,)
        ).fetchone()
        failures = (row["consecutive_failures"] if row else 0) + 1

        # Portal retry cadence: 5, 5, 15, 30, then 60 minutes.
        schedule = [5, 5, 15, 30, 60]
        minutes = schedule[min(failures - 1, len(schedule) - 1)]
        from datetime import timedelta

        next_at = iso_utc(utc_now() + timedelta(minutes=minutes))
        conn.execute(
            """
            INSERT INTO portal_state(
                portal, consecutive_failures, next_scrape_at, last_error
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(portal) DO UPDATE SET
                consecutive_failures = excluded.consecutive_failures,
                next_scrape_at = excluded.next_scrape_at,
                last_error = excluded.last_error
            """,
            (portal, failures, next_at, error[:1000]),
        )


def insert_notices_batch(items: list[dict]) -> tuple[int, int]:
    """Insert many scraped notices in one SQLite transaction.

    Returns (newly_queued, baseline_ignored). Duplicate notice_keys are ignored.
    """
    newly_queued = 0
    baseline_count = 0
    discovered_at = iso_utc()

    with connection() as conn:
        for item in items:
            baseline_ignored = bool(item.get("baseline_ignored"))
            status = "baseline_ignored" if baseline_ignored else "discovered"
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO notice_outbox(
                    notice_key, source, title, date_on_site, site_timestamp,
                    download_url, original_filename, status, discovered_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["notice_key"],
                    item["source"],
                    item["title"],
                    item["date_on_site"],
                    item.get("site_timestamp"),
                    item["download_url"],
                    item.get("original_filename"),
                    status,
                    discovered_at,
                ),
            )
            if cursor.rowcount == 1:
                if baseline_ignored:
                    baseline_count += 1
                else:
                    newly_queued += 1

    return newly_queued, baseline_count


def insert_notice_if_new(
    *,
    notice_key: str,
    source: str,
    title: str,
    date_on_site: str,
    site_timestamp: str | None,
    download_url: str,
    original_filename: str,
    baseline_ignored: bool,
) -> bool:
    """Backward-compatible single-row insert helper."""
    queued, baseline = insert_notices_batch([
        {
            "notice_key": notice_key,
            "source": source,
            "title": title,
            "date_on_site": date_on_site,
            "site_timestamp": site_timestamp,
            "download_url": download_url,
            "original_filename": original_filename,
            "baseline_ignored": baseline_ignored,
        }
    ])
    return (queued + baseline) == 1


def get_download_due(limit: int) -> list[sqlite3.Row]:
    now = iso_utc()
    with connection() as conn:
        return conn.execute(
            """
            SELECT * FROM notice_outbox
            WHERE status IN ('discovered', 'download_failed')
              AND (next_download_at IS NULL OR next_download_at <= ?)
            ORDER BY discovered_at ASC
            LIMIT ?
            """,
            (now, limit),
        ).fetchall()


def mark_download_success(
    notice_id: int,
    *,
    local_file_path: str,
    file_type: str,
    file_sha256: str,
) -> None:
    with connection() as conn:
        conn.execute(
            """
            UPDATE notice_outbox SET
                local_file_path = ?,
                file_type = ?,
                file_sha256 = ?,
                status = 'pending_upload',
                downloaded_at = ?,
                next_download_at = NULL,
                last_error = NULL
            WHERE id = ?
            """,
            (local_file_path, file_type, file_sha256, iso_utc(), notice_id),
        )


def mark_download_failed(notice_id: int, error: str) -> None:
    with connection() as conn:
        row = conn.execute(
            "SELECT download_attempts FROM notice_outbox WHERE id = ?", (notice_id,)
        ).fetchone()
        attempts = (row["download_attempts"] if row else 0) + 1
        conn.execute(
            """
            UPDATE notice_outbox SET
                status = 'download_failed',
                download_attempts = ?,
                next_download_at = ?,
                last_error = ?
            WHERE id = ?
            """,
            (attempts, next_retry_iso(attempts), error[:1000], notice_id),
        )


def get_upload_due(limit: int) -> list[sqlite3.Row]:
    now = iso_utc()
    with connection() as conn:
        return conn.execute(
            """
            SELECT * FROM notice_outbox
            WHERE status IN ('pending_upload', 'upload_failed')
              AND (next_upload_at IS NULL OR next_upload_at <= ?)
            ORDER BY discovered_at ASC
            LIMIT ?
            """,
            (now, limit),
        ).fetchall()


def mark_upload_success(notice_id: int, vm_notice_id: int | None) -> None:
    with connection() as conn:
        conn.execute(
            """
            UPDATE notice_outbox SET
                status = 'acknowledged',
                acknowledged_at = ?,
                vm_notice_id = ?,
                next_upload_at = NULL,
                last_error = NULL
            WHERE id = ?
            """,
            (iso_utc(), vm_notice_id, notice_id),
        )


def mark_upload_failed(notice_id: int, error: str) -> None:
    with connection() as conn:
        row = conn.execute(
            "SELECT upload_attempts FROM notice_outbox WHERE id = ?", (notice_id,)
        ).fetchone()
        attempts = (row["upload_attempts"] if row else 0) + 1
        conn.execute(
            """
            UPDATE notice_outbox SET
                status = 'upload_failed',
                upload_attempts = ?,
                next_upload_at = ?,
                last_error = ?
            WHERE id = ?
            """,
            (attempts, next_retry_iso(attempts), error[:1000], notice_id),
        )


def reset_for_redownload(notice_id: int, error: str) -> None:
    with connection() as conn:
        conn.execute(
            """
            UPDATE notice_outbox SET
                status = 'discovered',
                local_file_path = NULL,
                file_type = NULL,
                file_sha256 = NULL,
                next_download_at = NULL,
                last_error = ?
            WHERE id = ?
            """,
            (error[:1000], notice_id),
        )


def get_stats() -> dict[str, int]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS count FROM notice_outbox GROUP BY status"
        ).fetchall()
    return {row["status"]: row["count"] for row in rows}


def get_portal_states() -> list[sqlite3.Row]:
    with connection() as conn:
        return conn.execute(
            "SELECT * FROM portal_state ORDER BY portal"
        ).fetchall()
