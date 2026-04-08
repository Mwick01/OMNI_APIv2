import os
import re
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs, quote
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Import from your other local files
from database import init_db, insert_notice
from ai_processor import analyze_notice

load_dotenv()

LOGIN_URL    = os.getenv("LOGIN_URL")
NOTICE_URL   = os.getenv("NOTICE_URL")
DOWNLOAD_DIR = "downloads"
SESSION_FILE = "session.json"
SESSION_MAX_AGE_MINS = 6

USERNAME = os.getenv("SITE_USERNAME")
PASSWORD = os.getenv("SITE_PASSWORD")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def safe_filename(url):
    name = os.path.basename(url.split("?")[0])
    name = re.sub(r"[\\/:*?\"<>|&=]", "_", name)
    return name or "unknown_file"


def get_file_type(filename):
    return Path(filename).suffix.lower().lstrip(".") or "unknown"


def is_within_one_month(date_text):
    try:
        # Use regex to find the strict YYYY-MM-DD pattern, ignoring any garbage "1"s
        match = re.search(r"\d{4}-\d{2}-\d{2}", date_text)
        if not match: 
            return True
        notice_date = datetime.strptime(match.group(0), "%Y-%m-%d")
        return (datetime.now() - notice_date).days <= 30
    except Exception:
        return True


def save_session(session):
    data = {
        "cookies": dict(session.cookies),
        "saved_at": datetime.now().isoformat(),
    }
    with open(SESSION_FILE, "w") as f:
        json.dump(data, f)


def load_session():
    if not os.path.exists(SESSION_FILE):
        return None
    try:
        with open(SESSION_FILE) as f:
            data = json.load(f)
        saved_at = datetime.fromisoformat(data["saved_at"])
        age_mins = (datetime.now() - saved_at).total_seconds() / 60
        if age_mins > SESSION_MAX_AGE_MINS:
            return None
        session = requests.Session()
        session.cookies.update(data["cookies"])
        return session
    except Exception:
        return None


def login():
    session = requests.Session()
    payload = {"uname": USERNAME, "upwd": PASSWORD}
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = session.post(LOGIN_URL, data=payload, headers=headers, timeout=15)
        if "Sign In" not in response.text:
            save_session(session)
            return session
        return None
    except Exception:
        return None


def get_session():
    session = load_session()
    if session:
        try:
            resp = session.get(NOTICE_URL, timeout=10)
            if "Sign In" in resp.text or resp.url != NOTICE_URL:
                return login()
            return session
        except Exception:
            return login()
    return login()


