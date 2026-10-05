from dataclasses import dataclass

from .pii_detector import Detection


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str
    sensitive: bool


def decide(detections: list[Detection]) -> Decision:
    kinds = {item.kind for item in detections}
    if "SECRET" in kinds:
        return Decision("block", "Phát hiện mật khẩu, API key hoặc access token", True)
    if detections:
        high_risk = any(item.risk in {"high", "critical"} for item in detections)
        return Decision("mask", "Dữ liệu cá nhân phải được che giấu trước khi gọi AI", high_risk)
    return Decision("allow", "Không phát hiện dữ liệu thuộc phạm vi demo", False)
