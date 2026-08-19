"""Authentication helpers and in-process login abuse protection.

The application uses opaque, random session tokens in an HttpOnly cookie.  A
small process-local limiter protects the login endpoint from password guessing
without adding another database table or service to the MVP.  Deployments
that run multiple worker processes should put a shared rate limiter (or an
API gateway limit) in front of the application as well; the local limiter is
still useful as a last line of defence in every worker.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address, ip_network
from math import ceil
import secrets
from threading import RLock
from time import monotonic
from typing import Callable

from fastapi import HTTPException, Request
from passlib.context import CryptContext
from passlib.exc import UnknownHashError
from sqlalchemy.orm import Session

from .config import get_settings
from .models import SessionToken, User


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
settings = get_settings()

# A fixed valid bcrypt hash makes a username-enumeration attempt pay the same
# password-verification cost as a real account.  The value is never accepted
# as a real user's password because it is not disclosed to clients.
_DUMMY_PASSWORD_HASH = "$2b$12$qW.1X0v/ZObmrCgz.aqOieQ9NRm/rtt9UvS8BnTMxyfboDf9s69H6"


@dataclass
class _AttemptState:
    failures: deque[float] = field(default_factory=deque)
    blocked_until: float = 0.0


class LoginRateLimiter:
    """Thread-safe sliding-window limiter keyed by client IP address.

    ``check`` returns the number of seconds a caller should wait, or ``None``
    when an attempt is allowed.  ``record_failure`` records an unsuccessful
    password check and starts a temporary block after ``max_attempts`` in the
    configured window.  A successful login clears the IP's failure history.
    The clock is injectable to make the behaviour deterministic in tests.
    """

    def __init__(
        self,
        max_attempts: int,
        window_seconds: int,
        block_seconds: int,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if max_attempts < 1 or window_seconds < 1 or block_seconds < 1:
            raise ValueError("login limiter values must all be positive")
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.block_seconds = block_seconds
        self._clock = clock
        self._states: dict[str, _AttemptState] = {}
        self._lock = RLock()

    @staticmethod
    def _retry_after(until: float, now: float) -> int:
        return max(1, ceil(until - now))

    def _prune(self, key: str, state: _AttemptState, now: float) -> None:
        while state.failures and now - state.failures[0] >= self.window_seconds:
            state.failures.popleft()
        if state.blocked_until and state.blocked_until <= now:
            state.blocked_until = 0.0

    def check(self, key: str) -> int | None:
        now = self._clock()
        with self._lock:
            state = self._states.get(key)
            if state is None:
                return None
            self._prune(key, state, now)
            state = self._states.get(key)
            if state is not None and not state.failures and not state.blocked_until:
                self._states.pop(key, None)
                state = None
            if state is not None and state.blocked_until > now:
                return self._retry_after(state.blocked_until, now)
            return None

    def record_failure(self, key: str) -> int | None:
        now = self._clock()
        with self._lock:
            state = self._states.setdefault(key, _AttemptState())
            self._prune(key, state, now)
            # A request that races with another failed request while the IP is
            # blocked must not extend the block indefinitely.
            if state.blocked_until > now:
                return self._retry_after(state.blocked_until, now)
            state.failures.append(now)
            if len(state.failures) >= self.max_attempts:
                state.failures.clear()
                state.blocked_until = now + self.block_seconds
                return self._retry_after(state.blocked_until, now)
            return None

    def record_success(self, key: str) -> None:
        with self._lock:
            self._states.pop(key, None)

    def reset(self) -> None:
        """Clear all state (useful for tests and controlled maintenance)."""

        with self._lock:
            self._states.clear()


login_limiter = LoginRateLimiter(
    settings.login_rate_limit,
    settings.login_rate_window_seconds,
    settings.login_block_seconds,
)


def get_client_ip(request: Request) -> str:
    """Return a stable client key, honoring forwarded headers only from a proxy.

    Caddy forwards the original address in ``X-Forwarded-For``.  That header
    is accepted only when the immediate peer is explicitly configured as a
    trusted proxy; otherwise a caller cannot spoof the limiter key by sending
    a header directly to Uvicorn.
    """

    peer = request.client.host if request.client else "unknown"
    peer_is_trusted = False
    try:
        peer_address = ip_address(peer)
        for configured_proxy in settings.trusted_proxy_ips:
            try:
                if peer_address == ip_address(configured_proxy):
                    peer_is_trusted = True
                    break
            except ValueError:
                if peer_address in ip_network(configured_proxy, strict=False):
                    peer_is_trusted = True
                    break
    except ValueError:
        pass

    if peer_is_trusted:
        forwarded = request.headers.get("x-forwarded-for", "")
        for candidate in forwarded.split(","):
            candidate = candidate.strip()
            try:
                ip_address(candidate)
            except ValueError:
                continue
            return candidate
    return peer or "unknown"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(password, hashed)
    except (ValueError, UnknownHashError):
        # A corrupt/legacy hash should behave like an invalid credential, not
        # turn a login request into a 500 response.
        return False


def verify_password_or_dummy(password: str, hashed: str | None) -> bool:
    """Verify a password while keeping the missing-user path timing-safe."""

    return verify_password(password, hashed or _DUMMY_PASSWORD_HASH)


def create_session(db: Session, user: User) -> SessionToken:
    session = SessionToken(
        token=secrets.token_urlsafe(48),
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.session_ttl_days),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def current_user(request: Request, db: Session) -> User:
    token = request.cookies.get(settings.cookie_name)
    session = db.get(SessionToken, token) if token else None
    expires_at = session.expires_at if session else None
    if expires_at is not None and expires_at.tzinfo is None:
        # PostgreSQL returns timezone-aware values for our column, while
        # SQLite/test fixtures may return naive UTC values.
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if not session or expires_at is None or expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = db.get(User, session.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Inactive user")
    return user
