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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


@app.on_event("startup")
async def startup():
    db.init()
    # Seed admin user from environment (or defaults for local dev)
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@eearth.com")
    admin_password = os.environ.get("ADMIN_PASSWORD", "EEARTH2026!")
    if not db.get_user_by_email(admin_email):
        db.create_user(
            email=admin_email,
            name="Administrator",
            password_hash=hash_password(admin_password),
            role="admin",
        )
        print(f"[startup] Admin user created: {admin_email}")


# ─────────────────── Auth helpers ───────────────────

async def get_current_user(authorization: str = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    token = authorization.split(" ", 1)[1]
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid or expired token")
    user = db.get_user(user_id)
    if not user or not user["is_active"]:
        raise HTTPException(401, "User inactive or not found")
    return user


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "Admin access required")
    return user


def get_anthropic_client() -> anthropic.Anthropic:
    if not ANTHROPIC_API_KEY:
        raise HTTPException(500, "ANTHROPIC_API_KEY not configured on server")
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ─────────────────── AUTH ROUTES ───────────────────

class LoginRequest(BaseModel):
    email: str
    password: str


@app.post("/api/auth/login")
async def login(req: LoginRequest):
    user = db.get_user_by_email(req.email)
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password")
    if not user["is_active"]:
        raise HTTPException(401, "Account is inactive. Contact your administrator.")
    token = create_token(user["id"])
    return {
        "token": token,
        "user": {"id": user["id"], "email": user["email"], "name": user["name"], "role": user["role"]},
    }


