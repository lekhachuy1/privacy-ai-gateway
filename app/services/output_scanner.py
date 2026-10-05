from .masker import mask
from .pii_detector import detect, normalize_text


def sanitize_output(
    text: str,
    reserved_tokens: set[str] | None = None,
    known: dict[str, str] | None = None,
) -> tuple[str, list[str]]:
    text = normalize_text(text)  # cùng lý do như chuẩn hóa prompt đầu vào
    detections = detect(text)
    if not detections:
        return text, []
    # Giá trị trùng với dữ liệu người dùng đã cung cấp trong phiên (`known`) dùng
    # lại token cũ nên vẫn được khôi phục. PII mới do AI tự sinh nhận token mới,
    # không có trong Token Vault nên không thể bị khôi phục.
    sanitized, _ = mask(text, detections, reserved_tokens=reserved_tokens, known=known)
    return sanitized, sorted({item.kind for item in detections})
