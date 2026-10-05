from app.config import Settings


def test_gemini_model_accepts_accidental_models_prefix(monkeypatch):
    # Dùng tên khác hẳn giá trị trong .env, để test chỉ pass khi Settings() thật
    # sự đọc lại biến môi trường lúc khởi tạo.
    monkeypatch.setenv("GEMINI_MODEL", "models/test-model-xyz")
    configured = Settings()
    assert configured.gemini_model == "test-model-xyz"


def test_settings_reads_environment_at_creation(monkeypatch):
    monkeypatch.setenv("MEMORY_RETENTION_DAYS", "3")
    monkeypatch.setenv("EGRESS_LOG_ENABLED", "yes")
    configured = Settings()
    assert configured.memory_retention_days == 3
    assert configured.egress_log_enabled is True
