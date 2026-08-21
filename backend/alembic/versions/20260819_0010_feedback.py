"""Add user feedback submissions.

Revision ID: 20260819_0010_feedback
Revises: 20260807_0009_balances

Feedback is a simple append-only table: a user can submit and review their
own submissions from anywhere in the app, so problems can be reported
without leaving the current screen.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260819_0010_feedback"
down_revision: Union[str, Sequence[str], None] = "20260807_0009_balances"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=16), server_default="other", nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("contact", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_feedback_user_id", "feedback", ["user_id"], unique=False)
    op.create_index("ix_feedback_category", "feedback", ["category"], unique=False)
    op.create_index("ix_feedback_created_at", "feedback", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_feedback_created_at", table_name="feedback")
    op.drop_index("ix_feedback_category", table_name="feedback")
    op.drop_index("ix_feedback_user_id", table_name="feedback")
    op.drop_table("feedback")
