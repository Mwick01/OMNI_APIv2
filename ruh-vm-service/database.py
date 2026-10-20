from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from config import DB_PATH, MAX_ANALYSIS_ATTEMPTS, MAX_DELIVERY_ATTEMPTS


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat()


def retry_at(attempts: int) -> str:
    delays = [60, 300, 900, 1800, 3600, 10800, 21600]
    seconds = delays[min(max(attempts - 1, 0), len(delays) - 1)]
    return iso_utc(utc_now() + timedelta(seconds=seconds))


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
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


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _add_missing_columns(conn: sqlite3.Connection, table: str, columns: list[tuple[str, str]]) -> None:
    existing = _columns(conn, table)
    for name, definition in columns:
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def init_db() -> None:
    with connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notices (
                id                     INTEGER PRIMARY KEY AUTOINCREMENT,
                notice_key             TEXT,
                title                  TEXT NOT NULL,
                url                    TEXT,
                file_path              TEXT,
                file_type              TEXT,
                original_filename      TEXT,
                date_on_site           TEXT,
                site_timestamp         TEXT,
                downloaded_at          TEXT,
                received_at            TEXT,
                file_sha256            TEXT,
                sent_to_whatsapp       INTEGER NOT NULL DEFAULT 0,
                subject_code           TEXT,
                subject_name           TEXT,
                degree_programme       TEXT,
                semester_exam          TEXT,
                deadline               TEXT,
                summary                TEXT,
                source                 TEXT DEFAULT 'green',
                processing_status      TEXT NOT NULL DEFAULT 'received',
                processing_attempts    INTEGER NOT NULL DEFAULT 0,
                processing_started_at  TEXT,
                next_processing_at     TEXT,
                last_processing_error  TEXT,
                analyzed_at            TEXT
            )
            """
        )

        _add_missing_columns(
            conn,
            "notices",
            [
                ("notice_key", "TEXT"),
                ("site_timestamp", "TEXT"),
                ("received_at", "TEXT"),
                ("file_sha256", "TEXT"),
                ("original_filename", "TEXT"),
                ("processing_status", "TEXT NOT NULL DEFAULT 'received'"),
                ("processing_attempts", "INTEGER NOT NULL DEFAULT 0"),
                ("processing_started_at", "TEXT"),
                ("next_processing_at", "TEXT"),
                ("last_processing_error", "TEXT"),
                ("analyzed_at", "TEXT"),
                ("subject_code", "TEXT"),
                ("subject_name", "TEXT"),
                ("degree_programme", "TEXT"),
                ("semester_exam", "TEXT"),
                ("deadline", "TEXT"),
                ("summary", "TEXT"),
                ("source", "TEXT DEFAULT 'green'"),
                ("sent_to_whatsapp", "INTEGER NOT NULL DEFAULT 0"),
            ],
        )

        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_notices_notice_key
            ON notices(notice_key)
            WHERE notice_key IS NOT NULL AND notice_key != ''
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_notices_processing ON notices(processing_status, next_processing_at)")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notice_group_delivery (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                notice_id      INTEGER NOT NULL,
                group_id       TEXT NOT NULL,
                status         TEXT NOT NULL DEFAULT 'pending',
                attempts       INTEGER NOT NULL DEFAULT 0,
                started_at     TEXT,
                next_retry_at  TEXT,
                last_error     TEXT,
                sent_at        TEXT,
                created_at     TEXT NOT NULL,
                UNIQUE(notice_id, group_id),
                FOREIGN KEY(notice_id) REFERENCES notices(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_group_delivery_due ON notice_group_delivery(status, next_retry_at)")


def get_notice_by_key(notice_key: str) -> sqlite3.Row | None:
    with connection() as conn:
        return conn.execute("SELECT * FROM notices WHERE notice_key = ?", (notice_key,)).fetchone()


def insert_received_notice(
    *,
    notice_key: str,
    source: str,
    title: str,
    date_on_site: str,
    site_timestamp: str,
    download_url: str,
    file_path: str,
    file_type: str,
    file_sha256: str,
    original_filename: str,
) -> tuple[int, bool]:
    now = iso_utc()
    with connection() as conn:
        existing = conn.execute("SELECT id FROM notices WHERE notice_key = ?", (notice_key,)).fetchone()
        if existing:
            return int(existing["id"]), True
        try:
            cursor = conn.execute(
                """
                INSERT INTO notices (
                    notice_key, title, url, file_path, file_type,
                    date_on_site, site_timestamp, downloaded_at, received_at,
                    file_sha256, source, processing_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'received')
                """,
                (
                    notice_key,
                    title,
                    download_url,
                    file_path,
                    file_type,
                    date_on_site,
                    site_timestamp,
                    now,
                    now,
                    file_sha256,
                    source,
                ),
            )
            return int(cursor.lastrowid), False
        except sqlite3.IntegrityError:
            existing = conn.execute("SELECT id FROM notices WHERE notice_key = ?", (notice_key,)).fetchone()
            if not existing:
                raise
            return int(existing["id"]), True


def repair_notice_file(notice_id: int, file_path: str, file_type: str, file_sha256: str) -> None:
    with connection() as conn:
        conn.execute(
            """
            UPDATE notices
            SET file_path = ?, file_type = ?, file_sha256 = ?, downloaded_at = ?
            WHERE id = ?
            """,
            (file_path, file_type, file_sha256, iso_utc(), notice_id),
        )


def recover_stale_processing(stale_minutes: int) -> int:
    cutoff = iso_utc(utc_now() - timedelta(minutes=stale_minutes))
    with connection() as conn:
        cur = conn.execute(
            """
            UPDATE notices
            SET processing_status = 'analysis_failed',
                next_processing_at = ?,
                last_processing_error = COALESCE(last_processing_error, 'Recovered stale processing job')
            WHERE processing_status = 'processing'
              AND processing_started_at IS NOT NULL
              AND processing_started_at < ?
            """,
            (iso_utc(), cutoff),
        )
        return cur.rowcount


def claim_processing_batch(limit: int) -> list[sqlite3.Row]:
    now = iso_utc()
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            """
            SELECT * FROM notices
            WHERE processing_status IN ('received', 'analysis_failed')
              AND (next_processing_at IS NULL OR next_processing_at <= ?)
            ORDER BY received_at ASC, id ASC
            LIMIT ?
            """,
            (now, limit),
        ).fetchall()
        ids = [int(row["id"]) for row in rows]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            conn.execute(
                f"UPDATE notices SET processing_status='processing', processing_started_at=? WHERE id IN ({placeholders})",
                (now, *ids),
            )
        return rows


def ensure_group_deliveries(notice_id: int, group_ids: list[str]) -> None:
    now = iso_utc()
    with connection() as conn:
        for group_id in group_ids:
            conn.execute(
                """
                INSERT OR IGNORE INTO notice_group_delivery
                    (notice_id, group_id, status, created_at)
                VALUES (?, ?, 'pending', ?)
                """,
                (notice_id, group_id, now),
            )


def mark_analysis_success(notice_id: int, data: dict[str, Any]) -> None:
    with connection() as conn:
        conn.execute(
            """
            UPDATE notices SET
                subject_code = ?, subject_name = ?, degree_programme = ?,
                semester_exam = ?, deadline = ?, summary = ?,
                processing_status = 'ready', analyzed_at = ?,
                processing_started_at = NULL, next_processing_at = NULL,
                last_processing_error = NULL
            WHERE id = ?
            """,
            (
                data.get("subject_code"),
                data.get("subject_name"),
                data.get("degree_programme"),
                data.get("semester_exam"),
                data.get("deadline"),
                data.get("summary"),
                iso_utc(),
                notice_id,
            ),
        )


def mark_ready_without_analysis(notice_id: int, reason: str) -> None:
    with connection() as conn:
        conn.execute(
            """
            UPDATE notices SET
                processing_status = 'ready_without_analysis',
                processing_started_at = NULL,
                next_processing_at = NULL,
                last_processing_error = ?
            WHERE id = ?
            """,
            (reason[:1000], notice_id),
        )


def mark_analysis_failure(notice_id: int, error: str) -> bool:
    with connection() as conn:
        row = conn.execute("SELECT processing_attempts FROM notices WHERE id = ?", (notice_id,)).fetchone()
        attempts = int(row["processing_attempts"] if row else 0) + 1
        exhausted = attempts >= MAX_ANALYSIS_ATTEMPTS
        conn.execute(
            """
            UPDATE notices SET
                processing_status = ?,
                processing_attempts = ?,
                processing_started_at = NULL,
                next_processing_at = ?,
                last_processing_error = ?
            WHERE id = ?
            """,
            (
                "ready_without_analysis" if exhausted else "analysis_failed",
                attempts,
                None if exhausted else retry_at(attempts),
                error[:1000],
                notice_id,
            ),
        )
        return exhausted


def recover_stale_deliveries(stale_minutes: int) -> int:
    cutoff = iso_utc(utc_now() - timedelta(minutes=stale_minutes))
    with connection() as conn:
        cur = conn.execute(
            """
            UPDATE notice_group_delivery
            SET status = 'failed', next_retry_at = ?,
                last_error = COALESCE(last_error, 'Recovered stale delivery job')
            WHERE status = 'sending'
              AND started_at IS NOT NULL
              AND started_at < ?
            """,
            (iso_utc(), cutoff),
        )
        return cur.rowcount


def claim_delivery_batch(limit: int) -> list[sqlite3.Row]:
    now = iso_utc()
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            """
            SELECT
                d.id AS delivery_id, d.notice_id, d.group_id,
                d.status AS delivery_status, d.attempts AS delivery_attempts,
                n.*
            FROM notice_group_delivery d
            JOIN notices n ON n.id = d.notice_id
            WHERE d.status IN ('pending', 'failed')
              AND (d.next_retry_at IS NULL OR d.next_retry_at <= ?)
            ORDER BY d.created_at ASC, d.id ASC
            LIMIT ?
            """,
            (now, limit),
        ).fetchall()
        ids = [int(row["delivery_id"]) for row in rows]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            conn.execute(
                f"UPDATE notice_group_delivery SET status='sending', started_at=? WHERE id IN ({placeholders})",
                (now, *ids),
            )
        return rows


def _refresh_notice_sent_flag(conn: sqlite3.Connection, notice_id: int) -> None:
    counts = conn.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END) AS sent
        FROM notice_group_delivery
        WHERE notice_id = ?
        """,
        (notice_id,),
    ).fetchone()
    total = int(counts["total"] or 0)
    sent = int(counts["sent"] or 0)
    conn.execute(
        "UPDATE notices SET sent_to_whatsapp = ? WHERE id = ?",
        (1 if total > 0 and sent == total else 0, notice_id),
    )


