from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, TypeVar
import os
import warnings

ROOT = Path(__file__).resolve().parent.parent
T = TypeVar("T")


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env(ROOT / ".env")


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _env(name: str, default: str, cast: Callable[[str], T] = str) -> T:
    """Đọc biến môi trường mỗi khi tạo Settings(), không phải một lần lúc import.

    Giá trị mặc định thường của dataclass chỉ được tính khi định nghĩa class, nên
    đổi biến môi trường sau đó (ví dụ trong test) sẽ không có tác dụng.
    """
    return field(default_factory=lambda: cast(os.getenv(name, default)))


def _env_bool(name: str, default: bool) -> bool:
    return field(default_factory=lambda: _bool(name, default))


@dataclass(frozen=True)
class Settings:
    app_secret: str = _env("APP_SECRET", "dev-only-change-me")
    database_path: str = _env("DATABASE_PATH", str(ROOT / "data" / "privacy_gateway.db"))
    ai_mode: str = _env("AI_MODE", "mock", lambda v: v.strip().lower())
    ai_default_provider: str = _env("AI_DEFAULT_PROVIDER", "gemini", lambda v: v.strip().lower())
    ai_sensitive_provider: str = _env("AI_SENSITIVE_PROVIDER", "ollama", lambda v: v.strip().lower())
    ai_fallback_provider: str = _env("AI_FALLBACK_PROVIDER", "mock", lambda v: v.strip().lower())
    ai_timeout_seconds: float = _env("AI_TIMEOUT_SECONDS", "120", float)
    ai_max_input_chars: int = _env("AI_MAX_INPUT_CHARS", "4000", int)
    gemini_api_key: str = _env("GEMINI_API_KEY", "")
    gemini_model: str = _env("GEMINI_MODEL", "gemini-3.5-flash-lite", lambda v: v.strip().removeprefix("models/"))
    # 384 token cắt ngang các văn bản dài như đơn từ, email.
    gemini_max_output_tokens: int = _env("GEMINI_MAX_OUTPUT_TOKENS", "2048", int)
    ollama_base_url: str = _env("OLLAMA_BASE_URL", "http://127.0.0.1:11434", lambda v: v.rstrip("/"))
    ollama_model: str = _env("OLLAMA_MODEL", "gemma3:4b")
    ollama_keep_alive: str = _env("OLLAMA_KEEP_ALIVE", "2m")
    ollama_num_ctx: int = _env("OLLAMA_NUM_CTX", "4096", int)
    memory_enabled: bool = _env_bool("MEMORY_ENABLED", True)
    memory_retention_days: int = _env("MEMORY_RETENTION_DAYS", "7", int)
    memory_recent_messages: int = _env("MEMORY_RECENT_MESSAGES", "6", int)
    cross_session_memory_enabled: bool = _env_bool("CROSS_SESSION_MEMORY_ENABLED", True)
    cross_session_memory_messages: int = _env("CROSS_SESSION_MEMORY_MESSAGES", "4", int)
    # Khóa dùng để mã hóa ánh xạ token -> dữ liệu gốc. Trong môi trường thật phải
    # đặt TOKEN_VAULT_KEY riêng, đủ dài và không commit vào Git.
    token_vault_key: str = _env("TOKEN_VAULT_KEY", "")
    session_https_only: bool = _env_bool("SESSION_HTTPS_ONLY", False)
    session_max_age_seconds: int = _env("SESSION_MAX_AGE_SECONDS", "28800", int)
    login_max_attempts: int = _env("LOGIN_MAX_ATTEMPTS", "5", int)
    login_window_seconds: int = _env("LOGIN_WINDOW_SECONDS", "60", int)
    demo_password: str = _env("DEMO_PASSWORD", "demo123")
    # Ghi lại nguyên văn payload gửi tới provider AI để kiểm chứng khi demo.
    egress_log_enabled: bool = _env_bool("EGRESS_LOG_ENABLED", False)
    egress_log_path: str = _env("EGRESS_LOG_PATH", str(ROOT / "data" / "egress.log"))


settings = Settings()

_VALID_MODES = {"mock", "gemini", "ollama", "hybrid"}
if settings.ai_mode not in _VALID_MODES:
    raise ValueError(f"AI_MODE không hợp lệ: {settings.ai_mode!r}; chọn một trong {sorted(_VALID_MODES)}")
_VALID_PROVIDERS = {"mock", "gemini", "ollama"}
for _name in ("ai_default_provider", "ai_sensitive_provider", "ai_fallback_provider"):
    if getattr(settings, _name) not in _VALID_PROVIDERS:
        raise ValueError(f"{_name.upper()} không hợp lệ: {getattr(settings, _name)!r}; chọn một trong {sorted(_VALID_PROVIDERS)}")
if settings.ai_max_input_chars <= 0 or settings.memory_retention_days <= 0:
    raise ValueError("AI_MAX_INPUT_CHARS và MEMORY_RETENTION_DAYS phải lớn hơn 0")

if settings.app_secret in {"dev-only-change-me", "change-this-secret-before-demo"}:
    warnings.warn("APP_SECRET đang dùng giá trị mặc định; hãy đổi trước khi triển khai.", stacklevel=1)
if not settings.token_vault_key or settings.token_vault_key.startswith("change-this"):
    warnings.warn("TOKEN_VAULT_KEY chưa được đặt riêng; Token Vault dùng khóa mặc định/yếu.", stacklevel=1)
