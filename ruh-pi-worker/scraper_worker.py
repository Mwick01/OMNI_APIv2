from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, SoupStrainer

import outbox_db
from config import (
    BOOTSTRAP_UNDATED_LIMIT,
    CONNECT_TIMEOUT_SECONDS,
    DOWNLOAD_BATCH_SIZE,
    DOWNLOAD_DIR,
    INITIAL_LOOKBACK_HOURS,
    MAX_FILE_MB,
    PORTALS,
    READ_TIMEOUT_SECONDS,
    SCAN_ROW_LIMIT,
    SCAN_OVERLAP_HOURS,
    EARLY_STOP_OLD_ROWS,
    SESSION_FILE,
    SESSION_MAX_AGE_MINS,
    SITE_PASSWORD,
    SITE_USERNAME,
    Portal,
    validate_scraper_config,
)
from utils import (
    build_notice_key,
    clean_site_timestamp_text,
    get_file_type,
    iso_utc,
    parse_iso,
    parse_site_timestamp,
    safe_filename,
    sha256_file,
    sl_now,
    utc_now,
)

logger = logging.getLogger(__name__)
USER_AGENT = "RUH-Notice-Bot/2.0 (+Raspberry-Pi; polite 5-minute checker)"


class AuthenticationError(RuntimeError):
    pass


class FileTooLargeError(RuntimeError):
    pass


class FOSMISClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def _save_session(self) -> None:
        payload = {
            "cookies": dict(self.session.cookies),
            "saved_at": iso_utc(),
        }
        temp = SESSION_FILE.with_suffix(".tmp")
        temp.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(temp, SESSION_FILE)
        os.chmod(SESSION_FILE, 0o600)

    def _load_session(self) -> bool:
        if not SESSION_FILE.exists():
            return False
        try:
            payload = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            saved_at = parse_iso(payload.get("saved_at"))
            if saved_at is None:
                return False
            age_minutes = (utc_now() - saved_at).total_seconds() / 60
            if age_minutes > SESSION_MAX_AGE_MINS:
                return False
            self.session.cookies.update(payload.get("cookies", {}))
            return True
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return False

    @staticmethod
    def _looks_logged_out(text: str) -> bool:
        lowered = (text or "").lower()
        return "sign in" in lowered and "uname" in lowered

    def login(self, portal: Portal | None = None) -> None:
        target = portal or PORTALS[0]
        response = self.session.post(
            target.login_url,
            data={"uname": SITE_USERNAME, "upwd": SITE_PASSWORD},
            timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
            allow_redirects=True,
        )
        response.raise_for_status()
        if self._looks_logged_out(response.text):
            raise AuthenticationError(
                f"Login rejected by {target.label}; check credentials or portal form"
            )
        self._save_session()
        logger.info("Login successful through %s", target.label)

    def ensure_session(self) -> None:
        loaded = self._load_session()
        if loaded:
            try:
                response = self.session.get(
                    PORTALS[0].notice_url,
                    timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
                )
                response.raise_for_status()
                if not self._looks_logged_out(response.text):
                    logger.info("Reusing saved FOSMIS session")
                    return
            except requests.RequestException:
                # A connectivity error is not proof that credentials are invalid.
                # Let a fresh login produce the final error for this cycle.
                pass
        self.login(PORTALS[0])

    def get_portal_page(self, portal: Portal) -> str:
        response = self.session.get(
            portal.notice_url,
            timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
        )
        response.raise_for_status()
        if self._looks_logged_out(response.text):
            logger.warning("Session rejected by %s; trying direct login", portal.label)
            self.login(portal)
            response = self.session.get(
                portal.notice_url,
                timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
            )
            response.raise_for_status()
            if self._looks_logged_out(response.text):
                raise AuthenticationError(f"Session is not valid for {portal.label}")
        return response.text


