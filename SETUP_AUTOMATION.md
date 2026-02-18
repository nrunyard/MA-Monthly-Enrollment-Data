# Automation Setup Guide

This guide sets up GitHub Actions to automatically download new CMS
enrollment data every month and update your Google Drive CSV.

---

## What you need to do once

### 1. Create a Google Service Account

This lets GitHub upload to your Google Drive without your password.

1. Go to https://console.cloud.google.com
2. Create a new project (or use an existing one)
3. Go to **APIs & Services → Enable APIs** and enable the **Google Drive API**
4. Go to **APIs & Services → Credentials → Create Credentials → Service Account**
5. Give it any name (e.g. `github-uploader`), click Done
6. Click the service account → **Keys tab → Add Key → JSON**
7. A `.json` file will download — keep this safe

### 2. Share your Google Drive file with the service account

1. Open the `.json` key file and copy the `client_email` field
   (looks like `github-uploader@yourproject.iam.gserviceaccount.com`)
2. Go to Google Drive, right-click `combined_enrollment.csv` → Share
3. Paste that email address and give it **Editor** access
4. Click Send

### 3. Add secrets to GitHub

Go to your GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**

Add these two secrets:

| Secret Name | Value |
|-------------|-------|
| `GDRIVE_CREDENTIALS` | The entire contents of the `.json` key file you downloaded |
| `GDRIVE_FILE_ID` | `1A5HQIrH6umAsUGrP4IkZvPdVR7N9uxuc` (your file ID) |

### 4. Upload these files to your GitHub repo

- `update_data.py`
- `.github/workflows/update_enrollment_data.yml`
- `downloaded_periods.txt` (create an empty file with this name)

---

## How it works after setup

On the **20th of every month**, GitHub will automatically:
1. Download the latest CMS monthly enrollment file
2. Rebuild `combined_enrollment.csv`
3. Upload it to your Google Drive
4. Your Streamlit dashboard picks it up automatically on next load

You can also trigger it manually anytime:
- Go to your repo → **Actions** tab
- Click **Update MA Enrollment Data**
- Click **Run workflow**

---

## Files in this repo

| File | Purpose |
|------|---------|
| `dashboard_app.py` | Streamlit dashboard |
| `update_data.py` | Automation script |
| `requirements.txt` | Python dependencies |
| `downloaded_periods.txt` | Tracks which months have been downloaded |
| `.github/workflows/update_enrollment_data.yml` | GitHub Actions schedule |
| `MA_Contract_directory_2026_02.xlsx` | CMS plan directory (parent org mapping) |
