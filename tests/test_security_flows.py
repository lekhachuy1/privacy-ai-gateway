"""Kiểm tra end-to-end các luồng dễ bị bắt lỗi: token, quyền sở hữu, lưu giữ, định tuyến."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app import database, main
from app.security import hash_password
from app.services.ai_router import AIRouter
from app.services.connectors import AIResult, GeminiConnector, ProviderHealth


class ScriptedAI:
    """Connector giả: trả lần lượt các câu trả lời định sẵn và ghi lại input."""

    name = "mock"

    def __init__(self, *replies: str, delay: float = 0):
        self.replies = list(replies)
        self.delay = delay
        self.prompts: list[str] = []

    async def health(self) -> ProviderHealth:
        return ProviderHealth(True, "scripted", "ok")

    async def generate(self, safe_prompt: str, history: list[dict]) -> AIResult:
        self.prompts.append(safe_prompt)
        if self.delay:
            await asyncio.sleep(self.delay)
        reply = self.replies.pop(0) if self.replies else f"Đã nhận: {safe_prompt}"
        return AIResult(reply, "mock", "scripted")


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "settings", replace(database.settings, database_path=str(tmp_path / "t.db")))
    main.login_attempts.clear()
    yield
    main.login_attempts.clear()


def use_ai(monkeypatch, ai: ScriptedAI) -> None:
    monkeypatch.setitem(main.router.connectors, "mock", ai)


def login(client, username="demo", password="demo123") -> dict:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def add_user(username: str, password: str) -> None:
    with database.connect() as con:
        con.execute(
            "INSERT INTO users(id, username, password_hash, role) VALUES(?,?,?,?)",
            (str(uuid.uuid4()), username, hash_password(password), "user"),
        )


def test_ai_invented_token_is_never_reused_for_new_user_value(app_env, monkeypatch):
    ai = ScriptedAI(
        "Đã lưu [PHONE_01]. Tổng đài hỗ trợ là 0911111111.",  # AI tự bịa một số
        "Đã ghi nhận số mới.",
    )
    use_ai(monkeypatch, ai)
    with TestClient(main.app) as client:
        headers = login(client)
        first = client.post("/api/chat", headers=headers, json={"prompt": "Số của tôi 0901234567"}).json()
        assert first["response_sanitized"] == "Đã lưu [PHONE_01]. Tổng đài hỗ trợ là [PHONE_02]."
        cid = first["conversation_id"]
        second = client.post("/api/chat", headers=headers, json={
            "prompt": "Số mới của tôi 0902222222", "conversation_id": cid,
        }).json()
        # [PHONE_02] đã thuộc về số AI bịa ra, nên số mới phải là [PHONE_03].
        assert second["safe_prompt"] == "Số mới của tôi [PHONE_03]"
        history = client.get(f"/api/conversations/{cid}").json()["messages"]
        old_reply = history[1]["content_display"]
        assert "0902222222" not in old_reply  # không khôi phục nhầm vào tin nhắn cũ
        assert "(số điện thoại đã ẩn)" in old_reply
        assert "0901234567" in old_reply


def test_concurrent_turns_in_one_conversation_get_distinct_tokens(app_env, monkeypatch):
    use_ai(monkeypatch, ScriptedAI("Bắt đầu."))

    async def scenario():
        database.init_db()
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post("/api/auth/login", json={"username": "demo", "password": "demo123"})
            headers = {"X-CSRF-Token": r.json()["csrf_token"]}
            cid = (await client.post("/api/chat", headers=headers, json={"prompt": "Bắt đầu"})).json()["conversation_id"]
            use_ai(monkeypatch, ScriptedAI(delay=0.05))
            a, b = await asyncio.gather(
                client.post("/api/chat", headers=headers, json={"prompt": "Gọi 0901111111", "conversation_id": cid}),
                client.post("/api/chat", headers=headers, json={"prompt": "Gọi 0902222222", "conversation_id": cid}),
            )
            return a.json(), b.json(), (await client.get(f"/api/conversations/{cid}")).json()

    a, b, conv = asyncio.run(scenario())
    assert {a["safe_prompt"], b["safe_prompt"]} == {"Gọi [PHONE_01]", "Gọi [PHONE_02]"}
    shown = [m["content_display"] for m in conv["messages"] if m["role"] == "user"]
    assert "Gọi 0901111111" in shown and "Gọi 0902222222" in shown


def test_other_user_cannot_read_use_or_delete_conversation(app_env, monkeypatch):
    use_ai(monkeypatch, ScriptedAI())
    with TestClient(main.app) as client:
        headers = login(client)
        cid = client.post("/api/chat", headers=headers, json={"prompt": "Gửi Nguyễn Văn An"}).json()["conversation_id"]
        add_user("attacker", "attacker-pass")
        client.cookies.clear()
        other = login(client, "attacker", "attacker-pass")
        assert client.get(f"/api/conversations/{cid}").status_code == 404
        assert client.post("/api/chat", headers=other, json={"prompt": "[PERSON_01] là ai?", "conversation_id": cid}).status_code == 404
        assert client.delete(f"/api/conversations/{cid}", headers=other).status_code == 404
        assert client.get("/api/conversations").json() == []
        # Ký ức chéo phiên cũng không lấy được dữ liệu của tài khoản khác.
        recalled = client.post("/api/chat", headers=other, json={"prompt": "Nhắc lại phiên trước"}).json()
        assert recalled["cross_session_memory_used"] == 0


def test_cross_session_tokens_are_never_restored_with_current_mapping(app_env, monkeypatch):
    use_ai(monkeypatch, ScriptedAI("Đã nhận.", "Phiên trước có [PERSON_01]."))
    with TestClient(main.app) as client:
        headers = login(client)
        client.post("/api/chat", headers=headers, json={"prompt": "Viết thư cho Trần Văn Bình"})
        reply = client.post("/api/chat", headers=headers, json={"prompt": "Liên hệ Lê Thị Hoa"}).json()
        # [PERSON_01] trong phiên mới là Lê Thị Hoa; câu AI nhắc lại thuộc phiên mới.
        assert "Trần Văn Bình" not in reply["response"]
        history = main.router.connectors["mock"].prompts
        assert all("Trần Văn Bình" not in p for p in history)


def test_tampered_vault_value_is_not_returned(app_env, monkeypatch):
    use_ai(monkeypatch, ScriptedAI("Chào [PERSON_01]"))
    with TestClient(main.app) as client:
        headers = login(client)
        cid = client.post("/api/chat", headers=headers, json={"prompt": "Gửi Nguyễn Văn An"}).json()["conversation_id"]
        with database.connect() as con:
            con.execute("UPDATE token_vault SET encrypted_value='gAAAAAtampered'")
        shown = client.get(f"/api/conversations/{cid}").json()["messages"][1]["content_display"]
        assert shown == "Chào (họ tên đã ẩn)"


def test_vault_stores_only_ciphertext_and_delete_cascades(app_env, monkeypatch):
    use_ai(monkeypatch, ScriptedAI())
    with TestClient(main.app) as client:
        headers = login(client)
        cid = client.post("/api/chat", headers=headers, json={"prompt": "Gửi Nguyễn Văn An 0901234567"}).json()["conversation_id"]
        raw = (database.Path(database.settings.database_path)).read_bytes()
        assert "Nguyễn Văn An".encode() not in raw and b"0901234567" not in raw
        assert client.delete(f"/api/conversations/{cid}", headers=headers).status_code == 200
        with database.connect() as con:
            assert con.execute("SELECT COUNT(*) FROM token_vault").fetchone()[0] == 0
            assert con.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0


def test_expired_data_is_physically_purged_without_restart(app_env, monkeypatch):
    use_ai(monkeypatch, ScriptedAI())
    with TestClient(main.app) as client:
        headers = login(client)
        cid = client.post("/api/chat", headers=headers, json={"prompt": "Gửi Nguyễn Văn An"}).json()["conversation_id"]
        past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        with database.connect() as con:
            con.execute("UPDATE conversations SET expires_at=?", (past,))
            con.execute("UPDATE token_vault SET expires_at=?", (past,))
        client.post("/api/chat", headers=headers, json={"prompt": "Câu hỏi mới"})
        with database.connect() as con:
            assert con.execute("SELECT COUNT(*) FROM conversations WHERE id=?", (cid,)).fetchone()[0] == 0
            assert con.execute("SELECT COUNT(*) FROM token_vault").fetchone()[0] == 0


def test_blocked_prompt_never_reaches_ai_or_storage(app_env, monkeypatch):
    ai = ScriptedAI()
    use_ai(monkeypatch, ai)
    with TestClient(main.app) as client:
        headers = login(client)
        result = client.post("/api/chat", headers=headers, json={"prompt": "mật khẩu là Abc@12345"}).json()
        assert result["status"] == "blocked"
        assert ai.prompts == []
        assert client.get("/api/conversations").json() == []
        analyzed = client.post("/api/analyze", headers=headers, json={"prompt": "OTP: 482913"}).json()
        assert analyzed["action"] == "block" and analyzed["safe_prompt"] is None


@pytest.mark.parametrize("prompt", ["   ", "​​", "a" * 4001])
def test_blank_or_oversized_prompt_is_rejected(app_env, monkeypatch, prompt):
    ai = ScriptedAI()
    use_ai(monkeypatch, ai)
    with TestClient(main.app) as client:
        headers = login(client)
        assert client.post("/api/chat", headers=headers, json={"prompt": prompt}).status_code == 422
        assert ai.prompts == []


def test_auth_csrf_and_security_headers(app_env):
    with TestClient(main.app) as client:
        unknown = client.post("/api/auth/login", json={"username": "khong-ton-tai", "password": "x"})
        wrong = client.post("/api/auth/login", json={"username": "demo", "password": "sai"})
        assert unknown.status_code == wrong.status_code == 401
        assert unknown.json() == wrong.json()  # không lộ username có tồn tại hay không
        headers = login(client)
        assert client.post("/api/chat", headers={"X-CSRF-Token": "sai"}, json={"prompt": "hi"}).status_code == 403
        assert client.post("/api/auth/logout").status_code == 403
        api = client.get("/api/conversations")
        assert api.headers["cache-control"] == "no-store"
        assert api.headers["x-content-type-options"] == "nosniff"
        page = client.get("/")
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
        assert client.post("/api/auth/logout", headers=headers).status_code == 200
        assert client.get("/api/conversations").status_code == 401


def test_unknown_username_costs_as_much_as_wrong_password(app_env):
    import time

    with TestClient(main.app) as client:
        def elapsed(username: str) -> float:
            main.login_attempts.clear()
            started = time.perf_counter()
            client.post("/api/auth/login", json={"username": username, "password": "sai"})
            return time.perf_counter() - started

        elapsed("demo")  # làm nóng
        wrong = min(elapsed("demo") for _ in range(3))
        unknown = min(elapsed("khong-ton-tai") for _ in range(3))
    # Không có băm giả thì tài khoản không tồn tại trả về nhanh hơn hàng trăm lần.
    assert unknown > wrong * 0.5


def test_title_never_contains_half_token(app_env, monkeypatch):
    use_ai(monkeypatch, ScriptedAI())
    with TestClient(main.app) as client:
        headers = login(client)
        prompt = "Viết thư cảm ơn rất trang trọng và chi tiết gửi tới Nguyễn Văn An"
        title = client.post("/api/chat", headers=headers, json={"prompt": prompt}).json()["conversation_title"]
        assert title == "Viết thư cảm ơn rất trang trọng và chi tiết gửi tới"


class Provider:
    def __init__(self, name: str, error: str | None = None):
        self.name, self.error, self.calls = name, error, 0

    async def generate(self, safe_prompt, history):
        self.calls += 1
        if self.error:
            raise RuntimeError(self.error)
        return AIResult("ok", self.name, "m")


@pytest.mark.parametrize(("overrides", "cloud_allowed"), [
    ({"ai_mode": "hybrid", "ai_sensitive_provider": "gemini"}, False),  # cấu hình nhầm
    ({"ai_mode": "hybrid", "ai_fallback_provider": "gemini"}, False),
    ({"ai_mode": "ollama", "ai_fallback_provider": "gemini"}, False),
    ({"ai_mode": "gemini"}, True),  # người dùng chủ động chọn cloud cho mọi prompt
])
def test_sensitive_data_reaches_cloud_only_when_explicitly_chosen(overrides, cloud_allowed):
    defaults = {"ai_mode": "hybrid", "ai_default_provider": "gemini",
                "ai_sensitive_provider": "ollama", "ai_fallback_provider": "mock"}
    configured = replace(main.settings, **{**defaults, **overrides})
    router = AIRouter(configured)
    gemini, ollama, mock = Provider("gemini"), Provider("ollama", error="down"), Provider("mock")
    router.connectors = {"gemini": gemini, "ollama": ollama, "mock": mock}
    result = asyncio.run(router.generate("[CCCD_01]", [], sensitive=True))
    assert (gemini.calls > 0) is cloud_allowed
    assert result.provider == ("gemini" if cloud_allowed else "mock")


def test_gemini_multi_part_reply_skips_thoughts(monkeypatch):
    from app.services import connectors

    class Reply:
        def raise_for_status(self):
            return None

        def json(self):
            return {"candidates": [{"content": {"parts": [
                {"text": "suy nghĩ nội bộ", "thought": True}, {"text": "Phần 1. "}, {"text": "Phần 2."},
            ]}}]}

    async def fake_post(self, url, **kwargs):
        return Reply()

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(connectors, "settings", replace(connectors.settings, gemini_api_key="k", egress_log_enabled=False))
    result = asyncio.run(GeminiConnector().generate("hi", []))
    assert result.text == "Phần 1. Phần 2."
