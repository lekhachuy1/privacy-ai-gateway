from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json

import httpx

from ..config import settings
from .pii_detector import TOKEN_PATTERN


@dataclass(frozen=True)
class AIResult:
    text: str
    provider: str
    model: str
    fallback_reason: str | None = None


@dataclass(frozen=True)
class ProviderHealth:
    available: bool
    model: str
    detail: str

    def public(self) -> dict:
        return {"available": self.available, "model": self.model, "detail": self.detail}


class ConnectorError(RuntimeError):
    """Lỗi provider đã được làm sạch, an toàn để hiển thị trong demo."""


def _api_error(response: httpx.Response) -> str:
    message = ""
    try:
        data = response.json()
        if isinstance(data, dict):
            error = data.get("error", data)
            if isinstance(error, dict):
                message = str(error.get("message", ""))
    except ValueError:
        message = ""
    message = " ".join(message.split())[:240]
    suffix = f": {message}" if message else ""
    return f"HTTP {response.status_code}{suffix}"


SYSTEM_PROMPT = (
    "Bạn là trợ lý AI đứng sau một Privacy Gateway. Dữ liệu cá nhân của người dùng đã được "
    "thay bằng token dạng [PERSON_01], [PHONE_01], [EMAIL_01], [CCCD_01]. Mỗi token là giá trị "
    "THẬT người dùng đã cung cấp; hệ thống sẽ tự thay lại giá trị gốc trước khi hiển thị.\n"
    "Quy tắc:\n"
    "1. Khi cần điền thông tin đó, chép nguyên token vào đúng chỗ, giữ nguyên dấu ngoặc vuông "
    "và số thứ tự, coi token như chính tên/số/email đó.\n"
    "2. Không nhắc tới token hay việc dữ liệu bị ẩn, không liệt kê lại thông tin người dùng "
    "đã gửi, không hỏi lại thông tin đã có.\n"
    "3. Không tự bịa họ tên, số điện thoại, email hay số giấy tờ. Thông tin người dùng chưa "
    "cung cấp thì để dòng chấm '..........' để họ tự điền; không dùng dấu ngoặc vuông cho chỗ trống.\n"
    "4. Trả lời thẳng vào nội dung được yêu cầu, bằng tiếng Việt, định dạng Markdown gọn gàng."
)


def _record_egress(provider: str, url: str, payload: dict) -> None:
    """Ghi đúng body sắp gửi ra ngoài (không ghi header nên không lộ API key)."""
    if not settings.egress_log_enabled:
        return
    path = Path(settings.egress_log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "time": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "url": url,
        "payload": payload,
    }
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(entry, ensure_ascii=False) + "\n")


class MockConnector:
    name = "mock"

    async def health(self) -> ProviderHealth:
        return ProviderHealth(True, "deterministic-demo", "Sẵn sàng")

    async def generate(self, safe_prompt: str, history: list[dict]) -> AIResult:
        context = f" Có {len(history)} tin nhắn an toàn trong phiên cũ." if history else ""
        # Viết token dạng ‹PERSON_01› để gateway không khôi phục chúng khi hiển thị:
        # người xem thấy đúng thứ AI nhận được, không tưởng nhầm AI nhận dữ liệu thật.
        received = TOKEN_PATTERN.sub(lambda m: f"‹{m.group('kind')}_{m.group('number')}›", safe_prompt)
        return AIResult(
            text=f"[MOCK AI] Phản hồi giả lập, không gọi model thật. Nội dung AI nhận được: {received}.{context}",
            provider=self.name,
            model="deterministic-demo",
        )


