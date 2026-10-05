from collections.abc import Iterable
import re

from .pii_detector import TOKEN_PATTERN, Detection


def _initial_counters(reserved_tokens: set[str]) -> dict[str, int]:
    counters: dict[str, int] = {}
    for token in reserved_tokens:
        match = TOKEN_PATTERN.fullmatch(token)
        if match:
            kind = match.group("kind")
            counters[kind] = max(counters.get(kind, 0), int(match.group("number")))
    return counters


LABELS = {
    "PERSON": "họ tên", "PHONE": "số điện thoại", "EMAIL": "email", "CCCD": "số CCCD",
    "PASSPORT": "số hộ chiếu", "BANK_CARD": "số thẻ", "BANK_ACCOUNT": "số tài khoản",
    # Mẫu DOB bắt mọi ngày tháng năm đầy đủ, không riêng ngày sinh.
    "DOB": "ngày tháng", "IP_ADDRESS": "địa chỉ IP", "SECRET": "thông tin bí mật",
    "ADDRESS": "địa chỉ", "DRIVER_LICENSE": "số giấy phép lái xe", "TAX_ID": "mã số thuế",
    "INSURANCE": "số bảo hiểm", "LICENSE_PLATE": "biển số xe",
}


def tokens_in(texts: Iterable[str]) -> set[str]:
    """Mọi token đã xuất hiện trong các đoạn văn bản (lịch sử phiên, prompt).

    Token do Output Scanner gán cho PII AI tự sinh không nằm trong Token Vault;
    phải giữ chỗ cho chúng, nếu không lượt sau một giá trị khác sẽ nhận lại đúng
    token đó và bị khôi phục nhầm.
    """
    return {match.group(0) for text in texts for match in TOKEN_PATTERN.finditer(text)}


def _value_key(kind: str, value: str) -> tuple[str, str]:
    """Chuẩn hóa để "090 123 4567" và "0901234567" được coi là cùng một giá trị."""
    normalized = re.sub(r"[\s.\-()]+", "", value).casefold()
    if kind == "PHONE":
        normalized = re.sub(r"^\+?84", "0", normalized)  # +84 901… và 0901… là một số
    return kind, normalized


def mask(
    text: str,
    detections: list[Detection],
    reserved_tokens: set[str] | None = None,
    known: dict[str, str] | None = None,
) -> tuple[str, dict[str, str]]:
    """Token hóa PII; đánh số trái sang phải nhưng thay chuỗi từ phải sang trái.

    `known` là ánh xạ token → giá trị đã có trong phiên: giá trị lặp lại dùng lại
    đúng token cũ, để AI hiểu đó là cùng một người/số và phản hồi khôi phục được.
    """
    known = known or {}
    counters = _initial_counters((reserved_tokens or set()) | set(known))
    token_by_value: dict[tuple[str, str], str] = {}
    for token, value in known.items():
        match = TOKEN_PATTERN.fullmatch(token)
        if match:
            token_by_value.setdefault(_value_key(match.group("kind"), value), token)
    mapping: dict[str, str] = {}
    result = text
    replacements: list[tuple[Detection, str, str]] = []
    for item in sorted(detections, key=lambda d: d.start):
        original = text[item.start:item.end]
        key = _value_key(item.kind, original)
        token = token_by_value.get(key)
        if token is None:
            counters[item.kind] = counters.get(item.kind, 0) + 1
            token = f"[{item.kind}_{counters[item.kind]:02d}]"
            token_by_value[key] = token
        mapping[token] = original
        replacements.append((item, token, original))
    for item, token, _ in reversed(replacements):
        result = result[:item.start] + token + result[item.end:]
    return result, mapping


def restore_tokens(text: str, mapping: dict[str, str]) -> str:
    """Chỉ khôi phục token đúng định dạng và có trong mapping được cấp quyền."""
    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        return mapping.get(token, token)

    return TOKEN_PATTERN.sub(replace, text)


def label_tokens(text: str) -> str:
    """Đổi token còn sót (không được phép khôi phục) thành nhãn dễ đọc.

    Chỉ dùng cho bản hiển thị hoặc ngữ cảnh chéo phiên; bản lưu vẫn giữ token.
    """
    def replace(match: re.Match[str]) -> str:
        return f"({LABELS.get(match.group('kind'), 'thông tin')} đã ẩn)"

    return TOKEN_PATTERN.sub(replace, text)
