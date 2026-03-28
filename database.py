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
            sent_to_whatsapp INTEGER DEFAULT 0,
            course_name     TEXT,
            deadline        TEXT,
            summary         TEXT
        )
    """)
    
    # Safely upgrade existing database with new columns
    try:
        c.execute("ALTER TABLE notices ADD COLUMN course_name TEXT")
        c.execute("ALTER TABLE notices ADD COLUMN deadline TEXT")
        c.execute("ALTER TABLE notices ADD COLUMN summary TEXT")
    except sqlite3.OperationalError:
        pass # Columns already exist, skip adding them

    conn.commit()
    conn.close()


def insert_notice(title, url, file_path, file_type, date_on_site, course_name=None, deadline=None, summary=None):
    """Insert notice with AI data. Returns new ID if new, None if duplicate."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO notices (title, url, file_path, file_type, date_on_site, downloaded_at, course_name, deadline, summary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (title, url, file_path, file_type, date_on_site, datetime.now().isoformat(), course_name, deadline, summary))
        conn.commit()
        return c.lastrowid
    except sqlite3.IntegrityError:
        return None  # Already exists
    finally:
        conn.close()

def get_unsent_notices():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM notices WHERE sent_to_whatsapp = 0 ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return rows

def mark_as_sent(notice_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE notices SET sent_to_whatsapp = 1 WHERE id = ?", (notice_id,))
    conn.commit()
    conn.close()