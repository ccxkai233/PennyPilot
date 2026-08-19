from app.config import Settings


def test_prefixed_environment_aliases_and_cors_parser(monkeypatch):
    monkeypatch.setenv("PENNYPILOT_DATABASE_URL", "postgresql+psycopg://u:p@db:5432/ledger")
    monkeypatch.setenv("PENNYPILOT_SECRET_KEY", "test-secret")
    monkeypatch.setenv("PENNYPILOT_CORS_ORIGINS", "http://localhost:5173, https://example.test")

    settings = Settings(_env_file=None)

    assert settings.database_url.endswith("@db:5432/ledger")
    assert settings.secret_key == "test-secret"
    assert settings.cors_origins == ["http://localhost:5173", "https://example.test"]


def test_legacy_unprefixed_aliases_are_still_supported(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@legacy:5432/ledger")
    monkeypatch.setenv("SECRET_KEY", "legacy-secret")

    settings = Settings(_env_file=None)

    assert settings.database_url.endswith("@legacy:5432/ledger")
    assert settings.secret_key == "legacy-secret"


def test_ai_fallback_aliases_are_supported(monkeypatch):
    monkeypatch.setenv("PENNYPILOT_SECRET_KEY", "test-secret")
    monkeypatch.setenv("PENNYPILOT_AI_FALLBACK_BASE_URL", "https://backup.example")
    monkeypatch.setenv("PENNYPILOT_AI_FALLBACK_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("PENNYPILOT_AI_FALLBACK_API_KEY", "backup-key")

    settings = Settings(_env_file=None)

    assert settings.ai_fallback_base_url == "https://backup.example"
    assert settings.ai_fallback_model == "gpt-4o-mini"
    assert settings.ai_fallback_api_key == "backup-key"
