import os
import re
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs, quote
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from database import init_db, insert_notice
from ai_processor import analyze_notice

load_dotenv()

DOWNLOAD_DIR     = "downloads"
SESSION_FILE     = "session.json"       # Single session for both portals
SESSION_MAX_AGE_MINS = 6

USERNAME = os.getenv("SITE_USERNAME")
PASSWORD = os.getenv("SITE_PASSWORD")

# ── Two portals — same session ────────────────────────────────────────────────
PORTALS = [
    {
        "name":       "green",
        "label":      "🟢 Green FOSMIS",
        "login_url":  os.getenv("LOGIN_URL_GREEN"),
        "notice_url": os.getenv("NOTICE_URL_GREEN"),
        "dl_base":    "https://paravi.ruh.ac.lk/fosmis2019/downloads/Notices/",
    },
    {
        "name":       "purple",
        "label":      "🟣 Purple FOSMIS",
        "login_url":  os.getenv("LOGIN_URL_PURPLE"),
        "notice_url": os.getenv("NOTICE_URL_PURPLE"),
        "dl_base":    "https://paravi.ruh.ac.lk/fosmis/downloads/Notices/",
    },
]

os.makedirs(DOWNLOAD_DIR, exist_ok=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def safe_filename(url):
    name = os.path.basename(url.split("?")[0])
    name = re.sub(r"[\\/:*?\"<>|&=]", "_", name)
    return name or "unknown_file"


def get_file_type(filename):
    return Path(filename).suffix.lower().lstrip(".") or "unknown"


def is_within_one_month(date_text):
    try:
        match = re.search(r"\d{4}-\d{2}-\d{2}", date_text)
        if not match:
            return True
        notice_date = datetime.strptime(match.group(0), "%Y-%m-%d")
        return (datetime.now() - notice_date).days <= 30
    except Exception:
        return True


def save_session(session):
    data = {"cookies": dict(session.cookies), "saved_at": datetime.now().isoformat()}
    with open(SESSION_FILE, "w") as f:
        json.dump(data, f)


def load_session():
    if not os.path.exists(SESSION_FILE):
        return None
    try:
        with open(SESSION_FILE) as f:
            data = json.load(f)
        saved_at = datetime.fromisoformat(data["saved_at"])
        if (datetime.now() - saved_at).total_seconds() / 60 > SESSION_MAX_AGE_MINS:
            return None
        session = requests.Session()
        session.cookies.update(data["cookies"])
        return session
    except Exception:
        return None


def login():
    """Login once to green FOSMIS — session works for both portals."""
    session = requests.Session()
    payload = {"uname": USERNAME, "upwd": PASSWORD}
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = session.post(
            PORTALS[0]["login_url"],   # Login via green portal
            data=payload, headers=headers, timeout=15
        )
        if "Sign In" not in response.text:
            save_session(session)
            print("✅ Login successful (session valid for both portals)")
            return session
        print("❌ Login failed. Check credentials.")
        return None
    except Exception as e:
        print(f"❌ Login error: {e}")
        return None


def get_session():
    """Get valid session — reuse if fresh, login otherwise."""
    session = load_session()
    if session:
        # Quick verify against green portal
        try:
            resp = session.get(PORTALS[0]["notice_url"], timeout=10)
            if "Sign In" in resp.text:
                print("⚠️ Session expired — re-logging in.")
                return login()
            print(f"♻️ Reusing existing session.")
            return session
        except Exception:
            return login()
    return login()


# ── Per-portal scraper ────────────────────────────────────────────────────────

def scrape_portal(session, portal):
    print(f"\n{'─'*50}")
    print(f"  {portal['label']}")
    print(f"{'─'*50}")

    try:
        response = session.get(portal["notice_url"], timeout=15)
    except Exception as e:
        print(f"  ❌ Could not reach {portal['label']}: {e}")
        return 0

    # If session was rejected for this portal, try hitting its login too
    if "Sign In" in response.text:
        print(f"  ⚠️ Session not valid for {portal['label']} — trying direct login...")
        try:
            session.post(portal["login_url"],
                data={"uname": USERNAME, "upwd": PASSWORD},
                headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            response = session.get(portal["notice_url"], timeout=15)
        except Exception as e:
            print(f"  ❌ Could not log in to {portal['label']}: {e}")
            return 0

    soup = BeautifulSoup(response.text, "html.parser")
    tables = soup.find_all("table")
    if not tables:
        print("  ❌ No tables found")
        return 0

    recent_rows = []
    for table in tables:
        for row in table.find_all("tr")[1:]:
            tds = row.find_all("td")
            if len(tds) < 4:
                continue
            if is_within_one_month(tds[1].get_text(strip=True)):
                recent_rows.append(row)

    print(f"  📋 Found {len(recent_rows)} notices from last 30 days")
    new_count = 0

    for row in recent_rows:
        tds = row.find_all("td")

        raw_date  = tds[1].get_text(strip=True)
        raw_title = tds[2].get_text(strip=True)

        date_match = re.search(r"\d{4}-\d{2}-\d{2}[/ ]\d{2}:\d{2}", raw_date)
        date_text  = date_match.group(0) if date_match else raw_date
        title = re.sub(r"\d{4}-\d{2}-\d{2}[/ ]\d{2}:\d{2}", "", raw_title).replace("Download", "").strip()

        dl_link = tds[3].find("a", href=True)
        if not dl_link:
            continue

        href     = dl_link.get("href", "")
        full_url = urljoin(portal["notice_url"], href)

        # Direct download URL
        parsed_url   = urlparse(full_url)
        query_params = parse_qs(parsed_url.query)
        if "fname" in query_params:
            real_filename = query_params["fname"][0]
            direct_dl_url = f"{portal['dl_base']}{quote(real_filename)}"
            filename      = safe_filename(real_filename)
        else:
            direct_dl_url = full_url
            filename      = safe_filename(href)

        file_type = get_file_type(filename)
        filepath  = os.path.join(DOWNLOAD_DIR, filename)

        # Skip if already downloaded
        if os.path.exists(filepath) or os.path.exists(Path(filepath).with_suffix(".txt")):
            continue

        try:
            print(f"\n  ⬇️  {title[:55]}...")
            file_resp    = session.get(direct_dl_url, timeout=20)
            content_type = file_resp.headers.get("Content-Type", "").lower()

            if "text/html" in content_type or file_type in ["html", "htm"]:
                file_resp.encoding = "utf-8"
                page_soup = BeautifulSoup(file_resp.text, "html.parser")
                for tag in page_soup(["script", "style"]):
                    tag.decompose()
                text = "\n".join(
                    line.strip() for line in
                    page_soup.get_text(separator="\n").split("\n") if line.strip()
                )
                filename  = Path(filename).stem + ".txt"
                filepath  = os.path.join(DOWNLOAD_DIR, filename)
                file_type = "txt"
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(text)
            else:
                with open(filepath, "wb") as f:
                    f.write(file_resp.content)

            # AI analysis
            subject_code = subject_name = degree_programme = None
            semester_exam = deadline = summary = None

            print("  🤖 Running AI analysis...")
            ai_data = analyze_notice(title, filepath, file_type)
            

            if ai_data and not ai_data.get("is_exam_center"):
                subject_code     = ai_data.get("subject_code")
                subject_name     = ai_data.get("subject_name")
                degree_programme = ai_data.get("degree_programme")
                semester_exam    = ai_data.get("semester_exam")
                deadline         = ai_data.get("deadline")
                summary          = ai_data.get("summary")

            notice_id = insert_notice(
                title=title,
                url=direct_dl_url,
                file_path=filepath,
                file_type=file_type,
                date_on_site=date_text,
                subject_code=subject_code,
                subject_name=subject_name,
                degree_programme=degree_programme,
                semester_exam=semester_exam,
                deadline=deadline,
                summary=summary,
                source=portal["name"],
            )

            if notice_id:
                print(f"  💾 Saved [{portal['name']}]: {title[:50]}")
                new_count += 1

        except Exception as e:
            print(f"  ❌ Error: {e}")

    return new_count


# ── Main ──────────────────────────────────────────────────────────────────────

def scrape_and_download():
    init_db()

    # Single login — works for both portals
    session = get_session()
    if not session:
        print("❌ Could not log in.")
        return

    total = 0
    for portal in PORTALS:
        total += scrape_portal(session, portal)

    print(f"\n✅ Done. {total} new notice(s) found across both portals.")


if __name__ == "__main__":
    scrape_and_download()