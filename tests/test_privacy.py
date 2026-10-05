from app.services.masker import label_tokens, mask, restore_tokens
from app.services.output_scanner import sanitize_output
from app.services.pii_detector import detect
from app.services.policy_engine import decide


def test_allow_safe_prompt():
    detections = detect("Giải thích mô hình Zero Trust")
    assert detections == []
    assert decide(detections).action == "allow"


def test_mask_contact_data():
    text = "Liên hệ Nguyễn Văn An qua 0901234567 hoặc an@example.com"
    detections = detect(text)
    kinds = {d.kind for d in detections}
    assert {"PERSON", "PHONE", "EMAIL"}.issubset(kinds)
    safe, mapping = mask(text, detections)
    assert "0901234567" not in safe
    assert "an@example.com" not in safe
    assert mapping
    assert decide(detections).action == "mask"


def test_restore_only_authorized_tokens():
    mapping = {"[PERSON_01]": "Nguyễn Văn An", "[PHONE_01]": "0901234567"}
    response = "Xin chào [PERSON_01], liên hệ [PHONE_01]; bỏ qua [PERSON_99]."
    restored = restore_tokens(response, mapping)
    assert "Nguyễn Văn An" in restored
    assert "0901234567" in restored
    assert "[PERSON_99]" in restored


def test_mask_avoids_token_collision_across_turns():
    existing = {"[PERSON_01]"}
    text = "Liên hệ Trần Văn Bình"
    safe, mapping = mask(text, detect(text), existing)
    assert "[PERSON_02]" in safe
    assert mapping["[PERSON_02]"] == "Trần Văn Bình"


def test_block_secret():
    detections = detect("API_KEY=sk-demo-secret-123456789")
    assert decide(detections).action == "block"


def test_output_scanner():
    safe, kinds = sanitize_output("Gọi lại số 0901234567")
    assert "0901234567" not in safe
    assert "PHONE" in kinds


def test_output_scanner_does_not_collide_with_input_tokens():
    safe, kinds = sanitize_output("AI tự sinh số 0912345678", {"[PHONE_01]"})
    assert "[PHONE_02]" in safe
    assert "PHONE" in kinds


def test_common_vietnamese_pii_variants():
    cases = {
        "090 123 4567": "PHONE",
        "090-123-4567": "PHONE",
        "nguyễn văn an": "PERSON",
        "B1234567": "PASSPORT",
        "11/09/2000": "DOB",
        "192.168.1.10": "IP_ADDRESS",
        "4111 1111 1111 1111": "BANK_CARD",
    }
    for text, expected in cases.items():
        assert expected in {item.kind for item in detect(text)}


def test_more_secrets_are_blocked():
    samples = [
        "mật khẩu: abc123",
        "AKIAIOSFODNN7EXAMPLE",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.signature",
    ]
    for text in samples:
        assert decide(detect(text)).action == "block"


def test_common_words_starting_with_surnames_are_not_names():
    for text in ["Lý do nghỉ việc là: vì lý do sức khỏe", "hồ sơ đỗ xe lúc hoàng hôn", "Sống tại Hồ Chí Minh"]:
        assert "PERSON" not in {item.kind for item in detect(text)}


def test_names_without_diacritics_and_after_common_words():
    text = "Lý do Nguyễn Văn An xin nghỉ, người nhận là Le Van A"
    names = [text[d.start:d.end] for d in detect(text) if d.kind == "PERSON"]
    assert names == ["Nguyễn Văn An", "Le Van A"]


def test_same_value_reuses_token_within_and_across_turns():
    text = "Gọi 0901234567 hoặc 090 123 4567"
    safe, mapping = mask(text, detect(text))
    assert safe == "Gọi [PHONE_01] hoặc [PHONE_01]"
    later = "Nhắc lại số 0901234567 và số mới 0912345678"
    safe, mapping = mask(later, detect(later), known={"[PHONE_01]": "0901234567"})
    assert safe == "Nhắc lại số [PHONE_01] và số mới [PHONE_02]"


def test_output_reusing_user_value_is_restorable_and_new_pii_is_labelled():
    known = {"[PERSON_01]": "Le Van A"}
    safe, kinds = sanitize_output("Kính gửi Le Van A, gọi 0912345678", set(known), known)
    assert safe == "Kính gửi [PERSON_01], gọi [PHONE_01]"
    shown = label_tokens(restore_tokens(safe, known))
    assert shown == "Kính gửi Le Van A, gọi (số điện thoại đã ẩn)"


def test_bank_account_after_keyword_is_masked_and_sensitive():
    text = "Chuyển 15.000.000 đồng cho Hoàng Minh Quân, số tài khoản 0071000123456 tại Vietcombank; STK: 1903 5566 7788"
    detections = detect(text)
    accounts = [text[d.start:d.end] for d in detections if d.kind == "BANK_ACCOUNT"]
    assert accounts == ["0071000123456", "1903 5566 7788"]
    safe, _ = mask(text, detections)
    assert "số tài khoản [BANK_ACCOUNT_01]" in safe and "15.000.000" in safe
    assert decide(detections).sensitive
