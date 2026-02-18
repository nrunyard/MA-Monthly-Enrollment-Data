"""
update_data.py
==============
Called by GitHub Actions to:
  --step download  : Download the latest CMS monthly enrollment file
  --step combine   : Rebuild combined_enrollment.csv from all downloaded files
  --step upload    : Push combined_enrollment.csv to Google Drive

Secrets required in GitHub (Settings → Secrets → Actions):
  GDRIVE_CREDENTIALS  : Contents of your Google service account JSON key file
  GDRIVE_FILE_ID      : The Google Drive file ID of your combined_enrollment.csv
                        (the part between /d/ and /view in the share link)
"""

import argparse
import json
import logging
import os
import re
import time
import zipfile
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

CMS_BASE = "https://www.cms.gov"
SUBPAGE_PATTERN = (
    "/data-research/statistics-trends-and-reports/"
    "medicare-advantagepart-d-contract-and-enrollment-data/"
    "monthly-ma-enrollment-state/county/contract/"
    "ma-enrollment-scc-{period}"
)
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CMS-AutoUpdater/1.0)"}
DATA_DIR = Path("cms_ma_enrollment_data")
COMBINED_CSV = Path("combined_enrollment.csv")
MANIFEST = Path("downloaded_periods.txt")


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_current_period() -> str:
    today = date.today()
    # CMS releases last month's data around the 15th
    # We run on the 20th so previous month should be available
    if today.month == 1:
        return f"{today.year - 1}-12"
    return f"{today.year}-{today.month - 1:02d}"


def load_manifest() -> set:
    if MANIFEST.exists():
        return set(MANIFEST.read_text().splitlines())
    return set()


def save_manifest(periods: set):
    MANIFEST.write_text("\n".join(sorted(periods)))