def scrape_and_download():
    init_db()
    session = get_session()
    if not session:
        print("❌ Could not log in to FOSMIS.")
        return

    print("🔍 Checking notices...")
    response = session.get(NOTICE_URL, timeout=15)
    soup = BeautifulSoup(response.text, "html.parser")

    tables = soup.find_all("table")
    if not tables:
        print("❌ No tables found on page")
        return

    recent_rows = []
    for table in tables:
        for row in table.find_all("tr")[1:]:
            tds = row.find_all("td")
            if len(tds) < 4:
                continue
            date_text = tds[1].get_text(strip=True)
            if is_within_one_month(date_text):
                recent_rows.append(row)

    print(f"📋 Found {len(recent_rows)} notices from the last 30 days")

    new_count = 0

    for row in recent_rows:
        tds = row.find_all("td")
        
        # Grab the messy raw text
        raw_date = tds[1].get_text(strip=True)
        raw_title = tds[2].get_text(strip=True)
        
        # Clean the date so the database only saves '2026-03-23/16:07'
        date_match = re.search(r"\d{4}-\d{2}-\d{2}[/ ]\d{2}:\d{2}", raw_date)
        date_text = date_match.group(0) if date_match else raw_date
        
        # Clean the title: remove "Download" AND any date/time patterns
        title = raw_title.replace("Download", "").strip()
        title = re.sub(r"\d{4}-\d{2}-\d{2}[/ ]\d{2}:\d{2}", "", title).strip()
        
        dl_link = tds[3].find("a", href=True)

        if not dl_link:
            continue

        href      = dl_link.get("href", "")
        full_url  = urljoin(NOTICE_URL, href)
        
        # --- THE DIRECT BYPASS HACK ---
        parsed_url = urlparse(full_url)
        query_params = parse_qs(parsed_url.query)
        
        if "fname" in query_params:
            real_filename = query_params["fname"][0]
            safe_fname = quote(real_filename)
            direct_dl_url = f"https://paravi.ruh.ac.lk/fosmis2019/downloads/Notices/{safe_fname}"
            filename = safe_filename(real_filename)
        else:
            direct_dl_url = full_url
            filename = safe_filename(href)
        # ------------------------------

        file_type = get_file_type(filename)
        filepath  = os.path.join(DOWNLOAD_DIR, filename)

        # Quick check: if the file exists locally, we likely already processed it.
        # This saves the server from downloading and running AI on old files every 15 minutes.
        if os.path.exists(filepath) or os.path.exists(Path(filepath).with_suffix('.txt')):
            continue

        try:
            print(f"\n⬇️ Downloading: {title[:40]}...")
            file_resp = session.get(direct_dl_url, timeout=20)
            content_type = file_resp.headers.get("Content-Type", "").lower()
            file_text = ""

            # --- PROCESS HTML FILES ---
            if "text/html" in content_type or file_type in ["html", "htm"]:
                file_resp.encoding = "utf-8"
                page_soup = BeautifulSoup(file_resp.text, "html.parser")
                
                for tag in page_soup(["script", "style"]):
                    tag.decompose()
                
                file_text = "\n".join(
                    line.strip() for line in page_soup.get_text(separator="\n").split("\n") if line.strip()
                )
                
                filename  = Path(filename).stem + ".txt"
                filepath  = os.path.join(DOWNLOAD_DIR, filename)
                file_type = "txt"
                
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(file_text)

            # --- PROCESS PDF & OTHER FILES ---
            else:
                with open(filepath, "wb") as f:
                    f.write(file_resp.content)
                
            
            # --- AI ANALYSIS ---
            subject_code, subject_name, degree_programme, semester_exam, deadln, summ = None, None, None, None, None, None

            #print("  🤖 Running ChatGPT Analysis...")
            #ai_data = analyze_notice(title, filepath, file_type)

            
            # --- 🛠️ TEMPORARY FAKE AI FOR TESTING (FREE) 🛠️ ---
            print("  🤖 Skipping actual AI to save money (using fake data)...")
            ai_data = {
                "is_exam_center": False,
                "course_name": "TEST 101 - Intro to Saving Money",
                "deadline": "December 31st, 2026",
                "summary": "This is a fake AI summary just to test that the WhatsApp layout is looking beautiful without wasting API credits."
            }
            # ----------------------------------------------------


            if ai_data:
                if ai_data.get("is_exam_center"):
                    print("    ⏭ Exam center detected. Skipping deep summary.")
                else:
                    subject_code     = ai_data.get("subject_code")
                    subject_name     = ai_data.get("subject_name")
                    degree_programme = ai_data.get("degree_programme")
                    semester_exam    = ai_data.get("semester_exam")
                    deadln           = ai_data.get("deadline")
                    summ             = ai_data.get("summary")
                    print(f"    ✅ Subject: {subject_name} ({subject_code}) | Deadline: {deadln}")

            # --- SAVE TO DATABASE ---
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
                deadline=deadln,
                summary=summ
            )

            if notice_id:
                print(f"  💾 Saved new notice to database.")
                new_count += 1
            else:
                print(f"  ⏭ Already in database.")

        except Exception as e:
            print(f"  ❌ Error processing {filename}: {e}")

    print(f"\n✅ Scraping complete. {new_count} new notice(s) prepared for WhatsApp.")


if __name__ == "__main__":
    scrape_and_download()