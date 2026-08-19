from fastapi.middleware.cors import CORSMiddleware

from app.main import app


def test_database_schema_is_not_created_by_a_startup_hook():
    # Database changes must be explicit and auditable via Alembic.
    assert app.router.on_startup == []


def test_cors_allows_configured_cookie_credentials():
    cors = next(middleware for middleware in app.user_middleware if middleware.cls is CORSMiddleware)

    assert cors.kwargs["allow_credentials"] is True
    assert "http://localhost:5173" in cors.kwargs["allow_origins"]
