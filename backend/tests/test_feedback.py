from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Feedback, User
from app.schemas import FeedbackCreate


def _db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_feedback_table_is_registered_with_expected_columns():
    table = Base.metadata.tables["feedback"]
    assert table.c.user_id.nullable is False
    assert table.c.user_id.foreign_keys
    assert table.c.content.nullable is False
    assert table.c.contact.nullable is True
    assert table.c.category.nullable is False


def test_feedback_create_defaults_to_other_category_and_trims_content():
    payload = FeedbackCreate(content="  帮我看看这个问题  ")
    assert payload.category == "other"
    assert payload.content == "帮我看看这个问题"
    assert payload.contact is None


def test_feedback_create_rejects_blank_content():
    with pytest.raises(ValidationError):
        FeedbackCreate(content="   ")


def test_feedback_create_normalizes_blank_contact_to_none():
    payload = FeedbackCreate(content="有个建议", contact="   ")
    assert payload.contact is None


def test_feedback_rows_persist_and_list_newest_first():
    db = _db()
    user = User(username="feedback-user", password_hash="hash")
    db.add(user)
    db.flush()

    first = Feedback(user_id=user.id, category="bug", content="第一条反馈")
    db.add(first)
    db.commit()
    second = Feedback(user_id=user.id, category="suggestion", content="第二条反馈")
    db.add(second)
    db.commit()

    rows = db.scalars(
        select(Feedback)
        .where(Feedback.user_id == user.id)
        .order_by(Feedback.created_at.desc(), Feedback.id.desc())
    ).all()
    assert [row.id for row in rows] == [second.id, first.id]
    assert rows[0].category == "suggestion"
    assert rows[1].content == "第一条反馈"
