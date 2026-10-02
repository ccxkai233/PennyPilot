"""Application settings.

The first version of the project used ``PENNYPILOT_`` as the settings
prefix, while the checked-in ``.env.example`` (and a number of deployment
guides) used un-prefixed names such as ``DATABASE_URL``.  Explicit aliases
let us accept both forms during the transition.  The prefixed names are the
canonical form and are what we document for new deployments.
"""

from functools import lru_cache
from ipaddress import ip_address, ip_network
import json
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1", "test", "testserver"}
AIApiFormat = Literal["openai", "anthropic", "gemini"]

_INSECURE_SECRET_KEYS = {
    "change-me-in-production",
    "replace-with-a-long-random-secret",
    "secret",
    "secret-key",
}


class Settings(BaseSettings):
    app_name: str = Field(
        default="PennyPilot",
        validation_alias=AliasChoices("PENNYPILOT_APP_NAME", "APP_NAME"),
    )
    app_env: Literal["development", "staging", "production"] = Field(
        default="development",
        validation_alias=AliasChoices("PENNYPILOT_APP_ENV", "APP_ENV"),
    )
    log_level: Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"] = Field(
        default="INFO",
        validation_alias=AliasChoices("PENNYPILOT_LOG_LEVEL", "LOG_LEVEL"),
    )
    database_url: str = Field(
        # Match docker-compose.yml's development fallback so a fresh checkout
        # works even before a local .env is created.
        default="postgresql+psycopg://pennypilot:pennypilot_dev_password@localhost:5432/pennypilot",
        validation_alias=AliasChoices("PENNYPILOT_DATABASE_URL", "DATABASE_URL"),
    )
    secret_key: str = Field(
        default="change-me-in-production",
        validation_alias=AliasChoices("PENNYPILOT_SECRET_KEY", "SECRET_KEY"),
    )
    cookie_name: str = Field(
        default="pennypilot_session",
        validation_alias=AliasChoices("PENNYPILOT_COOKIE_NAME", "COOKIE_NAME"),
    )
    cookie_secure: bool = Field(
        default=False,
        validation_alias=AliasChoices("PENNYPILOT_COOKIE_SECURE", "COOKIE_SECURE"),
    )
    cookie_samesite: Literal["lax", "strict", "none"] = Field(
        default="lax",
        validation_alias=AliasChoices("PENNYPILOT_COOKIE_SAMESITE", "COOKIE_SAMESITE"),
    )
    # ``NoDecode`` lets the validator below handle comma-separated values as
    # well as JSON.  Without it pydantic-settings attempts JSON decoding before
    # field validators run and rejects the convenient comma-separated form.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"],
        validation_alias=AliasChoices("PENNYPILOT_CORS_ORIGINS", "CORS_ORIGINS"),
    )
    session_ttl_days: int = Field(
        default=7,
        validation_alias=AliasChoices("PENNYPILOT_SESSION_TTL_DAYS", "SESSION_TTL_DAYS"),
        ge=1,
        le=365,
    )
    trusted_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "[::1]", "test", "testserver"],
        validation_alias=AliasChoices("PENNYPILOT_TRUSTED_HOSTS", "TRUSTED_HOSTS"),
    )
    trusted_proxy_ips: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["127.0.0.1", "::1"],
        validation_alias=AliasChoices("PENNYPILOT_TRUSTED_PROXY_IPS", "TRUSTED_PROXY_IPS"),
    )
    login_rate_limit: int = Field(
        default=5,
        validation_alias=AliasChoices("PENNYPILOT_LOGIN_RATE_LIMIT", "LOGIN_RATE_LIMIT"),
        ge=1,
        le=100,
    )
    login_rate_window_seconds: int = Field(
        default=60,
        validation_alias=AliasChoices(
            "PENNYPILOT_LOGIN_RATE_WINDOW_SECONDS", "LOGIN_RATE_WINDOW_SECONDS"
        ),
        ge=1,
        le=86_400,
    )
    login_block_seconds: int = Field(
        default=300,
        validation_alias=AliasChoices("PENNYPILOT_LOGIN_BLOCK_SECONDS", "LOGIN_BLOCK_SECONDS"),
        ge=1,
        le=86_400,
    )
    # AI settings are deliberately optional.  An installation without a
    # provider configured still has a deterministic local parser/analyser;
    # this keeps the bookkeeping API usable when the model provider is down.
    # ``repr=False`` prevents accidental secret disclosure if a Settings
    # instance is included in an exception or debug representation.
    ai_base_url: str = Field(
        default="https://api.openai.com",
        validation_alias=AliasChoices(
            "PENNYPILOT_AI_BASE_URL", "AI_BASE_URL", "OPENAI_BASE_URL"
        ),
    )
    ai_fallback_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "PENNYPILOT_AI_FALLBACK_BASE_URL",
            "AI_FALLBACK_BASE_URL",
            "OPENAI_FALLBACK_BASE_URL",
        ),
    )
    ai_api_key: str | None = Field(
        default=None,
        repr=False,
        validation_alias=AliasChoices(
            "PENNYPILOT_AI_API_KEY", "AI_API_KEY", "OPENAI_API_KEY"
        ),
    )
    ai_fallback_api_key: str | None = Field(
        default=None,
        repr=False,
        validation_alias=AliasChoices(
            "PENNYPILOT_AI_FALLBACK_API_KEY",
            "AI_FALLBACK_API_KEY",
            "OPENAI_FALLBACK_API_KEY",
        ),
    )
    # Wire protocol spoken by each channel: OpenAI chat completions, the
    # Anthropic Messages API, or Gemini generateContent.
    ai_api_format: AIApiFormat = Field(
        default="openai",
        validation_alias=AliasChoices("PENNYPILOT_AI_API_FORMAT", "AI_API_FORMAT"),
    )
    ai_fallback_api_format: AIApiFormat | None = Field(
        default=None,
        validation_alias=AliasChoices("PENNYPILOT_AI_FALLBACK_API_FORMAT", "AI_FALLBACK_API_FORMAT"),
    )
    ai_model: str = Field(
        default="gpt-4o-mini",
        validation_alias=AliasChoices("PENNYPILOT_AI_MODEL", "AI_MODEL", "OPENAI_MODEL"),
    )
    ai_fallback_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "PENNYPILOT_AI_FALLBACK_MODEL",
            "AI_FALLBACK_MODEL",
            "OPENAI_FALLBACK_MODEL",
        ),
    )
    ai_timeout_seconds: float = Field(
        default=15.0,
        validation_alias=AliasChoices("PENNYPILOT_AI_TIMEOUT_SECONDS", "AI_TIMEOUT_SECONDS"),
        ge=2.0,
        le=60.0,
    )
    ai_max_response_bytes: int = Field(
        default=262_144,
        validation_alias=AliasChoices(
            "PENNYPILOT_AI_MAX_RESPONSE_BYTES", "AI_MAX_RESPONSE_BYTES"
        ),
        ge=4_096,
        le=4_194_304,
    )
    ai_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("PENNYPILOT_AI_ENABLED", "AI_ENABLED"),
    )
    # Development can opt into the deterministic parser for diagnostics. In
    # production we disable it so a provider outage is never mistaken for an
    # AI decision.
    ai_local_fallback: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "PENNYPILOT_AI_LOCAL_FALLBACK", "AI_LOCAL_FALLBACK"
        ),
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> Any:
        """Accept either a JSON list or a comma-separated environment value."""

        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return [item.strip() for item in raw.split(",") if item.strip()]
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
            raise ValueError("cors_origins must be a JSON list or comma-separated URLs")
        return value

    @field_validator("trusted_hosts", mode="before")
    @classmethod
    def parse_trusted_hosts(cls, value: Any) -> Any:
        """Accept JSON or comma-separated host names for TrustedHostMiddleware."""

        return cls._parse_list_value(value, "trusted_hosts")

    @field_validator("trusted_proxy_ips", mode="before")
    @classmethod
    def parse_trusted_proxy_ips(cls, value: Any) -> Any:
        values = cls._parse_list_value(value, "trusted_proxy_ips")
        if isinstance(values, list):
            for item in values:
                try:
                    ip_address(item)
                except (TypeError, ValueError) as exc:
                    try:
                        ip_network(item, strict=False)
                    except (TypeError, ValueError):
                        raise ValueError(f"invalid trusted proxy IP/network: {item}") from exc
        return values

    @field_validator("app_env", "cookie_samesite", "log_level", mode="before")
    @classmethod
    def normalize_enums(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip().lower()
            # These aliases are convenient in shell environments while the
            # canonical values remain explicit in generated configuration.
            aliases = {"dev": "development", "stage": "staging", "prod": "production"}
            if value in {"critical", "error", "warning", "info", "debug"}:
                return value.upper()
            return aliases.get(value, value)
        return value

    @field_validator("trusted_hosts", mode="after")
    @classmethod
    def validate_trusted_hosts(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for host in value:
            host = str(host).strip().lower()
            if not host:
                continue
            if "://" in host or "/" in host:
                raise ValueError("trusted_hosts must contain host names, not URLs or paths")
            # TrustedHostMiddleware accepts a leading wildcard only (for
            # example ``*.example.test``).  A bare wildcard is too broad when
            # credentials are in use and is rejected below for all environments.
            if host == "*" or ("*" in host and not host.startswith("*.")):
                raise ValueError("trusted_hosts wildcard must use the *.example.test form")
            if host not in normalized:
                normalized.append(host)
        if not normalized:
            raise ValueError("trusted_hosts must contain at least one host")
        return normalized

    @field_validator("cors_origins", mode="after")
    @classmethod
    def validate_cors_origins(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for origin in value:
            origin = str(origin).strip().rstrip("/")
            if not origin:
                continue
            if origin == "*":
                raise ValueError("cors_origins cannot contain '*' when credentials are enabled")
            parsed = urlsplit(origin)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"invalid CORS origin: {origin}")
            if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
                raise ValueError(f"CORS origin must not include a path or query: {origin}")
            if origin not in normalized:
                normalized.append(origin)
        return normalized

    @field_validator("ai_base_url", mode="after")
    @classmethod
    def validate_ai_base_url(cls, value: str) -> str:
        return cls._validate_ai_base_url_value(value)

    @staticmethod
    def _validate_ai_base_url_value(value: str) -> str:
        value = value.strip().rstrip("/")
        if not value:
            raise ValueError("ai_base_url must not be blank")
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("ai_base_url must be an http(s) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("ai_base_url must not contain credentials, query, or fragment")
        return value

    @field_validator("ai_api_format", "ai_fallback_api_format", mode="before")
    @classmethod
    def normalize_ai_api_format(cls, value: Any, info: ValidationInfo) -> Any:
        if isinstance(value, str):
            # Compose passes an unset variable through as an empty string.
            return value.strip().lower() or ("openai" if info.field_name == "ai_api_format" else None)
        return value

    @field_validator("ai_fallback_base_url", mode="before")
    @classmethod
    def trim_ai_fallback_base_url(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("ai_fallback_base_url", mode="after")
    @classmethod
    def validate_ai_fallback_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return cls._validate_ai_base_url_value(value)

    @field_validator("ai_api_key", "ai_fallback_api_key", "ai_model", "ai_fallback_model", mode="before")
    @classmethod
    def trim_ai_strings(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("ai_model", mode="after")
    @classmethod
    def validate_ai_model(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 200:
            raise ValueError("ai_model must contain 1-200 characters")
        return value

    @staticmethod
    def _parse_list_value(value: Any, field_name: str) -> Any:
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return [item.strip() for item in raw.split(",") if item.strip()]
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
            raise ValueError(f"{field_name} must be a JSON list or comma-separated values")
        return value

    @model_validator(mode="after")
    def validate_security_settings(self) -> "Settings":
        """Fail fast for settings that would make a production deployment unsafe."""

        if self.cookie_samesite == "none" and not self.cookie_secure:
            raise ValueError("cookie_secure must be true when cookie_samesite is 'none'")

        # CORS middleware is configured with credentials, so a wildcard is
        # never a safe value.  This is also checked by the field validator for
        # clearer errors when Settings is instantiated directly.
        if "*" in self.cors_origins:
            raise ValueError("cors_origins cannot contain '*' when credentials are enabled")

        if self.app_env == "production":
            if len(self.secret_key) < 32 or self.secret_key in _INSECURE_SECRET_KEYS:
                raise ValueError(
                    "PENNYPILOT_SECRET_KEY must be at least 32 characters and non-default in production"
                )
            if not self.cookie_secure:
                raise ValueError("PENNYPILOT_COOKIE_SECURE must be true in production")
            if all(host in _LOCAL_HOSTS for host in self.trusted_hosts):
                raise ValueError(
                    "PENNYPILOT_TRUSTED_HOSTS must include the public application host in production"
                )
            insecure_origins = [origin for origin in self.cors_origins if not origin.startswith("https://")]
            if insecure_origins:
                raise ValueError(
                    "production CORS origins must use HTTPS: " + ", ".join(insecure_origins)
                )
            # Plain HTTP is useful for a local development provider, but must
            # not be silently enabled for a public production deployment.
            if self.ai_base_url.startswith("http://") and not any(
                host in self.ai_base_url for host in ("localhost", "127.0.0.1", "[::1]")
            ):
                raise ValueError("production ai_base_url must use HTTPS")
            if self.ai_fallback_base_url and self.ai_fallback_base_url.startswith("http://") and not any(
                host in self.ai_fallback_base_url for host in ("localhost", "127.0.0.1", "[::1]")
            ):
                raise ValueError("production fallback ai_base_url must use HTTPS")
        return self

    model_config = SettingsConfigDict(
        # Resolve the repository-level .env even when commands are run from
        # ``backend/`` (the documented Alembic/uvicorn working directory).
        env_file=(Path(__file__).resolve().parents[2] / ".env", ".env"),
        # Every setting has explicit aliases above.  Keeping this empty avoids
        # accidentally turning an alias into ``PENNYPILOT_PENNYPILOT_*``.
        env_prefix="",
        populate_by_name=True,
        extra="ignore",
        case_sensitive=False,
    )

@lru_cache
def get_settings() -> Settings:
    return Settings()
