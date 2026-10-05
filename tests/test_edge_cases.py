"""Các trường hợp biên và cách né bộ nhận diện mà người chấm có thể thử."""
import time

import pytest

from app.services.masker import mask
from app.services.pii_detector import detect, normalize_text
from app.services.policy_engine import decide


def spans(text: str, kind: str | None = None) -> list[str]:
    return [text[d.start:d.end] for d in detect(text) if kind is None or d.kind == kind]


def kinds(text: str) -> set[str]:
    return {d.kind for d in detect(text)}


# (prompt, loại phải có, giá trị gốc không được còn trong safe_prompt)
MUST_MASK = [
    ("CCCD của tôi là 001 203 012 345", "CCCD", "001 203 012 345"),
    ("CMND: 123456789 cấp năm 2010", "CCCD", "123456789"),
    ("căn cước công dân số 079-123-456-789", "CCCD", "079-123-456-789"),
    ("Mã định danh 0012 0301 2345", "CCCD", "0012 0301 2345"),
    ("SĐT: 0901.234.567", "PHONE", "0901.234.567"),
    ("gọi (+84) 901 234 567 nhé", "PHONE", "901 234 567"),
    ("số máy bàn 028 3823 4567", "PHONE", "028 3823 4567"),
    ("liên hệ 0901 - 234 - 567", "PHONE", "0901 - 234 - 567"),
    ("email an [at] example [dot] com", "EMAIL", "an [at] example [dot] com"),
    ("gửi về an @ example.com", "EMAIL", "an @ example.com"),
    ("STK của tôi: 1903 5566 7788", "BANK_ACCOUNT", "1903 5566 7788"),
    ("số tài khoản 0071000123456 Vietcombank", "BANK_ACCOUNT", "0071000123456"),
    ("thẻ 5555-5555-5555-4444 hết hạn", "BANK_CARD", "5555-5555-5555-4444"),
    ("Ngày sinh 12.03.1995", "DOB", "12.03.1995"),
    ("sinh 1995-03-12", "DOB", "1995-03-12"),
    ("sinh ngày 12 tháng 3 năm 1995", "DOB", "12 tháng 3 năm 1995"),
    ("server 2001:db8::1 lỗi", "IP_ADDRESS", "2001:db8::1"),
    ("xe biển số 51G-123.45 đỗ sai", "LICENSE_PLATE", "51G-123.45"),
    ("mã số thuế 0101234567", "TAX_ID", "0101234567"),
    ("thẻ BHYT HS4010123456789", "INSURANCE", "HS4010123456789"),
    ("GPLX số 012345678901", "DRIVER_LICENSE", "012345678901"),
    ("Địa chỉ: 12 Lê Lợi, Quận 1, TP.HCM, số điện thoại 0901234567", "ADDRESS", "12 Lê Lợi"),
    ("địa chỉ nhà tôi là 268 Lý Thường Kiệt, P.14, Q.10.", "ADDRESS", "268 Lý Thường Kiệt"),
    ("Hộ chiếu C1234567", "PASSPORT", "C1234567"),
]


@pytest.mark.parametrize(("text", "kind", "raw"), MUST_MASK)
def test_variants_are_masked(text, kind, raw):
    detections = detect(text)
    assert kind in {d.kind for d in detections}, detections
    safe, _ = mask(text, detections)
    assert raw not in safe
    assert decide(detections).action == "mask"


@pytest.mark.parametrize("name", [
    "Đinh Văn Nam", "Trương Thị Mai", "Lưu Quang Vũ", "NGUYỄN VĂN AN", "Hà Thu Trang",
    "Mai Phương Thúy", "Lê Nam", "Trần Minh", "Trần Minh Khoa", "Nguyễn Trọng Hiếu",
    "Phạm Thị Ngọc Bích Trâm",
])
def test_vietnamese_names_including_less_common_surnames(name):
    assert spans(f"Gửi thư cho {name} trước thứ Sáu", "PERSON") == [name]


def test_name_boundary_stops_before_titles_and_abbreviations():
    assert spans("Gửi Nguyễn Văn An SĐT 0901234567", "PERSON") == ["Nguyễn Văn An"]
    assert spans("Kính gửi Nguyễn Văn An Trưởng Phòng nhân sự", "PERSON") == ["Nguyễn Văn An"]
    # "Mai" ở đầu câu là "ngày mai", tên thật bắt đầu từ "Nguyễn".
    assert spans("Mai Nguyễn Văn An sẽ đến", "PERSON") == ["Nguyễn Văn An"]


