# EEARTH Board of Directors App — Deployment Guide

**Version:** 1.0  
**Platform:** Render.com (Python/FastAPI + SQLite + Anthropic API)  
**Estimated deploy time:** 20–30 minutes

---

## Prerequisites

Before deploying, you need:

1. A [Render.com](https://render.com) account (free tier works; Starter plan recommended for production)
2. An [Anthropic API key](https://console.anthropic.com) with access to `claude-opus-4-6` and `claude-sonnet-4-6`
3. Your `eearth-board/` folder pushed to a GitHub or GitLab repository

---

## Step 1 — Push Code to GitHub

Create a new GitHub repository and push the `eearth-board/` folder contents (not the outer folder, just what's inside):

```
your-repo/
  auth.py
  database.py
  foundation_memory.py
  main.py
  personas.py
  requirements.txt
  render.yaml
  Procfile
  static/
    index.html
```

---

## Step 2 — Create a New Web Service on Render

1. Go to [dashboard.render.com](https://dashboard.render.com)
2. Click **New → Web Service**
3. Connect your GitHub account and select your repository
4. Render will auto-detect `render.yaml` and pre-fill most settings

---

## Step 3 — Add Persistent Disk

1. In your service settings, go to **Disks**
2. Click **Add Disj**
3. Set:
   - **Name:** `eearth-data`
   - **Mount Path:** `/opt/render/project/src`
   - **Size:** 1 GB

---

## Step 4 — Set Environment Variables

| Key | Value | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | `sk-ant-...` | Your Anthropic API key |
| `ADMIN_EMAIL`| `kyour@email.com` | First admin account email |
| `ADMIN_PASSWORD`  | `YourStrongPassword!` | First admin account password |
| `DATABASE_PATH` | `/opt/render/project/src/eearth_board.db` | Must match disk mount path |

---

## Step 5 — Deploy

1. Click **Manual Deploy ₒ Deploy latest commit**
2. Watch build logs
3. App will be available at `your-app.onrender.com`

---

## File Summary

| File | Purpose |
|---|---|
| `main.py` | FastAPI backend |
| `personas.py` | Board member personas |
| `foundation_memory.py` | Permanent EEARTH knowledge |
| `database.py` | SQLite layer |
| `auth.py` | JWT authentication |
| `static/index.html` | React SPA frontend |

---

*EEARTH Board App — Built April 2026*
