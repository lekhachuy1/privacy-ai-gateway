from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sqlite3
import uuid

from .config import settings
from .security import hash_password


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect():
    path = Path(settings.database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db() -> None:
    with connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS users(
                id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user'
            );
            CREATE TABLE IF NOT EXISTS conversations(
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL,
                remember_enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, expires_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS messages(
                id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, role TEXT NOT NULL,
                content_sanitized TEXT NOT NULL, provider TEXT, model TEXT,
                policy_action TEXT, pii_types TEXT NOT NULL DEFAULT '[]',
                fallback_reason TEXT, created_at TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS audit_events(
                id TEXT PRIMARY KEY, user_id TEXT, event_type TEXT NOT NULL,
                policy_action TEXT, provider TEXT, pii_types TEXT NOT NULL DEFAULT '[]',
                latency_ms INTEGER, detail TEXT, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS token_vault(
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                token TEXT NOT NULL,
                encrypted_value TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                UNIQUE(user_id, conversation_id, token),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );
            """
        )
        # Nâng cấp database cũ tại chỗ, không xóa lịch sử đã làm sạch.
        _ensure_column(con, "conversations", "expires_at", "TEXT")
        _ensure_column(con, "messages", "fallback_reason", "TEXT")
        _ensure_column(con, "audit_events", "detail", "TEXT")
        existing = con.execute("SELECT id FROM users WHERE username='demo'").fetchone()
        if not existing:
            con.execute(
                "INSERT INTO users(id, username, password_hash, role) VALUES(?,?,?,?)",
                (str(uuid.uuid4()), "demo", hash_password(settings.demo_password), "user"),
            )
        _purge_expired(con)


def _purge_expired(con: sqlite3.Connection) -> None:
    now = utc_now()
    con.execute("DELETE FROM conversations WHERE expires_at IS NOT NULL AND expires_at < ?", (now,))
    con.execute("DELETE FROM token_vault WHERE expires_at < ?", (now,))


def purge_expired() -> None:
    """Xóa hẳn khỏi đĩa dữ liệu quá hạn lưu giữ, không đợi khởi động lại server."""
    with connect() as con:
        _purge_expired(con)


def _ensure_column(con: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in con.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def get_user(username: str):
    with connect() as con:
        row = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        return dict(row) if row else None


def create_conversation(user_id: str, title: str, remember: bool) -> str:
    cid = str(uuid.uuid4())
    now = utc_now()
    expires = (datetime.now(timezone.utc) + timedelta(days=settings.memory_retention_days)).isoformat()
    with connect() as con:
        con.execute(
            """INSERT INTO conversations(
               id,user_id,title,remember_enabled,created_at,updated_at,expires_at
               ) VALUES(?,?,?,?,?,?,?)""",
            (cid, user_id, title[:80], int(remember), now, now, expires),
        )
    return cid


def save_message(conversation_id: str, role: str, content: str, **meta) -> None:
    with connect() as con:
        con.execute(
            """INSERT INTO messages(id, conversation_id, role, content_sanitized,
               provider, model, policy_action, pii_types, fallback_reason, created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                str(uuid.uuid4()), conversation_id, role, content,
                meta.get("provider"), meta.get("model"), meta.get("policy_action"),
                json.dumps(meta.get("pii_types", []), ensure_ascii=False),
                meta.get("fallback_reason"), utc_now(),
            ),
        )
        con.execute("UPDATE conversations SET updated_at=? WHERE id=?", (utc_now(), conversation_id))


def save_token_mapping(
    user_id: str,
    conversation_id: str,
    encrypted_mapping: dict[str, str],
) -> None:
    """Lưu ánh xạ đã mã hóa; không nhận hoặc ghi dữ liệu rõ vào database."""
    if not encrypted_mapping:
        return
    now = utc_now()
    expires = (datetime.now(timezone.utc) + timedelta(days=settings.memory_retention_days)).isoformat()
    with connect() as con:
        owner = con.execute(
            "SELECT 1 FROM conversations WHERE id=? AND user_id=?",
            (conversation_id, user_id),
        ).fetchone()
        if not owner:
            raise ValueError("Conversation không thuộc người dùng")
        # Một token đã gán thì không bao giờ đổi giá trị: tin nhắn cũ dùng token đó
        # phải luôn khôi phục ra đúng giá trị ban đầu. Trùng token chỉ gia hạn.
        for token, encrypted_value in encrypted_mapping.items():
            con.execute(
                """INSERT INTO token_vault(
                   id,user_id,conversation_id,token,encrypted_value,created_at,expires_at
                   ) VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(user_id,conversation_id,token) DO UPDATE SET
                   expires_at=excluded.expires_at""",
                (str(uuid.uuid4()), user_id, conversation_id, token, encrypted_value, now, expires),
            )


def get_token_mapping(user_id: str, conversation_id: str) -> dict[str, str]:
    """Trả về ánh xạ còn mã hóa, chỉ khi user sở hữu conversation."""
    with connect() as con:
        rows = con.execute(
            """SELECT tv.token, tv.encrypted_value
               FROM token_vault tv
               JOIN conversations c ON c.id=tv.conversation_id
               WHERE tv.user_id=? AND tv.conversation_id=? AND c.user_id=?
                 AND tv.expires_at>=?
                 AND (c.expires_at IS NULL OR c.expires_at>=?)""",
            (user_id, conversation_id, user_id, utc_now(), utc_now()),
        ).fetchall()
    return {row["token"]: row["encrypted_value"] for row in rows}


def list_conversations(user_id: str):
    with connect() as con:
        rows = con.execute(
            """SELECT id,title,remember_enabled,created_at,updated_at FROM conversations
               WHERE user_id=? AND (expires_at IS NULL OR expires_at>=?) ORDER BY updated_at DESC""",
            (user_id, utc_now()),
        ).fetchall()
        return [dict(row) for row in rows]


def get_conversation(user_id: str, conversation_id: str):
    with connect() as con:
        conv = con.execute(
            """SELECT * FROM conversations WHERE id=? AND user_id=?
               AND (expires_at IS NULL OR expires_at>=?)""",
            (conversation_id, user_id, utc_now()),
        ).fetchone()
        if not conv:
            return None
        rows = con.execute(
            "SELECT role,content_sanitized,provider,model,policy_action,created_at FROM messages WHERE conversation_id=? ORDER BY created_at",
            (conversation_id,),
        ).fetchall()
        result = dict(conv)
        result["messages"] = [dict(row) for row in rows]
        return result


def get_cross_session_memory(
    user_id: str,
    exclude_conversation_id: str | None = None,
    limit: int = 4,
) -> list[dict]:
    """Lấy prompt đã làm sạch từ những phiên khác của chính người dùng."""
    if limit <= 0:
        return []
    query = """
        SELECT m.content_sanitized, m.created_at, c.title
        FROM messages m
        JOIN conversations c ON c.id = m.conversation_id
        WHERE c.user_id=?
          AND c.remember_enabled=1
          AND m.role='user'
          AND (c.expires_at IS NULL OR c.expires_at >= ?)
    """
    params: list[object] = [user_id, utc_now()]
    if exclude_conversation_id:
        query += " AND c.id<>?"
        params.append(exclude_conversation_id)
    query += " ORDER BY m.created_at DESC LIMIT ?"
    params.append(limit)
    with connect() as con:
        rows = con.execute(query, params).fetchall()
    return [
        {
            "role": "user",
            "content_sanitized": (
                f"[Ký ức đã làm sạch từ phiên '{row['title']}']: "
                f"{row['content_sanitized']}"
            ),
        }
        for row in reversed(rows)
    ]


def delete_conversation(user_id: str, conversation_id: str) -> bool:
    with connect() as con:
        cur = con.execute("DELETE FROM conversations WHERE id=? AND user_id=?", (conversation_id, user_id))
        return cur.rowcount > 0


def audit(user_id: str | None, event_type: str, **meta) -> None:
    with connect() as con:
        con.execute(
            """INSERT INTO audit_events(
               id,user_id,event_type,policy_action,provider,pii_types,latency_ms,detail,created_at
               ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                str(uuid.uuid4()), user_id, event_type, meta.get("policy_action"),
                meta.get("provider"), json.dumps(meta.get("pii_types", []), ensure_ascii=False),
                meta.get("latency_ms"), meta.get("detail"), utc_now(),
            ),
        )


def statistics(user_id: str):
    with connect() as con:
        row = con.execute(
            """SELECT COUNT(*) requests,
               SUM(CASE WHEN policy_action='block' THEN 1 ELSE 0 END) blocked,
               SUM(CASE WHEN policy_action='mask' THEN 1 ELSE 0 END) masked
               FROM audit_events WHERE user_id=? AND event_type='chat'""",
            (user_id,),
        ).fetchone()
        routes = con.execute(
            "SELECT COALESCE(provider,'none') provider, COUNT(*) count FROM audit_events WHERE user_id=? AND event_type='chat' GROUP BY provider",
            (user_id,),
        ).fetchall()
        return {**dict(row), "routes": [dict(r) for r in routes]}
