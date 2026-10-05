import asyncio
from dataclasses import replace

from app.config import settings
from app.services.ai_router import AIRouter
from app.services.connectors import AIResult, ProviderHealth


class FakeConnector:
    def __init__(self, name: str, *, text: str = "ok", error: str | None = None):
        self.name = name
        self.text = text
        self.error = error
        self.calls = 0

    async def health(self) -> ProviderHealth:
        return ProviderHealth(self.error is None, f"{self.name}-model", self.error or "Sẵn sàng")

    async def generate(self, safe_prompt: str, history: list[dict]) -> AIResult:
        self.calls += 1
        if self.error:
            raise RuntimeError(self.error)
        return AIResult(self.text, self.name, f"{self.name}-model")


def make_router(**overrides):
    configured = replace(
        settings,
        ai_mode="hybrid",
        ai_default_provider="gemini",
        ai_sensitive_provider="ollama",
        ai_fallback_provider="mock",
        **overrides,
    )
    return AIRouter(configured)


def test_hybrid_safe_prompt_falls_back_from_gemini_to_ollama():
    router = make_router()
    gemini = FakeConnector("gemini", error="HTTP 429: hết quota")
    ollama = FakeConnector("ollama", text="local response")
    mock = FakeConnector("mock")
    router.connectors = {"gemini": gemini, "ollama": ollama, "mock": mock}

    result = asyncio.run(router.generate("safe prompt", [], sensitive=False))

    assert result.provider == "ollama"
    assert "gemini: HTTP 429" in result.fallback_reason
    assert gemini.calls == 1
    assert ollama.calls == 1
    assert mock.calls == 0


def test_hybrid_sensitive_prompt_never_falls_back_to_cloud():
    router = make_router()
    gemini = FakeConnector("gemini", text="cloud response")
    ollama = FakeConnector("ollama", error="local unavailable")
    mock = FakeConnector("mock", text="safe fallback")
    router.connectors = {"gemini": gemini, "ollama": ollama, "mock": mock}

    result = asyncio.run(router.generate("[CCCD_01]", [], sensitive=True))

    assert result.provider == "mock"
    assert ollama.calls == 1
    assert gemini.calls == 0
    assert mock.calls == 1


def test_health_returns_model_and_safe_detail():
    router = make_router()
    router.connectors = {
        "mock": FakeConnector("mock"),
        "gemini": FakeConnector("gemini", error="Chưa cấu hình key"),
        "ollama": FakeConnector("ollama"),
    }

    result = asyncio.run(router.health())

    assert result["mock"]["available"] is True
    assert result["gemini"]["available"] is False
    assert result["ollama"]["model"] == "ollama-model"