@app.get("/api/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return {"id": user["id"], "email": user["email"], "name": user["name"], "role": user["role"]}


# ─────────────────── USER MANAGEMENT (Admin only) ───────────────────

class CreateUserRequest(BaseModel):
    email: str
    name: str
    password: str
    role: str = "user"


class UpdateUserRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


@app.get("/api/users")
async def list_users(admin: dict = Depends(require_admin)):
    return db.list_users()


@app.post("/api/users")
async def create_user(req: CreateUserRequest, admin: dict = Depends(require_admin)):
    if db.get_user_by_email(req.email):
        raise HTTPException(400, "Email already registered")
    user_id = db.create_user(
        email=req.email,
        name=req.name,
        password_hash=hash_password(req.password),
        role=req.role,
    )
    return {"id": user_id, "message": "User created successfully"}


@app.patch("/api/users/{user_id}")
async def update_user(user_id: int, req: UpdateUserRequest, admin: dict = Depends(require_admin)):
    updates = {}
    if req.name is not None:
        updates["name"] = req.name
    if req.email is not None:
        updates["email"] = req.email
    if req.password is not None:
        updates["password_hash"] = hash_password(req.password)
    if req.role is not None:
        updates["role"] = req.role
    if req.is_active is not None:
        updates["is_active"] = 1 if req.is_active else 0
    db.update_user(user_id, updates)
    return {"message": "User updated"}


@app.delete("/api/users/{user_id}")
async def delete_user(user_id: int, admin: dict = Depends(require_admin)):
    db.delete_user(user_id)
    return {"message": "User deleted"}


# ─────────────────── BOARD MEMBERS ───────────────────

@app.get("/api/board-members")
async def get_board_members(user: dict = Depends(get_current_user)):
    return list_members()


# ─────────────────── MEETINGS ───────────────────

class CreateMeetingRequest(BaseModel):
    type: str  # "1on1" | "document" | "board"
    title: str
    board_members: Optional[List[str]] = None
    agenda: Optional[List[str]] = None


@app.get("/api/meetings")
async def list_meetings(user: dict = Depends(get_current_user)):
    return db.list_meetings(user["id"])


@app.post("/api/meetings")
async def create_meeting(req: CreateMeetingRequest, user: dict = Depends(get_current_user)):
    # Validate board members
    board_members = req.board_members or []
    for bm in board_members:
        if bm not in BOARD_MEMBERS:
            raise HTTPException(400, f"Unknown board member: {bm}")

    meeting_id = db.create_meeting(
        user_id=user["id"],
        type=req.type,
        title=req.title,
        board_members=board_members,
        agenda=req.agenda or [],
    )
    return {"id": meeting_id}


@app.get("/api/meetings/{meeting_id}")
async def get_meeting(meeting_id: int, user: dict = Depends(get_current_user)):
    meeting = db.get_meeting(meeting_id, user["id"])
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    return meeting


@app.delete("/api/meetings/{meeting_id}")
async def delete_meeting(meeting_id: int, user: dict = Depends(get_current_user)):
    db.delete_meeting(meeting_id, user["id"])
    return {"message": "Meeting deleted"}


@app.post("/api/meetings/{meeting_id}/agenda")
async def update_agenda(meeting_id: int, body: dict, user: dict = Depends(get_current_user)):
    meeting = db.get_meeting(meeting_id, user["id"])
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    db.update_meeting_agenda(meeting_id, body.get("agenda", []))
    return {"message": "Agenda updated"}


# ─────────────────── DOCUMENT UPLOAD ───────────────────

@app.post("/api/meetings/{meeting_id}/document")
async def upload_document(
    meeting_id: int,
    file: Optional[UploadFile] = File(None),
    text: Optional[str] = Form(None),
    user: dict = Depends(get_current_user),
):
    meeting = db.get_meeting(meeting_id, user["id"])
    if not meeting:
        raise HTTPException(404, "Meeting not found")

    content = ""
    filename = "pasted-text.txt"

    if file and file.filename:
        filename = file.filename
        file_bytes = await file.read()
        fname_lower = filename.lower()

        if fname_lower.endswith(".pdf"):
            try:
                import pdfplumber
                with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                    pages = []
                    for page in pdf.pages:
                        t = page.extract_text()
                        if t:
                            pages.append(t)
                    content = "\n\n".join(pages)
            except Exception as e:
                raise HTTPException(400, f"Could not parse PDF: {e}")
        elif fname_lower.endswith(".docx"):
            try:
                from docx import Document
                doc = Document(io.BytesIN(file_bytes))
                content = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            except Exception as e:
                raise HTTPException(400, f"Could not parse DOCX: {e}")
        else:
            content = file_bytes.decode("utf-8", errors="replace")
    elif text:
        content = text
    else:
        raise HTTPException(400, "Provide either a file or text content")

    if not content.strip():
        raise HTTPException(400, "Document appears to be empty")

    doc_id = db.save_document(meeting_id, filename, content)
    return {"id": doc_id, "filename": filename, "characters": len(content)}


# ─────────────────── CHAT (1-on-1 and Document Review) ───────────────────

class ChatRequest(BaseModel):
    board_member: str
    message: str
    use_memory: bool = True
    agenda_item: Optional[str] = None


@app.post("/api/meetings/{meeting_id}/chat")
async def chat(meeting_id: int, req: ChatRequest, user: dict = Depends(get_current_user)):
    meeting = db.get_meeting(meeting_id, user["id"])
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    if req.board_member not in BOARD_MEMBERS:
        raise HTTPException(400, f"Unknown board member: {req.board_member}")

    # Gather context
    memory_content = db.get_memory(user["id"], req.board_member) if req.use_memory else None
    doc_content = db.get_document_content(meeting_id) if meeting["type"] in ("document", "1on1") else None
    doc_context = None
    if doc_content:
        doc_context = f"Filename: {meeting.get('documents', [{}])[0].get('filename', 'document')}\n\n{doc_content[:10000]}"

    system = build_system_prompt(
        member_key=req.board_member,
        memory_content=memory_content,
        doc_context=doc_context,
        agenda_item=req.agenda_item,
    )

    # Build conversation history
    messages = []
    for msg in meeting.get("messages", []):
        if msg["board_member"] == req.board_member or msg["board_member"] is None:
            if msg["role"] == "user":
                messages.append({"role": "user", "content": msg["content"]})
            else:
                messages.append({"role": "assistant", "content": msg["content"]})

    messages.append({"role": "user", "content": req.message})

    # Save user message
    db.add_message(meeting_id, "user", req.message, None, req.agenda_item)

    client = get_anthropic_client()
    full_response = ""

    async def generate():
        nonlocal full_response
        try:
            with client.messages.stream(
                model="claude-opus-4-6",
                max_tokens=1500,
                system=system,
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    full_response += text
                    yield f"data: {json.dumps({'text': text, 'member': req.board_member})}\n\n"

            db.add_message(meeting_id, "assistant", full_response, req.board_member, req.agenda_item)
            yield f"data: {json.dumps({'done': True, 'member': req.board_member})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ─────────────────── BOARD MEETING — ALL MEMBERS RESPOND ───────────────────

class BoardItemRequest(BaseModel):
    agenda_item: str
    use_memory: bool = True
    allow_cross_reference: bool = True  # members see prior members' responses


@app.post("/api/meetings/{meeting_id}/board-respond")
async def board_respond(meeting_id: int, req: BoardItemRequest, user: dict = Depends(get_current_user)):
    """Stream responses from all board members to an agenda item, one after another."""
    meeting = db.get_meeting(meeting_id, user["id"])
    if not meeting:
        raise HTTPException(404, "Meeting not found")

    board_member_keys = meeting.get("board_members") or list(BOARD_MEMBERS.keys())
    doc_content = db.get_document_content(meeting_id)
    doc_context = None
    if doc_content:
        docs = meeting.get("documents", [])
        fname = docs[0].get("filename", "document") if docs else "document"
        doc_context = f"Filename: {fname}\n\n{doc_content[:6000]}"

    # Save user agenda item as a message
    db.add_message(meeting_id, "user", req.agenda_item, None, req.agenda_item)

    client = get_anthropic_client()
    collected_responses = []  # accumulate for cross-referencing

    async def generate():
        for member_key in board_member_keys:
            if member_key not in BOARD_MEMBERS:
                continue

            member_info = BOARD_MEMBERS[member_key]
            memory_content = db.get_memory(user["id"], member_key) if req.use_memory else None

            # Build cross-reference context from previous members' responses this round
            other_responses = collected_responses if req.allow_cross_reference else []

            system = build_system_prompt(
                member_key=member_key,
                memory_content=memory_content,
                doc_context=doc_context,
                agenda_item=req.agenda_item,
                other_responses=other_responses if other_responses else None,
            )

            # Add board meeting instruction
            system += "\n\nYou are in a full EEARTH Board of Directors meeting. Respond to the agenda item with your perspective. Be direct, stay in character, and keep your response substantive but focused (3-5 paragraphs). Other board members will also be responding, so bring your unique expertise to bear."

            # Build recent history for context (last few exchanges)
            messages = []
            recent = meeting.get("messages", [])[-8:]
            for msg in recent:
                if msg["role"] == "user":
                    messages.append({"role": "user", "content": msg["content"]})
            messages.append({"role": "user", "content": req.agenda_item})

            # Signal member start
            yield f"data: {json.dumps({'member_start': member_key, 'member_name': member_info['name'], 'member_color': member_info['color']})}\n\n"

            full_response = ""
            try:
                with client.messages.stream(
                    model="claude-opus-4-6",
                    max_tokens=800,
                    system=system,
                    messages=messages,
                ) as stream:
                    for text in stream.text_stream:
                        full_response += text
                        yield f"data: {json.dumps({'text': text, 'member': member_key})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e), 'member': member_key})}\n\n"
                continue

            # Save and accumulate
            db.add_message(meeting_id, "assistant", full_response, member_key, req.agenda_item)
            collected_responses.append({"member": member_key, "content": full_response})

            yield f"data: {json.dumps({'member_done': member_key})}\n\n"

        yield f"data: {json.dumps({'all_done': True})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ─────────────────── GENERATE MINUTES ───────────────────

@app.post("/api/meetings/{meeting_id}/minutes")
async def generate_minutes(meeting_id: int, user: dict = Depends(get_current_user)):
    meeting = db.get_meeting(meeting_id, user["id"])
    if not meeting:
        raise HTTPException(404, "Meeting not found")

    messages = meeting.get("messages", [])
    if not messages:
        raise HTTPException(400, "No meeting content to generate minutes from")

    # Build transcript
    transcript_lines = []
    for msg in messages:
        if msg["role"] == "user":
            transcript_lines.append(f"[CHAIR / PRESENTED TO BOARD]:\n{msg['content']}\n")
        else:
            name = BOARD_MEMBERS.get(msg["board_member"], {}).get("name", "Board Member") if msg["board_member"] else "Board"
            transcript_lines.append(f"[{name.upper()}]:\n{msg['content']}\n")

    transcript = "\n".join(transcript_lines)

    meeting_date = time.strftime("%B %d, %Y")
    meeting_time = time.strftime("%I:%M %p")

    members_present = []
    member_keys = set()
    for msg in messages:
        if msg["board_member"] and msg["board_member"] not in member_keys:
            member_keys.add(msg["board_member"])
            info = BOARD_MEMBERS.get(msg["board_member"], {})
            if info:
                members_present.append(f"{info['name']}, {info['title']}")

    minutes_prompt = f"""You are the Corporate Secretary of EEARTH™ Exploration LLC. Generate formal, professional Board of Directors meeting minutes.

Meeting: {meeting["title"]}
Date: {meeting_date}
Directors: {}",".join(members_present) if members_present else "Full Board"}

TRANSCRIPT:
{_jsontranscript[:15000]}

Include: Call to order, directors present, quorum, agenda and discussion summary with director positions, resolutions, action items, next meeting, adjournment, and signature lines.""".replace("{_jsontranscript[:15000]}", transcript[:15000])

    client = get_anthropic_client()
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4000,
        messages=[{"role": "user", "content": minutes_prompt}],
    )

    minutes_text = response.content[0].text
    db.save_minutes(meeting_id, minutes_text)
    return {"minutes": minutes_text}


@app.get("/api/meetings/{meeting_id}/minutes")
async def get_minutes(meeting_id: int, user: dict = Depends(get_current_user)):
    meeting = db.get_meeting(meeting_id, user["id"])
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    minutes = db.get_minutes(meeting_id)
    return {"minutes": minutes}


# ─────────────────── MEMORY MANAGEMENT ───────────────────

@app.get("/api/memory")
async def get_all_memory(user: dict = Depends(get_current_user)):
    return db.get_all_memories(user["id"])


@app.get("/api/memory/{board_member}")
async def get_member_memory(board_member: str, user: dict = Depends(get_current_user)):
    if board_member not in BOARD_MEMBERS:
        raise HTTPException(400, f"Unknown board member: {board_member}")
    content = db.get_memory(user["id"], board_member)
    return {"board_member": board_member, "content": content}


@app.put("/api/memory/{board_member}")
async def set_member_memory(board_member: str, body: dict, user: dict = Depends(get_current_user)):
    if board_member not in BOARD_MEMBERS:
        raise HTTPException(400, f"Unknown board member: {board_member}")
    content = body.get("content", "")
    db.set_memory(user["id"], board_member, content)
    return {"message": "Memory updated"}


@app.delete("/api/memory/{board_member}")
async def clear_member_memory(board_member: str, user: dict = Depends(get_current_user)):
    if board_member not in BOARD_MEMBERS:
        raise HTTPException(400, f"Unknown board member: {board_member}")
    db.clear_memory(user["id"], board_member)
    return {"message": "Memory cleared"}


class AutoMemoryRequest(BaseModel):
    board_members: Optional[List[str]] = None  # None = all that participated


@app.post("/api/meetings/{meeting_id}/update-memory")
async def update_memory_from_meeting(
    meeting_id: int, req: AutoMemoryRequest, user: dict = Depends(get_current_user)
):
    meeting = db.get_meeting(meeting_id, user["id"])
    if not meeting:
        raise HTTPException(404, "Meeting not found")

    messages = meeting.get("messages", [])
    if not messages:
        raise HTTPException(400, "No messages to process")

    participant_keys = set()
    for msg in messages:
        if msg["board_member"] and msg["board_member"] in BOARD_MEMBERS:
            participant_keys.add(msg["board_member"])

    target_keys = req.board_members or list(participant_keys)

    client = get_anthropic_client()
    results = {}

    for member_key in target_keys:
        if member_key not in BOARD_MEMBERS:
            continue
        member_name = BOARD_MEMBERS[member_key]["name"]
        member_transcript = []
        for msg in messages:
            if msg["role"] == "user":
                member_transcript.append(f"[USER]: {msg['content']}")
            elif msg["board_member"] == member_key:
                member_transcript.append(f"[{member_name}]: {msg['content']}")
        existing_memory = db.get_memory(user["id"], member_key) or No prior memory."
        memory_prompt = f"""Update {member_name}'s memory document based on this meeting. Write in first person. Include key topics, positions, action items, and notable insights. Under 800 words.

EXISTING: {existing_memory}

NEW MEETING ({meeting["title"]}):
{chr(10).join(member_transcript[:3000])}"""

        try:
            response = client.messages.create(
                model="claude-sonnet-4-6", max_tokens=1000,
                messages=[{"role": "user", "content": memory_prompt}],
            )
            new_memory = response.content[0].text
            db.set_memory(user["id"], member_key, new_memory)
            results[member_key] = {"status": "updated", "length": len(new_memory)}
        except Exception as e:
            results[member_key] = {"status": "error", "error": str(e)}

    return {"updated": results}


# ─────────────────── FOUNDATION MEMORY (read-only) ───────────────────

@app.get("/api/foundation-memory")
async def get_foundation_memory_all(user: dict = Depends(get_current_user)):
    memories = get_all_foundation_memories()
    return {"description": "Foundation EEARTH knowledge permanently embedded.",
            "members": {key: {"name": BOARD_MEMBERS.get(key, {}).get("name", key),
                              "content_length": len(content),
                              "preview": content[:200] + "..."}
                        for key, content in memories.items()}}


@app.get("/api/foundation-memory/{board_member}")
async def get_foundation_memory_member(board_member: str, user: dict = Depends(get_current_user)):
    if board_member not in BOARD_MEMBERS:
        raise HTTPException(400, f"Unknown board member: {board_member}")
    content = get_foundation_memory(board_member)
    return {"board_member": board_member, "name": BOARD_MEMBERS[board_member]["name"], "content": content}


# ─────────────────── STATIC FILES / SPA ───────────────────

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/{path:path}")
async def serve_spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404)
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return HTMLResponse("<h1>EEARTH Board — frontend not built yet</h1>", status_code=503)


@app.get("/")
async def root():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return HTMLResponse("<h1>EEARTH Board — frontend not built yet</h1>", status_code=503)
