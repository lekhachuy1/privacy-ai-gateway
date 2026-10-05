import asyncio

from .connectors import AIResult, GeminiConnector, MockConnector, OllamaConnector


CLOUD_PROVIDERS = {"gemini"}


class AIRouter:
    def __init__(self, settings):
        self.settings = settings
        self.connectors = {
            "mock": MockConnector(),
            "gemini": GeminiConnector(),
            "ollama": OllamaConnector(),
        }

    def select(self, sensitive: bool) -> str:
        if self.settings.ai_mode in self.connectors:
            return self.settings.ai_mode
        if self.settings.ai_mode == "hybrid":
            return self.settings.ai_sensitive_provider if sensitive else self.settings.ai_default_provider
        return "mock"

    async def generate(self, safe_prompt: str, history: list[dict], sensitive: bool) -> AIResult:
        primary_name = self.select(sensitive)
        candidates = [primary_name]
        if self.settings.ai_mode == "hybrid" and not sensitive:
            candidates.append("ollama" if primary_name == "gemini" else "gemini")
        candidates.append(self.settings.ai_fallback_provider)
        candidates.append("mock")
        if sensitive and self.settings.ai_mode not in CLOUD_PROVIDERS:
            # Chỉ khi người dùng chủ động chọn AI_MODE=gemini thì mọi prompt mới đi
            # cloud. Ở hybrid/ollama, dữ liệu nhạy cảm không bao giờ lên cloud, kể cả
            # khi AI_SENSITIVE_PROVIDER hay AI_FALLBACK_PROVIDER bị đặt nhầm là gemini.
            candidates = [n for n in candidates if n not in CLOUD_PROVIDERS]
        failure_notes: list[str] = []
        for name in dict.fromkeys(candidates):
            connector = self.connectors.get(name)
            if not connector:
                continue
            try:
                result = await connector.generate(safe_prompt, history)
                reason = "; ".join(failure_notes) or None
                return AIResult(result.text, result.provider, result.model, reason)
            except Exception as exc:
                detail = " ".join(str(exc).split())[:260] or type(exc).__name__
                failure_notes.append(f"{name}: {detail}")
        raise RuntimeError("Không có AI provider khả dụng")

    async def health(self) -> dict[str, dict]:
        async def check(name, connector):
            try:
                return name, (await connector.health()).public()
            except Exception:
                return name, {
                    "available": False,
                    "model": "unknown",
                    "detail": "Health check gặp lỗi nội bộ",
                }

        checks = await asyncio.gather(
            *(check(name, connector) for name, connector in self.connectors.items())
        )
        return dict(checks)