def get_download_url(period: str) -> str | None:
    url = CMS_BASE + SUBPAGE_PATTERN.format(period=period)
    log.info("Checking sub-page for %s ...", period)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        log.warning("Could not fetch sub-page: %s", e)
        return None
    soup = BeautifulSoup(resp.text, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.search(r"\.(zip|csv)$", href, re.IGNORECASE):
            return href if href.startswith("http") else CMS_BASE + href
    return None


def download_period(period: str) -> bool:
    month_dir = DATA_DIR / period
    if month_dir.exists() and any(month_dir.iterdir()):
        log.info("[%s] Already downloaded.", period)
        return True

    file_url = get_download_url(period)
    if not file_url:
        log.warning("[%s] No download URL found.", period)
        return False

    log.info("[%s] Downloading %s", period, file_url)
    try:
        resp = requests.get(file_url, headers=HEADERS, timeout=120)
        resp.raise_for_status()
    except requests.RequestException as e:
        log.error("[%s] Download failed: %s", period, e)
        return False

    month_dir.mkdir(parents=True, exist_ok=True)
    raw = resp.content

    if file_url.lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(BytesIO(raw)) as zf:
                zf.extractall(month_dir)
                log.info("[%s] Extracted %d file(s).", period, len(zf.namelist()))
                return True
        except zipfile.BadZipFile:
            pass

    out = month_dir / f"MA_Enrollment_SCC_{period}.csv"
    out.write_bytes(raw)
    log.info("[%s] Saved to %s", period, out)
    return True


# ── Steps ─────────────────────────────────────────────────────────────────────

def step_download():
    period = get_current_period()
    log.info("Target period: %s", period)
    manifest = load_manifest()

    if period in manifest:
        log.info("Period %s already in manifest, nothing to do.", period)
        return

    success = download_period(period)
    if success:
        manifest.add(period)
        save_manifest(manifest)
        log.info("Manifest updated: %s", sorted(manifest))
    else:
        raise RuntimeError(f"Failed to download period {period}")


def step_combine():
    log.info("Combining all CSVs...")
    all_dfs = []
    csv_files = sorted(DATA_DIR.rglob("*.csv"))
    csv_files = [f for f in csv_files if "combined" not in f.name.lower()]

    if not csv_files:
        raise RuntimeError(f"No CSV files found under {DATA_DIR}")

    for csv_path in csv_files:
        # Period is the YYYY-MM folder directly under DATA_DIR
        try:
            period = csv_path.relative_to(DATA_DIR).parts[0]
        except Exception:
            period = "unknown"
        try:
            df = pd.read_csv(csv_path, dtype=str, encoding="latin-1")
            df.columns = [c.strip().strip('"') for c in df.columns]
            df.insert(0, "report_period", period)
            df.replace(".", "", inplace=True)
            df["Enrolled"] = pd.to_numeric(df["Enrolled"], errors="coerce")
            all_dfs.append(df)
            log.info("Loaded %s (%d rows)", csv_path.name, len(df))
        except Exception as e:
            log.warning("Could not read %s: %s", csv_path, e)

    combined = pd.concat(all_dfs, ignore_index=True)
    combined.to_csv(COMBINED_CSV, index=False)
    log.info("Combined CSV saved: %s (%d rows)", COMBINED_CSV, len(combined))


def step_upload():
    """Upload combined_enrollment.csv to Google Drive using a service account."""
    credentials_json = os.environ.get("GDRIVE_CREDENTIALS")
    file_id = os.environ.get("GDRIVE_FILE_ID")

    if not credentials_json:
        raise RuntimeError("GDRIVE_CREDENTIALS secret not set.")
    if not file_id:
        raise RuntimeError("GDRIVE_FILE_ID secret not set.")

    # Write credentials to a temp file
    creds_path = Path("/tmp/gdrive_creds.json")
    creds_path.write_text(credentials_json)

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        log.info("Installing google-api-python-client...")
        import subprocess
        subprocess.run(
            ["pip", "install", "google-api-python-client", "google-auth"],
            check=True
        )
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

    scopes = ["https://www.googleapis.com/auth/drive.file"]
    creds = service_account.Credentials.from_service_account_file(
        str(creds_path), scopes=scopes
    )
    service = build("drive", "v3", credentials=creds)

    media = MediaFileUpload(str(COMBINED_CSV), mimetype="text/csv", resumable=True)

    # Try updating the existing file first
    try:
        service.files().update(fileId=file_id, media_body=media).execute()
        log.info("Updated existing Google Drive file: %s", file_id)
    except Exception as e:
        log.warning("Could not update existing file (%s), uploading as new file...", e)
        # Fall back: search for existing file by name and update it, or create new
        query = f"name = '{COMBINED_CSV.name}' and trashed = false"
        results = service.files().list(q=query, fields="files(id, name)").execute()
        existing = results.get("files", [])
        if existing:
            existing_id = existing[0]["id"]
            media2 = MediaFileUpload(str(COMBINED_CSV), mimetype="text/csv", resumable=True)
            service.files().update(fileId=existing_id, media_body=media2).execute()
            log.info("Updated file by name search, ID: %s", existing_id)
        else:
            # Create brand new file
            file_metadata = {"name": COMBINED_CSV.name, "mimeType": "text/csv"}
            media2 = MediaFileUpload(str(COMBINED_CSV), mimetype="text/csv", resumable=True)
            new_file = service.files().create(body=file_metadata, media_body=media2, fields="id").execute()
            new_id = new_file.get("id")
            log.info("Created new Google Drive file. New ID: %s", new_id)
            log.warning(
                "

*** ACTION REQUIRED ***
"
                "A new file was created on Google Drive with ID: %s
"
                "Update your GDRIVE_FILE_ID secret and dashboard_app.py with this new ID.
"
                "Then share the new file publicly so the dashboard can read it.
",
                new_id
            )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--step", choices=["download", "combine", "upload"], required=True)
    args = p.parse_args()

    if args.step == "download":
        step_download()
    elif args.step == "combine":
        step_combine()
    elif args.step == "upload":
        step_upload()


if __name__ == "__main__":
    main()
