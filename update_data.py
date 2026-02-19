"""
update_data.py — GitHub Actions automation script
==================================================
Steps:
  --step download  : Download latest CMS monthly file
  --step combine   : Merge into combined_enrollment.csv.gz (rolling 24 months)

Usage:
  python update_data.py --step download
  python update_data.py --step combine
"""

import argparse
import gzip
import logging
import re
import shutil
import zipfile
from datetime import date
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

HEADERS      = {"User-Agent": "Mozilla/5.0 (compatible; CMS-Downloader/1.0)"}
CMS_BASE     = "https://www.cms.gov"
SUBPAGE_PAT  = (
    "/data-research/statistics-trends-and-reports/"
    "medicare-advantagepart-d-contract-and-enrollment-data/"
    "monthly-ma-enrollment-state/county/contract/ma-enrollment-scc-{period}"
)
DATA_DIR     = Path("cms_ma_enrollment_data")
COMBINED_GZ  = Path("combined_enrollment.csv.gz")
MANIFEST     = Path("downloaded_periods.txt")
ROLLING      = 24


def load_manifest() -> set:
    return set(MANIFEST.read_text().splitlines()) if MANIFEST.exists() else set()

def save_manifest(periods: set):
    MANIFEST.write_text("\n".join(sorted(periods)))

def current_period() -> str:
    t = date.today()
    # Run on 20th — previous month should be published
    m = t.month - 1 or 12
    y = t.year if t.month > 1 else t.year - 1
    return f"{y}-{m:02d}"

def get_download_url(period: str):
    url = CMS_BASE + SUBPAGE_PAT.format(period=period)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        log.warning("Could not fetch sub-page for %s: %s", period, e)
        return None
    soup = BeautifulSoup(resp.text, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.search(r"\.(zip|csv)$", href, re.IGNORECASE):
            return href if href.startswith("http") else CMS_BASE + href
    return None

def download_period(period: str) -> bool:
    out_dir = DATA_DIR / period
    if out_dir.exists() and any(out_dir.rglob("*.csv")):
        log.info("[%s] Already downloaded.", period)
        return True
    url = get_download_url(period)
    if not url:
        log.warning("[%s] No download URL found.", period)
        return False
    log.info("[%s] Downloading %s", period, url)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=120)
        resp.raise_for_status()
    except Exception as e:
        log.error("[%s] Download failed: %s", period, e)
        return False
    out_dir.mkdir(parents=True, exist_ok=True)
    if url.lower().endswith(".zip"):
        with zipfile.ZipFile(BytesIO(resp.content)) as zf:
            zf.extractall(out_dir)
    else:
        (out_dir / f"enrollment_{period}.csv").write_bytes(resp.content)
    log.info("[%s] Saved.", period)
    return True


def step_download():
    period = current_period()
    log.info("Target period: %s", period)
    manifest = load_manifest()
    if period in manifest:
        log.info("Already have %s, nothing to do.", period)
        return
    if download_period(period):
        manifest.add(period)
        save_manifest(manifest)
    else:
        raise RuntimeError(f"Failed to download {period}")


def read_existing_gz() -> pd.DataFrame | None:
    if not COMBINED_GZ.exists():
        return None
    try:
        with gzip.open(COMBINED_GZ, "rb") as f:
            return pd.read_csv(f, dtype=str, encoding="latin-1")
    except Exception as e:
        log.warning("Could not read existing gz: %s", e)
        return None


def step_combine():
    # Load newly downloaded CSVs
    new_dfs = []
    for csv_path in sorted(DATA_DIR.rglob("*.csv")):
        try:
            period = csv_path.relative_to(DATA_DIR).parts[0]
        except Exception:
            continue
        try:
            df = pd.read_csv(csv_path, dtype=str, encoding="latin-1")
            df.columns = [c.strip().strip('"') for c in df.columns]
            df.insert(0, "report_period", period)
            df.replace(".", "", inplace=True)
            df["Enrolled"] = pd.to_numeric(df["Enrolled"], errors="coerce")
            new_dfs.append(df)
            log.info("Loaded %s (%d rows)", csv_path.name, len(df))
        except Exception as e:
            log.warning("Could not read %s: %s", csv_path, e)

    # Merge with existing combined data
    existing = read_existing_gz()
    if new_dfs:
        new_data   = pd.concat(new_dfs, ignore_index=True)
        new_periods = set(new_data["report_period"].unique())
        if existing is not None:
            existing["Enrolled"] = pd.to_numeric(existing["Enrolled"], errors="coerce")
            existing = existing[~existing["report_period"].isin(new_periods)]
            combined = pd.concat([existing, new_data], ignore_index=True)
        else:
            combined = new_data
    elif existing is not None:
        log.info("No new CSVs found, using existing combined data.")
        combined = existing
    else:
        raise RuntimeError("No data found anywhere.")

    # Enforce rolling 24-month window
    all_periods = sorted(combined["report_period"].unique())
    if len(all_periods) > ROLLING:
        keep = all_periods[-ROLLING:]
        combined = combined[combined["report_period"].isin(keep)]
        log.info("Trimmed to %d periods: %s → %s", ROLLING, keep[0], keep[-1])

    combined = combined.sort_values("report_period")

    # Write compressed
    with gzip.open(COMBINED_GZ, "wb") as f:
        combined.to_csv(f, index=False)

    log.info("Saved %s (%d rows, %d periods)",
             COMBINED_GZ, len(combined), combined["report_period"].nunique())

    # Clean up raw downloaded files to save space
    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)
        log.info("Cleaned up %s", DATA_DIR)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--step", choices=["download", "combine"], required=True)
    args = p.parse_args()
    if args.step == "download":
        step_download()
    else:
        step_combine()

if __name__ == "__main__":
    main()
