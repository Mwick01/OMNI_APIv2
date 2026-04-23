import sqlite3
from datetime import datetime

DB_PATH = "database.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS notices (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            title            TEXT,
            url              TEXT UNIQUE,
            file_path        TEXT,
            file_type        TEXT,
            date_on_site     TEXT,
            downloaded_at    TEXT,
            sent_to_whatsapp INTEGER DEFAULT 0,
            subject_code     TEXT,
            subject_name     TEXT,
            degree_programme TEXT,
            semester_exam    TEXT,
            deadline         TEXT,
            summary          TEXT,
            source           TEXT DEFAULT 'green'
        )
    """)
    # Migrate existing DB — add missing columns safely
    existing = [row[1] for row in c.execute("PRAGMA table_info(notices)")]
    migrations = [
        ("subject_code",     "TEXT"),
        ("subject_name",     "TEXT"),
        ("degree_programme", "TEXT"),
        ("semester_exam",    "TEXT"),
        ("deadline",         "TEXT"),
        ("summary",          "TEXT"),
        ("source",           "TEXT"),
    ]
    for col, coltype in migrations:
        if col not in existing:
            c.execute(f"ALTER TABLE notices ADD COLUMN {col} {coltype}")
    conn.commit()
    conn.close()


def insert_notice(title, url, file_path, file_type, date_on_site,
                  subject_code=None, subject_name=None, degree_programme=None,
                  semester_exam=None, deadline=None, summary=None, source="green"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO notices
              (title, url, file_path, file_type, date_on_site, downloaded_at,
               subject_code, subject_name, degree_programme, semester_exam,
               deadline, summary, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (title, url, file_path, file_type, date_on_site,
              datetime.now().isoformat(),
              subject_code, subject_name, degree_programme, semester_exam,
              deadline, summary, source))
        conn.commit()
        return c.lastrowid
    except sqlite3.IntegrityError:
        return None
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