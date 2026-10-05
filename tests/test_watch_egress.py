"""Công cụ giám sát egress phải bắt được rò rỉ thật, không chỉ luôn báo xanh."""
from dataclasses import replace
import json
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import watch_egress  # noqa: E402

from app import database, main  # noqa: E402
from app.services import connectors  # noqa: E402

RAW = ["Nguyễn Văn An", "0901234567", "an@example.com", "001203012345"]


@pytest.mark.parametrize(("sent", "watched"), [
    ("gửi Nguyễn Văn An", "Nguyễn Văn An"),
    ("gửi NGUYEN  VAN AN", "Nguyễn Văn An"),          # mất dấu, hoa, thừa khoảng trắng
    ("gọi 090 123 4567", "0901234567"),              # khác cách viết số
    ("gọi +84 901.234.567", "0901234567"),           # mã quốc gia
    ("gọi 0901234567", "０９０１２３４５６７"),        # người dò gõ full-width
    ("CCCD 001-203-012-345", "001203012345"),
])
def test_watcher_detects_leak_in_any_format(sent, watched):
    body = json.dumps({"contents": [{"parts": [{"text": sent}]}]}, ensure_ascii=False)
    assert watch_egress.find_value(body, watched)


@pytest.mark.parametrize(("sent", "watched"), [
    ("gửi [PERSON_01], số [PHONE_01]", "Nguyễn Văn An"),
    ("gửi bạn Anh và Lan", "An"),  # "an" chỉ nằm trong từ khác
    ("mã đơn 09012345678", "0901234567"),  # dãy số dài hơn, không phải số đó
])
def test_watcher_does_not_raise_false_alarm(sent, watched):
    body = json.dumps({"contents": [{"parts": [{"text": sent}]}]}, ensure_ascii=False)
    assert watch_egress.find_value(body, watched) is None


def test_watcher_survives_corrupt_line(capsys):
    watch_egress.show('{"time": "2026-10-04T10:00:00", "provider": "gemi')
    assert "không đọc được" in capsys.readouterr().out


def test_follow_waits_for_complete_line_and_handles_truncation(tmp_path):
    log = tmp_path / "egress.log"
    log.write_text('{"cũ": 1}\n', encoding="utf-8")
    lines = watch_egress.follow(log)

    def writer():
        time.sleep(0.2)
        with log.open("a", encoding="utf-8") as f:
            f.write('{"a": ')  # dòng đang ghi dở
            f.flush()
            time.sleep(0.5)
            f.write('1}\n')
        time.sleep(0.5)
        log.write_text('{"b": 2}\n', encoding="utf-8")  # log bị làm trống rồi ghi lại

    threading.Thread(target=writer, daemon=True).start()
    assert next(lines) == '{"a": 1}\n'  # không trả nửa dòng, không trả dòng cũ
    assert next(lines) == '{"b": 2}\n'
    lines.close()


def _chat_and_read_log(tmp_path, monkeypatch, prompt: str) -> str:
    sent: list[dict] = []

    class Reply:
        def raise_for_status(self):
            return None

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "Đã soạn."}]}}]}

    async def fake_post(self, url, headers=None, json=None, **kwargs):
        sent.append(json)
        return Reply()

    import httpx
    log = tmp_path / "egress.log"
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(database, "settings", replace(database.settings, database_path=str(tmp_path / "w.db")))
    monkeypatch.setattr(connectors, "settings", replace(
        connectors.settings, gemini_api_key="test-key", egress_log_enabled=True, egress_log_path=str(log),
    ))
    monkeypatch.setattr(main.router, "settings", replace(main.router.settings, ai_mode="gemini"))
    main.login_attempts.clear()
    with TestClient(main.app) as client:
        csrf = client.post("/api/auth/login", json={"username": "demo", "password": "demo123"}).json()["csrf_token"]
        client.post("/api/chat", headers={"X-CSRF-Token": csrf}, json={"prompt": prompt})
    entry = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    # Log ghi đúng body mà httpx nhận để gửi đi, không phải một bản khác.
    assert entry["payload"] == sent[-1]
    return json.dumps(entry["payload"], ensure_ascii=False)


PROMPT = "Gửi Nguyễn Văn An, SĐT 090 123 4567, email an@example.com, CCCD 001203012345"


def test_gateway_egress_contains_no_raw_value(tmp_path, monkeypatch):
    body = _chat_and_read_log(tmp_path, monkeypatch, PROMPT)
    for value in RAW:
        assert watch_egress.find_value(body, value) is None, value


def test_watcher_catches_leak_when_masking_is_disabled(tmp_path, monkeypatch):
    # Đối chứng: tắt bộ nhận diện thì dữ liệu thật đi ra, và công cụ phải báo THẤY.
    monkeypatch.setattr(main, "detect", lambda text: [])
    body = _chat_and_read_log(tmp_path, monkeypatch, PROMPT)
    for value in RAW:
        assert watch_egress.find_value(body, value), value