def parse_notice_rows(
    html: str,
    portal: Portal,
    *,
    cutoff_dt=None,
) -> list[dict[str, Any]]:
    """Parse newest notice rows, stopping after the overlap window is passed.

    The FOSMIS table is expected to be newest-first. To avoid stopping on one
    accidentally out-of-order row, EARLY_STOP_OLD_ROWS consecutive rows older
    than cutoff_dt are required before the scan ends. Rows inside the overlap
    window are still deduplicated later by notice_key.
    """
    soup = BeautifulSoup(
        html, "html.parser", parse_only=SoupStrainer("table")
    )
    parsed_rows: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    consecutive_old = 0
    stop_scan = False

    for table in soup.find_all("table"):
        if stop_scan:
            break

        for row in table.find_all("tr")[1:]:
            columns = row.find_all("td")
            if len(columns) < 4:
                continue

            # Parse the timestamp first. This lets us reject old rows before
            # doing title cleanup, URL parsing, quoting and SHA-256 key work.
            raw_date = columns[1].get_text(" ", strip=True)
            site_dt = parse_site_timestamp(raw_date)

            if cutoff_dt is not None and site_dt is not None and site_dt < cutoff_dt:
                consecutive_old += 1
                if consecutive_old >= EARLY_STOP_OLD_ROWS:
                    stop_scan = True
                    break
                continue

            # An in-window or undated row breaks the consecutive-old sequence.
            consecutive_old = 0

            raw_title = columns[2].get_text(" ", strip=True)
            title = re.sub(
                r"20\d{2}-\d{2}-\d{2}[/ ]\d{2}:\d{2}", "", raw_title
            ).replace("Download", "").strip()
            date_on_site = clean_site_timestamp_text(raw_date)

            link = columns[3].find("a", href=True)
            if not link:
                continue

            href = link.get("href", "").strip()
            full_url = urljoin(portal.notice_url, href)
            parsed_url = urlparse(full_url)
            query_params = parse_qs(parsed_url.query)

            if "fname" in query_params and query_params["fname"]:
                original_filename = query_params["fname"][0]
                download_url = portal.download_base + quote(original_filename, safe="")
            else:
                encoded_path = quote(parsed_url.path, safe="/:@!$&'()*+,;=")
                download_url = parsed_url._replace(path=encoded_path).geturl()
                original_filename = safe_filename(href)

            notice_key = build_notice_key(
                portal.name, title, date_on_site, download_url
            )
            if notice_key in seen_keys:
                continue
            seen_keys.add(notice_key)

            parsed_rows.append(
                {
                    "notice_key": notice_key,
                    "source": portal.name,
                    "title": title,
                    "date_on_site": date_on_site,
                    "site_dt": site_dt,
                    "site_timestamp": site_dt.isoformat() if site_dt else None,
                    "download_url": download_url,
                    "original_filename": original_filename,
                }
            )

            # Hard cap during traversal instead of parsing the whole history
            # and slicing only at the end.
            if len(parsed_rows) >= SCAN_ROW_LIMIT:
                stop_scan = True
                break

    return parsed_rows


def stage_portal_rows(portal: Portal, rows: list[dict[str, Any]]) -> tuple[int, int]:
    state = outbox_db.get_portal_state(portal.name)
    first_successful_run = not bool(state["bootstrapped"])
    bootstrap_cutoff = sl_now() - timedelta(hours=INITIAL_LOOKBACK_HOURS)
    undated_used = 0
    batch: list[dict[str, Any]] = []

    for item in rows:
        baseline_ignored = False
        if first_successful_run:
            site_dt = item["site_dt"]
            if site_dt is None:
                baseline_ignored = undated_used >= BOOTSTRAP_UNDATED_LIMIT
                undated_used += 1
            else:
                baseline_ignored = site_dt < bootstrap_cutoff

        staged_item = dict(item)
        staged_item["baseline_ignored"] = baseline_ignored
        batch.append(staged_item)

    # One SQLite connection + one commit for the whole portal scan.
    newly_queued, baseline_count = outbox_db.insert_notices_batch(batch)

    timestamps = [item["site_dt"] for item in rows if item["site_dt"]]
    max_timestamp = max(timestamps).isoformat() if timestamps else None
    outbox_db.mark_portal_success(portal.name, max_timestamp)
    return newly_queued, baseline_count


