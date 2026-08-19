from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.auth import LoginRateLimiter, get_client_ip
from app.config import Settings
from app.main import app
from app.schemas import LoginRequest, UserCreate


def test_production_settings_reject_unsafe_defaults():
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(
            _env_file=None,
            app_env="production",
            secret_key="change-me-in-production",
            cookie_secure=True,
            trusted_hosts=["ledger.gitdo.net"],
            cors_origins=["https://ledger.gitdo.net"],
        )


def test_production_settings_require_https_and_secure_cookie():
    common = {
        "_env_file": None,
        "app_env": "production",
        "secret_key": "s" * 64,
        "trusted_hosts": ["ledger.gitdo.net"],
        "cors_origins": ["https://ledger.gitdo.net"],
    }
    with pytest.raises(ValueError, match="COOKIE_SECURE"):
        Settings(**common, cookie_secure=False)

    insecure_common = {**common, "cors_origins": ["http://ledger.gitdo.net"]}
    with pytest.raises(ValueError, match="HTTPS"):
        Settings(**insecure_common, cookie_secure=True)


def test_production_settings_accept_public_host_and_normalize_values():
    settings = Settings(
        _env_file=None,
        app_env="prod",
        secret_key="s" * 64,
        cookie_secure=True,
        cookie_samesite="LAX",
        trusted_hosts="ledger.gitdo.net, localhost",
        cors_origins="https://ledger.gitdo.net/",
    )

    assert settings.app_env == "production"
    assert settings.trusted_hosts == ["ledger.gitdo.net", "localhost"]
    assert settings.cors_origins == ["https://ledger.gitdo.net"]


def test_security_middleware_is_configured():
    middleware_classes = {middleware.cls for middleware in app.user_middleware}
    assert TrustedHostMiddleware in middleware_classes
    cors = next(middleware for middleware in app.user_middleware if middleware.cls is CORSMiddleware)
    assert cors.kwargs["allow_credentials"] is True
    assert "*" not in cors.kwargs["allow_origins"]


@dataclass
class _FakeClock:
    value: float = 0.0

    def __call__(self) -> float:
        return self.value


def test_login_rate_limiter_blocks_and_clears_on_success():
    clock = _FakeClock()
    limiter = LoginRateLimiter(3, 60, 120, clock=clock)

    assert limiter.check("203.0.113.8") is None
    assert limiter.record_failure("203.0.113.8") is None
    assert limiter.record_failure("203.0.113.8") is None
    retry_after = limiter.record_failure("203.0.113.8")
    assert retry_after == 120
    assert limiter.check("203.0.113.8") == 120

    clock.value += 121
    assert limiter.check("203.0.113.8") is None
    limiter.record_failure("203.0.113.8")
    limiter.record_success("203.0.113.8")
    assert limiter.check("203.0.113.8") is None


def test_login_rate_limiter_window_expires_old_failures():
    clock = _FakeClock()
    limiter = LoginRateLimiter(2, 10, 30, clock=clock)
    limiter.record_failure("198.51.100.2")
    clock.value = 11
    # The first failure is outside the window, so this does not block yet.
    assert limiter.record_failure("198.51.100.2") is None


def test_auth_schemas_reject_whitespace_only_passwords():
    with pytest.raises(ValueError, match="password must not be blank"):
        UserCreate(username="valid-user", password="        ")
    with pytest.raises(ValueError, match="password must not be blank"):
        LoginRequest(username="valid-user", password="        ")


def test_trusted_proxy_network_can_supply_forwarded_client_ip(monkeypatch):
    from app import auth

    monkeypatch.setattr(auth.settings, "trusted_proxy_ips", ["172.20.0.0/16"])
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/auth/login",
        "headers": [(b"x-forwarded-for", b"203.0.113.9, 172.20.0.5")],
        "client": ("172.20.0.5", 12345),
        "server": ("127.0.0.1", 8000),
        "scheme": "http",
        "query_string": b"",
    }
    assert get_client_ip(Request(scope)) == "203.0.113.9"
