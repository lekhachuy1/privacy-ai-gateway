"""Chứng minh body HTTP thật sự gửi tới Gemini không chứa PII gốc.

Test chặn httpx ngay tại lời gọi mạng, nên kiểm tra đúng những byte sẽ rời
khỏi máy, gồm cả prompt hiện tại lẫn lịch sử hội thoại gửi kèm.
"""
from dataclasses import replace
import json

import httpx
from fastapi.testclient import TestClient

from app import database, main
from app.services import connectors

RAW_PII = ["Nguyễn Văn An", "0901234567", "an@example.com"]


class FakeGeminiResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"candidates": [{"content": {"parts": [{"text": "Đã soạn email cho [PERSON_01]."}]}}]}


def test_gemini_http_body_never_contains_raw_pii(tmp_path, monkeypatch):
    sent: list[dict] = []

    async def fake_post(self, url, headers=None, json=None, **kwargs):
        sent.append({"url": url, "body": json})
        return FakeGeminiResponse()

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(database, "settings", replace(database.settings, database_path=str(tmp_path / "egress.db")))
    monkeypatch.setattr(connectors, "settings", replace(
        connectors.settings,
        gemini_api_key="test-key",
        egress_log_enabled=True,
        egress_log_path=str(tmp_path / "egress.log"),
    ))
    monkeypatch.setattr(main.router, "settings", replace(main.router.settings, ai_mode="gemini"))
    main.login_attempts.clear()

    with TestClient(main.app) as client:
        csrf = client.post("/api/auth/login", json={"username": "demo", "password": "demo123"}).json()["csrf_token"]
        headers = {"X-CSRF-Token": csrf}
        first = client.post("/api/chat", headers=headers, json={
            "prompt": "Viết email cho Nguyễn Văn An, số điện thoại 0901234567, email an@example.com.",
            "remember": True,
        }).json()
        # Lượt hai: lịch sử gửi kèm cũng phải là bản đã làm sạch.
        client.post("/api/chat", headers=headers, json={
            "prompt": "Viết ngắn gọn hơn.",
            "conversation_id": first["conversation_id"],
        })

    assert first["provider"] == "gemini"
    assert len(sent) == 2
    for request in sent:
        wire = json.dumps(request["body"], ensure_ascii=False)
        assert "[PERSON_01]" in wire
        for value in RAW_PII:
            assert value not in wire
    # Người dùng vẫn thấy dữ liệu thật sau khi khôi phục.
    assert "Nguyễn Văn An" in first["response"]

    logged = (tmp_path / "egress.log").read_text(encoding="utf-8")
    assert logged.count("\n") == 2
    assert "test-key" not in logged
    for value in RAW_PII:
        assert value not in logged
