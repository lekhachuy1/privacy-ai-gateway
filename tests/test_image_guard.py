"""Image Guard: ảnh phải được che trước khi bất cứ thứ gì rời gateway."""
from dataclasses import replace
from io import BytesIO
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import make_sample_images as samples  # noqa: E402

from app import database, main  # noqa: E402
from app.services import image_guard  # noqa: E402
from app.services.image_guard import (  # noqa: E402
    Word, analyze_image, deskew, detect_ocr_text, find_qr_codes, fix_ocr_digits, fix_ocr_surnames, load_image,
)

needs_ocr = pytest.mark.skipif(not image_guard.ocr_available(), reason="Chưa cài Tesseract OCR")
PERSON = samples.PEOPLE[0]


def png_bytes(image: Image.Image, **kwargs) -> bytes:
    out = BytesIO()
    image.save(out, **kwargs)
    return out.getvalue()


def test_ocr_digit_fix_only_touches_number_like_chunks():
    fixed, count = fix_ocr_digits("SĐT: 09O1 234 S67, Sinh năm Bob")
    assert fixed == "SĐT: 0901 234 567, Sinh năm Bob"
    assert count == 2
    assert fix_ocr_digits("Mã lớp CS 447 A") == ("Mã lớp CS 447 A", 0)


def test_surname_with_wrong_diacritics_is_repaired():
    words = [Word("NGUYÊN", (0, 0, 1, 1), (0, 1, 1, 1), 90), Word("VĂN", (0, 0, 1, 1), (0, 1, 1, 1), 90),
             Word("hồ", (0, 0, 1, 1), (0, 1, 1, 1), 90)]
    assert fix_ocr_surnames(words) == 1
    assert [w.text for w in words] == ["NGUYỄN", "VĂN", "hồ"]


def test_detection_survives_missing_diacritics_from_ocr():
    text = "Địa chi: 12 Lý Thường Kiệt, Quan 10, TP. Hồ Chi Minh"
    kinds = [(d.kind, text[d.start:d.end]) for d in detect_ocr_text(text)]
    assert ("ADDRESS", "12 Lý Thường Kiệt, Quan 10, TP. Hồ Chi Minh") in kinds
    # Lượt bỏ dấu không được sinh tên giả từ "CHỦ NGHĨA" (bỏ dấu thành họ "Chu").
    assert detect_ocr_text("CỘNG HOÀ XÃ HỘI CHỦ NGHĨA VIỆT NAM") == []


def test_long_numbers_are_masked_even_when_validators_fail():
    # OCR đọc "số" thành "50" dính vào số thẻ: Luhn trượt nhưng dãy số vẫn bị che.
    text = "Thẻ của anh 50 4111 1111 1111 1111 bị trừ tiền"
    assert [(d.kind, text[d.start:d.end]) for d in detect_ocr_text(text)] == [("LONG_NUMBER", "50 4111 1111 1111 1111")]
    # Số tiền, ngày tháng (dưới 9 chữ số) không bị che thừa.
    assert [d.kind for d in detect_ocr_text("Tổng cộng: 1.490.000 đ ngày 15/08/1990")] == ["DOB"]


def test_deskew_recovers_small_rotation():
    tilted = samples.fake_invoice(PERSON).rotate(4, expand=True, fillcolor="white")
    _, angle = deskew(tilted)
    assert abs(angle + 4) <= 0.5


def test_exif_and_gps_are_stripped_and_rotation_kept():
    image = Image.new("RGB", (80, 40), "white")
    data = png_bytes(image, format="JPEG", exif=samples.gps_exif())
    loaded, has_exif, has_gps = load_image(data)
    assert has_exif and has_gps
    out = BytesIO()
    loaded.save(out, format="PNG")
    assert not Image.open(BytesIO(out.getvalue())).getexif()


def test_rejects_non_images_and_oversized_files():
    with pytest.raises(ValueError):
        load_image(b"%PDF-1.7 not an image")
    with pytest.raises(ValueError):
        load_image(b"\x89PNG" + b"0" * image_guard.MAX_IMAGE_BYTES)


def test_qr_code_on_fake_cccd_is_found_and_decoded():
    found = find_qr_codes(samples.fake_cccd(PERSON))
    assert len(found) == 1
    assert found[0]["data"].startswith(PERSON["cccd"] + "|")
    assert "NATIONAL_ID" in image_guard._qr_summary(found[0]["data"])["pii_types"]


@needs_ocr
@pytest.mark.parametrize("doc,expected", [
    ("cccd", {"CCCD", "PERSON", "DOB"}),
    ("invoice", {"PERSON", "PHONE", "EMAIL", "TAX_ID", "BANK_ACCOUNT"}),
    ("chat", {"PERSON", "PHONE", "CCCD", "BANK_CARD"}),
])
def test_fake_documents_are_redacted(doc, expected):
    report = analyze_image(png_bytes(samples.BUILDERS[doc](PERSON), format="PNG"))
    assert expected <= {d.kind for d in report.detections}
    # Đọc lại ảnh đã che: không còn đọc được số điện thoại / CCCD / tài khoản.
    leftover = image_guard.build_text(image_guard.run_ocr(Image.open(BytesIO(report.redacted_png)).convert("RGB")))[0]
    digits = "".join(ch for ch in leftover if ch.isdigit())
    for key in ("cccd", "phone", "bank", "card", "tax"):
        if key in samples.EXPECTED[doc]:
            assert PERSON[key].replace(" ", "") not in digits


@needs_ocr
def test_image_chat_sends_only_masked_text(tmp_path, monkeypatch):
    original = database.settings
    database.settings = replace(original, database_path=str(tmp_path / "img.db"))
    main.login_attempts.clear()
    sent = []

    async def fake_generate(prompt, history, sensitive):
        sent.append(prompt)
        return await real_generate(prompt, history, sensitive)

    real_generate = main.router.generate
    monkeypatch.setattr(main.router, "generate", fake_generate)
    try:
        with TestClient(main.app) as client:
            csrf = client.post("/api/auth/login", json={"username": "demo", "password": "demo123"}).json()["csrf_token"]
            headers = {"X-CSRF-Token": csrf}
            data = png_bytes(samples.fake_chat(PERSON), format="PNG")
            files = {"file": ("chat.png", data, "image/png")}

            assert client.post("/api/image/analyze", files=files).status_code == 403
            preview = client.post("/api/image/analyze", headers=headers, files=files)
            assert preview.status_code == 200
            assert preview.json()["redacted_image"].startswith("data:image/png;base64,")
            assert PERSON["phone"] not in preview.json()["safe_text"]
            assert not sent  # xem trước không gọi AI

            result = client.post("/api/image/chat", headers=headers, files=files,
                                 data={"question": "Tóm tắt yêu cầu của khách", "remember": "true"})
            assert result.status_code == 200, result.text
            assert len(sent) == 1
            for value in (PERSON["phone"], PERSON["cccd"], PERSON["card"], "NGUYỄN VĂN AN"):
                assert value not in sent[0]
            assert "[PHONE_01]" in sent[0]
            assert result.json()["image"]["boxes"]
    finally:
        database.settings = original
