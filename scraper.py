import os
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from database import init_db, insert_notice

load_dotenv()

LOGIN_URL    = os.getenv("LOGIN_URL")
NOTICE_URL   = os.getenv("NOTICE_URL")
DOWNLOAD_DIR = "downloads"

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
        date_str = date_text.replace("/", " ").split(" ")[0].strip()
        notice_date = datetime.strptime(date_str, "%Y-%m-%d")
        return (datetime.now() - notice_date).days <= 30
    except Exception:
        return True


def clean_title(text):
    """Remove trailing 'Download' word from titles."""
    return re.sub(r"\s*Download\s*$", "", text, flags=re.IGNORECASE).strip()


def login():
    session = requests.Session()
    payload = {"uname": USERNAME, "upwd": PASSWORD}
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = session.post(LOGIN_URL, data=payload, headers=headers, timeout=15)
        if "Sign In" not in response.text:
            print("✅ Login successful!")
            return session
        else:
            print("❌ Login failed. Check credentials.")
            return None
    except Exception as e:
        print(f"❌ Login error: {e}")
        return None


def scrape_and_download():
    init_db()
    session = login()
    if not session:
        return

    print("🔍 Checking notices...")
    response = session.get(NOTICE_URL, timeout=15)
    soup = BeautifulSoup(response.text, "html.parser")

    tables = soup.find_all("table")
    if not tables:
        print("❌ No tables found on page")
        return

    # Collect rows from all tables, filter to last 30 days
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

        # Columns: No | Date | Title | Download
        date_text = tds[1].get_text(strip=True)
        title     = clean_title(tds[2].get_text(strip=True))  # ← clean title
        dl_link   = tds[3].find("a", href=True)

        if not dl_link:
            continue

        href      = dl_link.get("href", "")
        full_url  = urljoin(NOTICE_URL, href)
        filename  = safe_filename(href)
        file_type = get_file_type(filename)
        filepath  = os.path.join(DOWNLOAD_DIR, filename)

        try:
            file_resp = session.get(full_url, timeout=20)

            if "text/html" in file_resp.headers.get("Content-Type", ""):
                # Force UTF-8 decoding to handle Sinhala and other Unicode
                file_resp.encoding = "utf-8"
                page_soup = BeautifulSoup(file_resp.content, "html.parser")
                notice_div = page_soup.find("div", id="m") or page_soup
                for tag in notice_div(["script", "style"]):
                    tag.decompose()
                text = "\n".join(
                    line.strip() for line in notice_div.get_text(separator="\n").split("\n")
                )
                filename  = Path(filename).stem + ".txt"
                filepath  = os.path.join(DOWNLOAD_DIR, filename)
                file_type = "txt"
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(text)
            else:
                with open(filepath, "wb") as f:
                    f.write(file_resp.content)

            notice_id = insert_notice(
                title=title,
                url=full_url,
                file_path=filepath,
                file_type=file_type,
                date_on_site=date_text,
            )

            if notice_id is None:
                print(f"  ⏭ Already exists: {title}")
                continue

            print(f"  ✅ New: {title}")
            new_count += 1

        except Exception as e:
            print(f"  ❌ Error with {filename}: {e}")

    print(f"\n✅ Done. {new_count} new notice(s) found.")


if __name__ == "__main__":
    scrape_and_download()