@pytest.mark.parametrize("text", [
    "mật khẩu là Abc@12345",
    "mật khẩu wifi của tôi là 12345678",
    "OTP: 482913",
    "pwd=hunter2",
    "key AIzaSyA1234567890abcdefghijklmnopqrstu",
    "key mới AQ.Ab8RN6I1gY-i0kyM-MplvSpV0Do0Zw9Vi7Ec0W",
    "token ghp_" + "a1B2c3D4e5" * 4,
    "kết nối postgres://admin:S3cret@db.local:5432/app",
    "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456",
    "-----BEGIN RSA PRIVATE KEY-----",
    "dùng sk-proj-abc123def456ghi789",
    "sk_live_51Habcdefghijk",
])
def test_secrets_are_blocked(text):
    assert decide(detect(text)).action == "block"


# Không được che/chặn nhầm: câu bình thường phải đi nguyên vẹn.
@pytest.mark.parametrize("text", [
    "Lập kế hoạch skills-development cho nhóm",
    "Tóm tắt bài skill_assessment_form",
    "Mật khẩu mạnh là gì?",
    "mật khẩu nên dài bao nhiêu ký tự",
    "Thanh toán 150.000.000 đồng vào tài khoản công ty",
    "số dư tài khoản là 2.500.000 đ",
    "Cuộc họp bắt đầu lúc 10:30:45",
    "Hà Nội là thủ đô của Việt Nam",
    "Văn bản này cần ký trước thứ Hai",
    "Hồ Sơ Xin Việc",
    "ngày mai anh đi làm sớm",
    "Địa chỉ email là gì?",
    "Viết đơn xin nghỉ, địa chỉ Đà Nẵng.",
    "Phiên bản 1.2.3 đã phát hành",
    "Lớp 10A1 có 45 học sinh",
    "Mã đơn hàng 1234 5678 9012 3456 bị giao trễ",
    "Vũ trụ rộng lớn và hoàng hôn rất đẹp",
    "Lý do nghỉ việc là sức khỏe",
    "Giá 2 triệu, giảm 15%, còn 1.700.000 đồng",
])
def test_ordinary_text_is_not_flagged(text):
    assert detect(text) == [], spans(text)
    assert decide(detect(text)).action == "allow"


def test_evasion_by_unicode_tricks_is_normalized():
    for raw in ["０９０１２３４５６７", "0901​234567", "0901 234 567", "09­01234567"]:
        assert "PHONE" in kinds(normalize_text(raw)), raw
    import unicodedata
    assert "PERSON" in kinds(normalize_text(unicodedata.normalize("NFD", "Nguyễn Văn An")))


def test_existing_tokens_are_not_detected_as_new_pii():
    text = "Gửi [PERSON_01] tại [ADDRESS_01], CCCD [CCCD_01], số [PHONE_01]"
    assert detect(text) == []


def test_literal_token_in_prompt_is_not_reused_for_real_value():
    text = "Mẫu [PHONE_01], số thật 0901234567"
    safe, mapping = mask(text, detect(text), reserved_tokens={"[PHONE_01]"})
    assert safe == "Mẫu [PHONE_01], số thật [PHONE_02]"
    assert mapping == {"[PHONE_02]": "0901234567"}


def test_international_and_local_phone_formats_share_one_token():
    text = "Gọi +84 901 234 567 hoặc 0901234567"
    safe, _ = mask(text, detect(text))
    assert safe == "Gọi [PHONE_01] hoặc [PHONE_01]"


@pytest.mark.parametrize("payload", [
    "0" * 4000,
    "1 " * 2000,
    "a@" * 2000,
    "địa chỉ " + "a" * 3990,
    "mật khẩu " * 440,
    "CCCD " * 800,
    "Nguyễn " * 570,
    ":" * 4000,
    "a:" * 2000,
], ids=lambda payload: repr(payload[:12]))
def test_detector_is_fast_on_adversarial_input(payload):
    started = time.perf_counter()
    detect(payload)
    assert time.perf_counter() - started < 2.0
