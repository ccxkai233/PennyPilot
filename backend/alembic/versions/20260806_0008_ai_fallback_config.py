"""Add per-user fallback AI configuration fields.

Revision ID: 20260806_0008_ai_fallback_config
Revises: 20260806_0007_financial_accounts

The primary AI configuration stays unchanged; this revision only adds an
optional second provider slot so the UI can persist a backup model/API key.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260806_0008_ai_fallback_config"
down_revision: Union[str, Sequence[str], None] = "20260806_0007_financial_accounts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ai_configs", sa.Column("fallback_base_url", sa.String(length=500), nullable=True))
    op.add_column("ai_configs", sa.Column("fallback_model", sa.String(length=200), nullable=True))
    op.add_column("ai_configs", sa.Column("encrypted_fallback_api_key", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_configs", "encrypted_fallback_api_key")
    op.drop_column("ai_configs", "fallback_model")
    op.drop_column("ai_configs", "fallback_base_url")
