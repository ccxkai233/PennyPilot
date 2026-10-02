"""Add the API format of each AI channel.

Revision ID: 20261002_0011_ai_api_format
Revises: 20260819_0010_feedback

A channel can now speak the OpenAI, Anthropic or Gemini wire format.  NULL
keeps the deployment default (OpenAI-compatible), so existing rows behave
exactly as before.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261002_0011_ai_api_format"
down_revision: Union[str, Sequence[str], None] = "20260819_0010_feedback"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ai_configs", sa.Column("api_format", sa.String(length=16), nullable=True))
    op.add_column("ai_configs", sa.Column("fallback_api_format", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_configs", "fallback_api_format")
    op.drop_column("ai_configs", "api_format")
