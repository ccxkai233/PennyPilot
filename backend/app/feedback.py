"""User feedback submission and history.

Feedback is intentionally append-only: there is no update/delete endpoint, so
a user's own history always matches what was actually submitted. Any
authenticated user can send feedback from any screen without leaving their
current task.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .models import Feedback
from .schemas import FeedbackCreate, FeedbackListResponse, FeedbackRead


router = APIRouter(prefix="/api", tags=["feedback"])


@router.get("/feedback", response_model=FeedbackListResponse)
def list_feedback(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    filters = [Feedback.user_id == user.id]
    total = db.scalar(select(func.count(Feedback.id)).where(*filters)) or 0
    items = db.scalars(
        select(Feedback)
        .where(*filters)
        .order_by(Feedback.created_at.desc(), Feedback.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return FeedbackListResponse(items=items, total=total, page=page, page_size=page_size)


@router.post("/feedback", response_model=FeedbackRead, status_code=status.HTTP_201_CREATED)
def create_feedback(payload: FeedbackCreate, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    feedback = Feedback(user_id=user.id, **payload.model_dump())
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return feedback
