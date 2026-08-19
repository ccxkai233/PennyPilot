from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.main import DEFAULT_CATEGORIES, _ensure_default_categories
from app.models import Category, User


def _db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_default_categories_include_salary_income():
    assert ("工资收入", "income", "💼") in DEFAULT_CATEGORIES


def test_default_category_initialization_is_idempotent_and_preserves_existing_rows():
    db = _db()
    user = User(username="category-defaults", password_hash="hash")
    db.add(user)
    db.flush()
    existing_salary = Category(
        user_id=user.id,
        name="工资收入",
        direction="income",
        icon="custom",
        sort_order=42,
        is_active=False,
    )
    db.add(existing_salary)
    db.commit()

    first_added = _ensure_default_categories(db, user.id)
    db.commit()
    second_added = _ensure_default_categories(db, user.id)
    db.commit()

    rows = db.scalars(
        select(Category).where(Category.user_id == user.id)
    ).all()
    salary_rows = [
        row
        for row in rows
        if row.name == "工资收入" and row.direction == "income"
    ]
    assert first_added == len(DEFAULT_CATEGORIES) - 1
    assert second_added == 0
    assert len(salary_rows) == 1
    assert salary_rows[0].id == existing_salary.id
    assert salary_rows[0].icon == "custom"
    assert salary_rows[0].sort_order == 42
    assert salary_rows[0].is_active is False
    assert {
        (row.name, row.direction)
        for row in rows
    } == {(name, direction) for name, direction, _ in DEFAULT_CATEGORIES}
