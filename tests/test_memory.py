from dataclasses import replace
from datetime import datetime, timedelta, timezone

from app import database


def test_sanitized_memory_and_ownership(tmp_path):
    original = database.settings
    database.settings = replace(original, database_path=str(tmp_path / "test.db"))
    try:
        database.init_db()
        user = database.get_user("demo")
        cid = database.create_conversation(user["id"], "Phiên test", True)
        database.save_message(cid, "user", "Liên hệ [PHONE_01]", policy_action="mask", pii_types=["PHONE"])
        own = database.get_conversation(user["id"], cid)
        assert own["messages"][0]["content_sanitized"] == "Liên hệ [PHONE_01]"
        memory = database.get_cross_session_memory(user["id"], limit=5)
        assert len(memory) == 1
        assert "[PHONE_01]" in memory[0]["content_sanitized"]
        assert "0901234567" not in memory[0]["content_sanitized"]
        assert database.get_cross_session_memory("wrong-user-id", limit=5) == []
        assert database.get_cross_session_memory(user["id"], exclude_conversation_id=cid) == []
        assert database.get_conversation("wrong-user-id", cid) is None
        assert database.delete_conversation(user["id"], cid) is True
    finally:
        database.settings = original


def test_expired_conversation_is_not_visible(tmp_path):
    original = database.settings
    database.settings = replace(original, database_path=str(tmp_path / "expired.db"))
    try:
        database.init_db()
        user = database.get_user("demo")
        cid = database.create_conversation(user["id"], "Đã hết hạn", True)
        expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        with database.connect() as con:
            con.execute("UPDATE conversations SET expires_at=? WHERE id=?", (expired, cid))
        assert database.get_conversation(user["id"], cid) is None
        assert all(item["id"] != cid for item in database.list_conversations(user["id"]))
        assert database.get_cross_session_memory(user["id"]) == []
    finally:
        database.settings = original