def scrape_portals(client: FOSMISClient) -> None:
    for portal in PORTALS:
        if not outbox_db.portal_is_due(portal.name):
            logger.info("%s is in connection backoff; skipping this cycle", portal.label)
            continue

        try:
            state = outbox_db.get_portal_state(portal.name)
            cutoff_dt = None
            if state["bootstrapped"] and state["last_seen_site_ts"]:
                last_seen = parse_iso(state["last_seen_site_ts"])
                if last_seen is not None:
                    cutoff_dt = last_seen - timedelta(hours=SCAN_OVERLAP_HOURS)

            started = time.perf_counter()
            html = client.get_portal_page(portal)
            fetched = time.perf_counter()

            rows = parse_notice_rows(html, portal, cutoff_dt=cutoff_dt)
            parsed = time.perf_counter()

            if not rows:
                # A bootstrapped portal may legitimately have no rows inside
                # the overlap window only if the table/order changed. Treat it
                # as an error so the cursor is not advanced silently.
                raise RuntimeError("No notice rows found in the expected scan window")

            queued, baseline = stage_portal_rows(portal, rows)
            staged = time.perf_counter()

            logger.info(
                "%s: scanned=%d queued_new=%d baseline_ignored=%d "
                "timing(fetch=%.2fs parse=%.2fs db=%.2fs total=%.2fs)",
                portal.label,
                len(rows),
                queued,
                baseline,
                fetched - started,
                parsed - fetched,
                staged - parsed,
                staged - started,
            )
        except Exception as exc:
            outbox_db.mark_portal_failure(portal.name, str(exc))
            logger.exception("Could not scrape %s: %s", portal.label, exc)


def _write_html_notice(response: requests.Response, destination: Path) -> tuple[Path, str]:
    response.encoding = response.encoding or "utf-8"
    if FOSMISClient._looks_logged_out(response.text):
        raise AuthenticationError("Download request returned the login page")

    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = "\n".join(
        line.strip()
        for line in soup.get_text(separator="\n").splitlines()
        if line.strip()
    )

    final_path = destination.with_suffix(".txt")
    temp_path = final_path.with_suffix(final_path.suffix + ".part")
    with temp_path.open("w", encoding="utf-8") as file:
        file.write(text)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp_path, final_path)
    return final_path, "txt"


def _write_binary_notice(response: requests.Response, destination: Path) -> tuple[Path, str]:
    max_bytes = MAX_FILE_MB * 1024 * 1024
    content_length = response.headers.get("Content-Length")
    if content_length and int(content_length) > max_bytes:
        raise FileTooLargeError(
            f"File is {int(content_length) / 1024 / 1024:.1f} MB; limit is {MAX_FILE_MB} MB"
        )

    temp_path = destination.with_suffix(destination.suffix + ".part")
    total = 0
    with temp_path.open("wb") as file:
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                raise FileTooLargeError(f"Download exceeded {MAX_FILE_MB} MB")
            file.write(chunk)
        file.flush()
        os.fsync(file.fileno())

    os.replace(temp_path, destination)
    return destination, get_file_type(destination.name)


def download_notice(client: FOSMISClient, row: Any) -> tuple[Path, str, str]:
    source_dir = DOWNLOAD_DIR / row["source"]
    source_dir.mkdir(parents=True, exist_ok=True)

    filename = safe_filename(row["original_filename"] or "notice_file")
    destination = source_dir / f"{row['notice_key'][:12]}_{filename}"

    response = client.session.get(
        row["download_url"],
        timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
        stream=True,
    )
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "").lower()
    original_type = get_file_type(filename)

    try:
        if "text/html" in content_type or original_type in {"html", "htm"}:
            final_path, file_type = _write_html_notice(response, destination)
        else:
            final_path, file_type = _write_binary_notice(response, destination)
    except Exception:
        for candidate in (
            destination.with_suffix(destination.suffix + ".part"),
            destination.with_suffix(".txt.part"),
        ):
            candidate.unlink(missing_ok=True)
        raise

    file_hash = sha256_file(final_path)
    return final_path, file_type, file_hash


def download_pending(client: FOSMISClient) -> None:
    rows = outbox_db.get_download_due(DOWNLOAD_BATCH_SIZE)
    if not rows:
        logger.info("No notice files waiting for download")
        return

    logger.info("Downloading %d queued notice file(s)", len(rows))
    for row in rows:
        try:
            final_path, file_type, file_hash = download_notice(client, row)
            outbox_db.mark_download_success(
                row["id"],
                local_file_path=str(final_path),
                file_type=file_type,
                file_sha256=file_hash,
            )
            logger.info("Downloaded [%s] %s", row["source"], row["title"][:80])
        except Exception as exc:
            outbox_db.mark_download_failed(row["id"], str(exc))
            logger.exception("Download failed for %s: %s", row["title"][:80], exc)


def run_scraper_cycle() -> None:
    validate_scraper_config()
    client = FOSMISClient()
    client.ensure_session()
    scrape_portals(client)
    download_pending(client)