class OllamaConnector:
    name = "ollama"

    async def health(self) -> ProviderHealth:
        try:
            async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
                response = await client.get(f"{settings.ollama_base_url}/api/tags")
                response.raise_for_status()
                models = response.json().get("models", [])
                names = {item.get("name") or item.get("model") for item in models}
                if settings.ollama_model not in names:
                    return ProviderHealth(
                        False,
                        settings.ollama_model,
                        f"Ollama đang chạy nhưng chưa có model {settings.ollama_model}",
                    )
                return ProviderHealth(True, settings.ollama_model, "Sẵn sàng trên máy local")
        except httpx.HTTPStatusError as exc:
            return ProviderHealth(False, settings.ollama_model, _api_error(exc.response))
        except (httpx.HTTPError, ValueError, ImportError):
            return ProviderHealth(False, settings.ollama_model, "Không kết nối được Ollama")

    async def generate(self, safe_prompt: str, history: list[dict]) -> AIResult:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages += [
            {"role": m["role"], "content": m["content_sanitized"]}
            for m in history[-settings.memory_recent_messages:]
        ]
        messages.append({"role": "user", "content": safe_prompt})
        payload = {
            "model": settings.ollama_model,
            "messages": messages,
            "stream": False,
            "keep_alive": settings.ollama_keep_alive,
            "options": {"num_ctx": settings.ollama_num_ctx, "temperature": 0.2},
        }
        url = f"{settings.ollama_base_url}/api/chat"
        _record_egress(self.name, url, payload)
        try:
            async with httpx.AsyncClient(timeout=settings.ai_timeout_seconds, trust_env=False) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
            text = str(data.get("message", {}).get("content", "")).strip()
            if not text:
                raise ConnectorError("Ollama không trả về nội dung")
            return AIResult(text, self.name, settings.ollama_model)
        except httpx.HTTPStatusError as exc:
            raise ConnectorError(_api_error(exc.response)) from exc
        except httpx.TimeoutException as exc:
            raise ConnectorError("Timeout khi chờ Ollama; model có thể đang nạp vào RAM") from exc
        except httpx.HTTPError as exc:
            raise ConnectorError("Không kết nối được Ollama tại địa chỉ đã cấu hình") from exc
        except ImportError as exc:
            raise ConnectorError("Môi trường HTTP local chưa sẵn sàng") from exc
        except ValueError as exc:
            raise ConnectorError("Phản hồi Ollama không phải JSON hợp lệ") from exc


class GeminiConnector:
    name = "gemini"

    async def health(self) -> ProviderHealth:
        if not settings.gemini_api_key:
            return ProviderHealth(False, settings.gemini_model, "Chưa cấu hình GEMINI_API_KEY")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}"
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(url, headers={"x-goog-api-key": settings.gemini_api_key})
                response.raise_for_status()
            return ProviderHealth(True, settings.gemini_model, "API key và model hợp lệ")
        except httpx.HTTPStatusError as exc:
            return ProviderHealth(False, settings.gemini_model, _api_error(exc.response))
        except (httpx.HTTPError, ImportError):
            return ProviderHealth(False, settings.gemini_model, "Không kết nối được Gemini")

    async def generate(self, safe_prompt: str, history: list[dict]) -> AIResult:
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY chưa được cấu hình")
        contents = []
        for item in history[-settings.memory_recent_messages:]:
            role = "model" if item["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": item["content_sanitized"]}]})
        contents.append({"role": "user", "parts": [{"text": safe_prompt}]})
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent"
        payload = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": contents,
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": settings.gemini_max_output_tokens},
        }
        headers = {"x-goog-api-key": settings.gemini_api_key}
        _record_egress(self.name, url, payload)
        try:
            async with httpx.AsyncClient(timeout=settings.ai_timeout_seconds) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
            # Phản hồi có thể chia nhiều part; bỏ part "thought" của model suy luận.
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(str(p.get("text", "")) for p in parts if not p.get("thought")).strip()
            if not text:
                raise ConnectorError("Gemini không trả về nội dung")
            return AIResult(text, self.name, settings.gemini_model)
        except httpx.HTTPStatusError as exc:
            raise ConnectorError(_api_error(exc.response)) from exc
        except httpx.TimeoutException as exc:
            raise ConnectorError("Timeout khi chờ Gemini") from exc
        except httpx.HTTPError as exc:
            raise ConnectorError("Không kết nối được Gemini") from exc
        except ImportError as exc:
            raise ConnectorError("Cấu hình HTTP proxy chưa đầy đủ") from exc
        except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
            raise ConnectorError("Cấu trúc phản hồi Gemini không hợp lệ") from exc
