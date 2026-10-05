from dataclasses import replace

from fastapi.testclient import TestClient

from app import database, main


def test_login_csrf_chat_and_ownership(tmp_path):
    original = database.settings
    database.settings = replace(original, database_path=str(tmp_path / "api.db"))
    main.login_attempts.clear()
    try:
        with TestClient(main.app) as client:
            assert client.get("/api/conversations").status_code == 401

            login = client.post("/api/auth/login", json={"username": "demo", "password": "demo123"})
            assert login.status_code == 200
            csrf = login.json()["csrf_token"]

            missing_csrf = client.post("/api/chat", json={"prompt": "Zero Trust"})
            assert missing_csrf.status_code == 403

            headers = {"X-CSRF-Token": csrf}
            result = client.post("/api/chat", headers=headers, json={"prompt": "Zero Trust", "remember": True})
            assert result.status_code == 200
            payload = result.json()
            assert payload["provider"] == "mock"
            assert payload["conversation_id"]

            recalled = client.post(
                "/api/chat",
                headers=headers,
                json={"prompt": "Tôi đã làm gì ở phiên trước?", "remember": False, "use_cross_session_memory": True},
            )
            assert recalled.status_code == 200
            assert recalled.json()["cross_session_memory_used"] == 1
            assert "Có 1 tin nhắn an toàn" in recalled.json()["response"]

            assert client.get("/api/conversations/not-owned").status_code == 404
            assert client.delete("/api/conversations/not-owned", headers=headers).status_code == 404
    finally:
        database.settings = original


def test_login_rate_limit(tmp_path):
    original_db = database.settings
    original_main = main.settings
    configured = replace(
        original_main,
        database_path=str(tmp_path / "rate.db"),
        login_max_attempts=2,
        login_window_seconds=60,
    )
    database.settings = configured
    main.settings = configured
    main.login_attempts.clear()
    try:
        with TestClient(main.app) as client:
            for _ in range(2):
                assert client.post("/api/auth/login", json={"username": "demo", "password": "wrong"}).status_code == 401
            assert client.post("/api/auth/login", json={"username": "demo", "password": "wrong"}).status_code == 429
    finally:
        main.login_attempts.clear()
        main.settings = original_main
        database.settings = original_db


def test_masked_cloud_payload_and_restored_display(tmp_path):
    original = database.settings
    database.settings = replace(original, database_path=str(tmp_path / "restore.db"))
    main.login_attempts.clear()
    try:
        with TestClient(main.app) as client:
            login = client.post("/api/auth/login", json={"username": "demo", "password": "demo123"})
            csrf = login.json()["csrf_token"]
            headers = {"X-CSRF-Token": csrf}
            result = client.post(
                "/api/chat",
                headers=headers,
                json={
                    "prompt": "Liên hệ Nguyễn Văn An qua 0901234567",
                    "remember": True,
                },
            )
            assert result.status_code == 200
            payload = result.json()
            assert "Nguyễn Văn An" not in payload["safe_prompt"]
            assert "0901234567" not in payload["safe_prompt"]
            assert "Nguyễn Văn An" in payload["response"]
            assert "0901234567" in payload["response"]
            assert "Nguyễn Văn An" not in payload["response_sanitized"]

            conversation = client.get(f"/api/conversations/{payload['conversation_id']}").json()
            assert any("Nguyễn Văn An" in m["content_display"] for m in conversation["messages"])
            assert all("Nguyễn Văn An" not in m["content_sanitized"] for m in conversation["messages"])
    finally:
        database.settings = original


def test_decomposed_vietnamese_input_is_still_masked(tmp_path):
    import unicodedata
    original = database.settings
    database.settings = replace(original, database_path=str(tmp_path / "nfd.db"))
    main.login_attempts.clear()
    try:
        with TestClient(main.app) as client:
            csrf = client.post("/api/auth/login", json={"username": "demo", "password": "demo123"}).json()["csrf_token"]
            # Bộ gõ dấu tổ hợp: "ễ" = "e" + dấu mũ + dấu ngã.
            prompt = unicodedata.normalize("NFD", "Liên hệ Nguyễn Văn An")
            payload = client.post("/api/chat", headers={"X-CSRF-Token": csrf}, json={"prompt": prompt}).json()
            assert payload["safe_prompt"] == "Liên hệ [PERSON_01]"
    finally:
        database.settings = original
