"""
EEARTH Board App — Database Layer
SQLite-backed storage for users, meetings, messages, documents, minutes, and board member memory.
"""

import sqlite3
import json
import time
import os
from typing import Optional, List, Dict, Any

DB_PATH = os.environ.get("DATABASE_PATH", "eearth_board.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


class Database:
    def init(self):
        """Create all tables if they don't exist."""
        with get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS meetings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    board_members TEXT NOT NULL DEFAULT '[]',
                    agenda TEXT NOT NULL DEFAULT '[]',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    meeting_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    board_member TEXT,
                    agenda_item TEXT,
                    created_at REAL NOT NULL,
                    FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    meeting_id INTEGER NOT NULL,
                    filename TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS minutes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    meeting_id INTEGER NOT NULL UNIQUE,
                    content TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS board_member_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    board_member TEXT NOT NULL,
                    memory_content TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    UNIQUE(user_id, board_member)
                );

                CREATE INDEX IF NOT EXISTS idx_meetings_user ON meetings(user_id);
                CREATE INDEX IF NOT EXISTS idx_messages_meeting ON messages(meeting_id);
                CREATE INDEX IF NOT EXISTS idx_documents_meeting ON documents(meeting_id);
                CREATE INDEX IF NOT EXISTS idx_memory_user_member ON board_member_memory(user_id, board_member);
            """)

    # ─────────────────── USERS ───────────────────

    def create_user(self, email: str, name: str, password_hash: str, role: str = "user") -> int:
        with get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO users (email, name, password_hash, role, is_active, created_at) VALUES (?,?,?,?,1,?)",
                (email, name, password_hash, role, time.time()),
            )
            return cursor.lastrowid

    def get_user(self, user_id: int) -> Optional[dict]:
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            return dict(row) if row else None

    def get_user_by_email(self, email: str) -> Optional[dict]:
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            return dict(row) if row else None

    def list_users(self) -> List[dict]:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT id, email, name, role, is_active, created_at FROM users ORDER BY created_at"
            ).fetchall()
            return [dict(r) for r in rows]

    def update_user(self, user_id: int, updates: dict) -> None:
        if not updates:
            return
        sets = ", ".join(f"{k}=?" for k in updates)
        values = list(updates.values()) + [user_id]
        with get_conn() as conn:
            conn.execute(f"UPDATE users SET {sets} WHERE id=?", values)

    def delete_user(self, user_id: int) -> None:
        with get_conn() as conn:
            conn.execute("DELETE FROM users WHERE id=?", (user_id,))

    # ─────────────────── MEETINGS ───────────────────

    def create_meeting(self, user_id: int, type: str, title: str, board_members: list, agenda: list) -> int:
        now = time.time()
        with get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO meetings (user_id, type, title, board_members, agenda, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (user_id, type, title, json.dumps(board_members), json.dumps(agenda), now, now),
            )
            return cursor.lastrowid

    def get_meeting(self, meeting_id: int, user_id: int = None) -> Optional[dict]:
        with get_conn() as conn:
            if user_id is not None:
                row = conn.execute(
                    "SELECT * FROM meetings WHERE id=? AND user_id=?", (meeting_id, user_id)
                ).fetchone()
            else:
                row = conn.execute("SELECT * FROM meetings WHERE id=?", (meeting_id,)).fetchone()
            if not row:
                return None
            m = dict(row)
            m["board_members"] = json.loads(m["board_members"])
            m["agenda"] = json.loads(m["agenda"])
            m["messages"] = self.get_messages(meeting_id)
            m["documents"] = self.get_documents(meeting_id)
            m["minutes"] = self.get_minutes(meeting_id)
            return m

    def list_meetings(self, user_id: int) -> List[dict]:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT id, type, title, board_members, created_at, updated_at FROM meetings WHERE user_id=? ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
            result = []
            for row in rows:
                m = dict(row)
                m["board_members"] = json.loads(m["board_members"])
                count = conn.execute(
                    "SELECT COUNT(*) FROM messages WHERE meeting_id=?", (m["id"],)
                ).fetchone()[0]
                m["message_count"] = count
                result.append(m)
            return result

    def delete_meeting(self, meeting_id: int, user_id: int) -> None:
        with get_conn() as conn:
            conn.execute("DELETE FROM meetings WHERE id=? AND user_id=?", (meeting_id, user_id))

    def update_meeting_agenda(self, meeting_id: int, agenda: list) -> None:
        with get_conn() as conn:
            conn.execute(
                "UPDATE meetings SET agenda=?, updated_at=? WHERE id=?",
                (json.dumps(agenda), time.time(), meeting_id),
            )

    # ─────────────────── MESSAGES ───────────────────

    def add_message(self, meeting_id: int, role: str, content: str, board_member: str = None, agenda_item: str = None) -> int:
        with get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO messages (meeting_id, role, content, board_member, agenda_item, created_at) VALUES (?,?,?,?,?,?)",
                (meeting_id, role, content, board_member, agenda_item, time.time()),
            )
            conn.execute("UPDATE meetings SET updated_at=? WHERE id=?", (time.time(), meeting_id))
            return cursor.lastrowid

    def get_messages(self, meeting_id: int) -> List[dict]:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE meeting_id=? ORDER BY created_at",
                (meeting_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ─────────────────── DOCUMENTS ───────────────────

    def save_document(self, meeting_id: int, filename: str, content: str) -> int:
        with get_conn() as conn:
            # Replace existing document for this meeting
            conn.execute("DELETE FROM documents WHERE meeting_id=?", (meeting_id,))
            cursor = conn.execute(
                "INSERT INTO documents (meeting_id, filename, content, created_at) VALUES (?,?,?,?)",
                (meeting_id, filename, content, time.time()),
            )
            return cursor.lastrowid

    def get_documents(self, meeting_id: int) -> List[dict]:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT id, meeting_id, filename, LENGTH(content) as content_length, created_at FROM documents WHERE meeting_id=?",
                (meeting_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_document_content(self, meeting_id: int) -> Optional[str]:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT content FROM documents WHERE meeting_id=? LIMIT 1", (meeting_id,)
            ).fetchone()
            return row["content"] if row else None

    # ─────────────────── MINUTES ───────────────────

    def save_minutes(self, meeting_id: int, content: str) -> None:
        with get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO minutes (meeting_id, content, created_at) VALUES (?,?,?)",
                (meeting_id, content, time.time()),
            )

    def get_minutes(self, meeting_id: int) -> Optional[str]:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT content FROM minutes WHERE meeting_id=?", (meeting_id,)
            ).fetchone()
            return row["content"] if row else None

    # ─────────────────── BOARD MEMBER MEMORY ───────────────────

    def get_memory(self, user_id: int, board_member: str) -> Optional[str]:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT memory_content FROM board_member_memory WHERE user_id=? AND board_member=?",
                (user_id, board_member),
            ).fetchone()
            return row["memory_content"] if row else None

    def set_memory(self, user_id: int, board_member: str, content: str) -> None:
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO board_member_memory (user_id, board_member, memory_content, updated_at)
                   VALUES (?,?,?,?)
                   ON CONFLICT(user_id, board_member) DO UPDATE SET memory_content=excluded.memory_content, updated_at=excluded.updated_at""",
                (user_id, board_member, content, time.time()),
            )

    def clear_memory(self, user_id: int, board_member: str) -> None:
        with get_conn() as conn:
            conn.execute(
                "DELETE FROM board_member_memory WHERE user_id=? AND board_member=?",
                (user_id, board_member),
            )

    def get_all_memories(self, user_id: int) -> dict:
        """Return a dict of {board_member: memory_content} for all members with memory."""
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT board_member, memory_content, updated_at FROM board_member_memory WHERE user_id=?",
                (user_id,),
            ).fetchall()
            return {r["board_member"]: {"content": r["memory_content"], "updated_at": r["updated_at"]} for r in rows}


db = Database()
