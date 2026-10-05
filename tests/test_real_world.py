"""Kịch bản thực tế: prompt mà nhân viên văn phòng, lập trình viên, CSKH hay gửi cho AI."""
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app import database, main
from app.services.masker import mask
from app.services.pii_detector import detect, normalize_text
from app.services.policy_engine import decide


def run(prompt: str):
    text = normalize_text(prompt)
    detections = detect(text)
    safe, _ = mask(text, detections)
    return decide(detections).action, {d.kind for d in detections}, safe


# (prompt, hành động mong đợi, loại phải phát hiện, chuỗi không được lọt ra)
MASK_CASES = [
    ("Soạn hợp đồng lao động cho ông Trần Minh Quân, sinh ngày 12/03/1990, CCCD 079090001234, "
     "thường trú 45 Lê Lợi, phường Bến Nghé, quận 1, TP.HCM.",
     {"PERSON", "DOB", "CCCD", "ADDRESS"}, ["Trần Minh Quân", "079090001234", "45 Lê Lợi"]),
    ("Chuyển khoản giúp tôi 5.000.000 đồng vào STK 0071000123456 Vietcombank, chủ TK NGUYEN THI LAN.",
     {"BANK_ACCOUNT", "PERSON"}, ["0071000123456", "NGUYEN THI LAN"]),
    ("Bệnh nhân Phạm Thị Hồng, mã BHYT DN4797912345678, chẩn đoán đái tháo đường type 2.",
     {"PERSON", "INSURANCE"}, ["Phạm Thị Hồng", "DN4797912345678"]),
    ("Đơn hàng giao cho chị Hoa, sđt 0912.345.678, địa chỉ nhận hàng: 12 ngõ 34 Trần Duy Hưng, Cầu Giấy, Hà Nội.",
     {"PHONE", "ADDRESS"}, ["0912.345.678", "Trần Duy Hưng"]),
    ("Ship tới 268 Lý Thường Kiệt, P.14, Q.10, TP.HCM giúp", {"ADDRESS"}, ["268 Lý Thường Kiệt", "Q.10"]),
    ("Giao tới 12/3A Nguyễn Trãi, Phường 2, Quận 5 giúp em", {"ADDRESS"}, ["12/3A", "Phường 2"]),
    ("Văn phòng ở 15 Phố Huế, Hai Bà Trưng, Hà Nội", {"ADDRESS"}, ["15 Phố Huế"]),
    ("Chuyển tiền quốc tế tới IBAN DE89370400440532013000", {"BANK_ACCOUNT"}, ["DE89370400440532013000"]),
    ("Xuất hóa đơn cho công ty mã số thuế 0312345678-001", {"TAX_ID"}, ["0312345678"]),
    ("Xe biển số 51F-123.45 vượt đèn đỏ", {"LICENSE_PLATE"}, ["51F-123.45"]),
]

BLOCK_CASES = [
    "Đây là file .env của tôi:\nDB_HOST=localhost\nDB_PASSWORD=hunter2!\n",
    "export AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    "GITHUB_TOKEN=ghp_xxx123456 npm publish",
    '{"password": "P@ssw0rd2024"}',
    'db:\n  password: "abc123xyz"',
    "pass wifi nhà mình: matkhau123",
    "mk facebook là Lan@1999",
    "Thẻ visa 4111 1111 1111 1111 hết hạn 12/27 CVV 123, kiểm tra giúp",
    "Lỗi kết nối: postgresql://admin:Sup3rS3cret@10.0.0.5:5432/prod, sửa giúp",
]

# Câu bình thường không được che/chặn nhầm.
ALLOW_CASES = [
    "Lý do Hà Nội mùa thu đẹp là gì? Mai tôi đi Đà Lạt.",
    "Doanh thu quý 3 đạt 1.234.567.890 đồng, tăng 12%",
    "Mã vận đơn GHN 1234567890123 chưa giao",
    "Làm sao để pass môn Giải tích? pass rate là bao nhiêu",
    "mk thấy bài này khó quá, mk là sinh viên năm 2",
    "Họp lúc 10 giờ sáng, phòng 3, tầng 2 nhé",
    "Chọn 3 trong số các món: phở, bún, cơm",
    "Có 3 phố đi bộ, rất đẹp, nên đi thử",
    '{"token_count": 512, "model": "gemma3"}',
    "Đặt MAX_TOKENS=1024 và temperature=0.7",
]


@pytest.mark.parametrize("prompt,kinds,hidden", MASK_CASES)
def test_real_world_mask(prompt, kinds, hidden):
    action, found, safe = run(prompt)
    assert action == "mask"
    assert kinds <= found
    for value in hidden:
        assert value not in safe


@pytest.mark.parametrize("prompt", BLOCK_CASES)
def test_real_world_block(prompt):
    action, found, _ = run(prompt)
    assert action == "block"
    assert "SECRET" in found


@pytest.mark.parametrize("prompt", ALLOW_CASES)
def test_real_world_allow(prompt):
    action, found, _ = run(prompt)
    assert action == "allow", found


def test_invalid_iban_checksum_not_masked():
    assert run("Mã tham chiếu DE00370400440532013000")[0] == "allow"


def test_env_secret_blocked_end_to_end(tmp_path):
    original = database.settings
    database.settings = replace(original, database_path=str(tmp_path / "rw.db"))
    main.login_attempts.clear()
    try:
        with TestClient(main.app) as client:
            csrf = client.post("/api/auth/login", json={"username": "demo", "password": "demo123"}).json()["csrf_token"]
            result = client.post(
                "/api/chat",
                headers={"X-CSRF-Token": csrf},
                json={"prompt": "Sửa lỗi giúp: DB_PASSWORD=hunter2! không kết nối được", "remember": True},
            ).json()
            assert result["status"] == "blocked"
            assert "hunter2" not in str(result)
    finally:
        database.settings = original
