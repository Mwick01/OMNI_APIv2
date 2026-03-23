import sqlite3
from datetime import datetime

DB_PATH = "database.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS notices (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            title           TEXT,
            url             TEXT UNIQUE,
            file_path       TEXT,
            file_type       TEXT,
            date_on_site    TEXT,
            downloaded_at   TEXT,
            sent_to_whatsapp INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def insert_notice(title, url, file_path, file_type, date_on_site):
    """Insert notice. Returns new ID if new, None if duplicate."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO notices (title, url, file_path, file_type, date_on_site, downloaded_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (title, url, file_path, file_type, date_on_site, datetime.now().isoformat()))
        conn.commit()
        return c.lastrowid
    except sqlite3.IntegrityError:
        return None  # Already exists
    finally:
        conn.close()


def get_unsent_notices():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM notices WHERE sent_to_whatsapp = 0 ORDER BY date_on_site DESC")
    rows = c.fetchall()
    conn.close()
    return rows


def mark_as_sent(notice_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE notices SET sent_to_whatsapp = 1 WHERE id = ?", (notice_id,))
    conn.commit()
    conn.close()