def mark_delivery_success(delivery_id: int, notice_id: int) -> None:
    with connection() as conn:
        conn.execute(
            """
            UPDATE notice_group_delivery SET
                status='sent', sent_at=?, started_at=NULL,
                next_retry_at=NULL, last_error=NULL
            WHERE id=?
            """,
            (iso_utc(), delivery_id),
        )
        _refresh_notice_sent_flag(conn, notice_id)


def mark_delivery_failure(delivery_id: int, notice_id: int, error: str) -> bool:
    with connection() as conn:
        row = conn.execute("SELECT attempts FROM notice_group_delivery WHERE id=?", (delivery_id,)).fetchone()
        attempts = int(row["attempts"] if row else 0) + 1
        exhausted = attempts >= MAX_DELIVERY_ATTEMPTS
        conn.execute(
            """
            UPDATE notice_group_delivery SET
                status=?, attempts=?, started_at=NULL,
                next_retry_at=?, last_error=?
            WHERE id=?
            """,
            (
                "dead_letter" if exhausted else "failed",
                attempts,
                None if exhausted else retry_at(attempts),
                error[:1000],
                delivery_id,
            ),
        )
        _refresh_notice_sent_flag(conn, notice_id)
        return exhausted


def get_stats() -> dict[str, Any]:
    with connection() as conn:
        notice_rows = conn.execute(
            "SELECT processing_status AS status, COUNT(*) AS count FROM notices GROUP BY processing_status"
        ).fetchall()
        delivery_rows = conn.execute(
            "SELECT status, COUNT(*) AS count FROM notice_group_delivery GROUP BY status"
        ).fetchall()
        latest = conn.execute(
            "SELECT id, title, source, received_at, processing_status FROM notices ORDER BY id DESC LIMIT 5"
        ).fetchall()
    return {
        "notices": {row["status"]: row["count"] for row in notice_rows},
        "deliveries": {row["status"]: row["count"] for row in delivery_rows},
        "latest": [dict(row) for row in latest],
    }
