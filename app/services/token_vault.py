from base64 import urlsafe_b64encode
from hashlib import sha256

from cryptography.fernet import Fernet, InvalidToken

from ..database import get_token_mapping, save_token_mapping


class TokenVault:
    """Kho ánh xạ token tách biệt, mã hóa và kiểm tra phạm vi người dùng/phiên."""

    def __init__(self, configured_key: str, fallback_secret: str):
        # Cho phép demo chạy ngay; production phải đặt TOKEN_VAULT_KEY riêng.
        material = configured_key or fallback_secret
        derived = urlsafe_b64encode(sha256(material.encode("utf-8")).digest())
        self._fernet = Fernet(derived)

    def store(
        self,
        user_id: str,
        conversation_id: str,
        mapping: dict[str, str],
    ) -> None:
        encrypted = {
            token: self._fernet.encrypt(value.encode("utf-8")).decode("ascii")
            for token, value in mapping.items()
            if not token.startswith("[SECRET_")
        }
        save_token_mapping(user_id, conversation_id, encrypted)

    def load(self, user_id: str, conversation_id: str | None) -> dict[str, str]:
        if not conversation_id:
            return {}
        encrypted = get_token_mapping(user_id, conversation_id)
        result: dict[str, str] = {}
        for token, value in encrypted.items():
            try:
                result[token] = self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
            except (InvalidToken, UnicodeDecodeError):
                # Không trả dữ liệu nếu khóa sai hoặc bản ghi bị sửa đổi.
                continue
        return result
