"""
EEARTH Board of Directors — FastAPI Backend
Handles: authentication, user management, meetings, AI chat (streaming SSE),
         document processing, board member memory, and minutes generation.
"""

import json
import os
import time
import io
from pathlib import Path
from typing import Optional, List

import anthropic
from fastapi import FastAPI, HTTPException, Depends, Header, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from auth import create_token, verify_token, hash_password, verify_password
from database import db
from personas import BOARD_MEMBERS, build_system_prompt, list_members
from foundation_memory import get_foundation_memory, get_all_foundation_memories

# ─────────────────── App setup ───────────────────

app = FastAPI(title="EEARTH Board of Directors", version="1.0.0")


@app.get("/api/health")
async def health_check():
    """Unauthenticated health check for Render."""
    return {"status": "ok", "version": "1.0.0"}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
