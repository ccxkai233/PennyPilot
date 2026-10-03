import logging
import sys

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .accounting import router as accounting_router
from .ai import router as ai_router
from .feedback import router as feedback_router
from .partners import router as partners_router
from .settlements import router as settlements_router
from .auth import (
    create_session,
    current_user,
    get_client_ip,
    hash_password,
    login_limiter,
    verify_password_or_dummy,
)
from .config import get_settings
from .db import get_db
from .errors import localize_detail, localize_validation_errors
from .models import Category, PaymentMethod, SessionToken, User
from .schemas import LoginRequest, UserCreate, UserRead


settings = get_settings()
# Keep production safeguards (docs disabled, secure cookies) while allowing
# operators to turn on detailed application diagnostics independently through
# PENNYPILOT_LOG_LEVEL.  The app logger is explicitly configured because
# Uvicorn's root logger defaults to INFO and would otherwise hide DEBUG lines.
_app_log_level = getattr(logging, settings.log_level)
_app_logger = logging.getLogger("app")
_app_logger.setLevel(_app_log_level)
if not any(getattr(handler, "_pennypilot_handler", False) for handler in _app_logger.handlers):
    _app_handler = logging.StreamHandler(sys.stderr)
    _app_handler._pennypilot_handler = True
    _app_handler.setLevel(_app_log_level)
    _app_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    _app_logger.addHandler(_app_handler)
_app_logger.propagate = False
logging.getLogger("app.ai_service").setLevel(_app_log_level)
logging.getLogger("app.ai").setLevel(_app_log_level)
logging.getLogger(__name__).info(
    "PennyPilot started app_env=%s log_level=%s ai_enabled=%s ai_local_fallback=%s",
    settings.app_env,
    settings.log_level,
    settings.ai_enabled,
    settings.ai_local_fallback,
)
_docs_enabled = settings.app_env != "production"
app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

# Database changes are explicit and auditable through Alembic. CORS is limited
# to configured front-end origins while allowing the Session cookie.  The
# TrustedHost middleware rejects host-header injection before a route runs.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Requested-With"],
    max_age=600,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if request.url.path.startswith("/api/auth/"):
        response.headers.setdefault("Cache-Control", "no-store")
    if settings.app_env == "production":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response

@app.exception_handler(HTTPException)
async def localized_http_exception(request: Request, exc: HTTPException):
    """Return error details in Chinese; headers such as Retry-After are kept."""

    return JSONResponse({"detail": localize_detail(exc.detail)}, status_code=exc.status_code, headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def localized_validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse({"detail": localize_validation_errors(exc.errors())}, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)


app.include_router(accounting_router)
app.include_router(partners_router)
app.include_router(ai_router)
app.include_router(settlements_router)
app.include_router(feedback_router)


DEFAULT_CATEGORIES = (
    ("进货", "expense", "📦"),
    ("房租", "expense", "🏠"),
    ("水电", "expense", "💡"),
    ("餐饮", "expense", "🍜"),
    ("其他支出", "expense", "🧾"),
    ("销售收入", "income", "💰"),
    ("工资收入", "income", "💼"),
    ("其他收入", "income", "➕"),
)
DEFAULT_PAYMENT_METHODS = (
    ("微信", "💬"),
    ("支付宝", "🔵"),
    ("现金", "💵"),
    ("银行转账", "🏦"),
    ("POS 刷卡", "💳"),
)


def _ensure_default_categories(db: Session, user_id: int) -> int:
    """Add missing built-in categories for one user without overwriting data.

    The helper is intentionally idempotent: an existing category is matched
    by the same ``(name, direction)`` pair regardless of whether the user has
    deactivated or customized it.  Migrations use the same predicate for
    already-created users; registration calls this helper for new users.
    """

    existing = {
        (name, direction)
        for name, direction in db.execute(
            select(Category.name, Category.direction).where(Category.user_id == user_id)
        ).all()
    }
    missing = [
        (name, direction, icon, index)
        for index, (name, direction, icon) in enumerate(DEFAULT_CATEGORIES)
        if (name, direction) not in existing
    ]
    if missing:
        db.add_all(
            Category(
                user_id=user_id,
                name=name,
                direction=direction,
                icon=icon,
                sort_order=index,
            )
            for name, direction, icon, index in missing
        )
    return len(missing)


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}


@app.post("/api/auth/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.username == payload.username)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already exists")

    user = User(username=payload.username, password_hash=hash_password(payload.password))
    db.add(user)
    try:
        db.flush()
        _ensure_default_categories(db, user.id)
        db.add_all(
            PaymentMethod(
                user_id=user.id,
                name=name,
                icon=icon,
                sort_order=index,
                account_role="cash",
                track_balance=True,
                current_balance_cents=0,
            )
            for index, (name, icon) in enumerate(DEFAULT_PAYMENT_METHODS)
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already exists") from exc
    db.refresh(user)
    return user


@app.post("/api/auth/login")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    client_ip = get_client_ip(request)
    retry_after = login_limiter.check(client_ip)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts; try again later",
            headers={"Retry-After": str(retry_after)},
        )

    user = db.scalar(select(User).where(User.username == payload.username))
    password_matches = verify_password_or_dummy(
        payload.password, user.password_hash if user else None
    )
    if not user or not password_matches:
        retry_after = login_limiter.record_failure(client_ip)
        headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers=headers,
        )

    login_limiter.record_success(client_ip)
    session = create_session(db, user)
    response.set_cookie(
        settings.cookie_name,
        session.token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.session_ttl_days * 86400,
        path="/",
    )
    return {"user": UserRead.model_validate(user)}


@app.post("/api/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(settings.cookie_name)
    session = db.get(SessionToken, token) if token else None
    if session:
        db.delete(session)
        db.commit()
    response.delete_cookie(
        settings.cookie_name,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite=settings.cookie_samesite,
    )


@app.get("/api/auth/me", response_model=UserRead)
def me(request: Request, db: Session = Depends(get_db)):
    return current_user(request, db)
