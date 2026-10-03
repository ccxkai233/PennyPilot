"""Add AI conversation history.

Revision ID: 20261003_0012_ai_conversations
Revises: 20261002_0011_ai_api_format

Questions asked on the transactions page, the answers, the tool steps and
any change proposals are kept per conversation so a thread survives a page
reload and can be reopened later.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261003_0012_ai_conversations"
down_revision: Union[str, Sequence[str], None] = "20261002_0011_ai_api_format"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "ai_conversation_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=True),
        sa.Column("proposals", sa.JSON(), nullable=True),
        sa.Column("report_id", sa.Integer(), nullable=True),
        sa.Column("period_label", sa.String(length=100), nullable=True),
        sa.Column("warning", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("ai_conversation_messages")
    op.drop_table("ai_conversations")
