"""Add canonical partner website while preserving legacy email data.

The original partners table exposed an ``email`` column.  The profile form now
uses a website URL, but old clients and records still depend on email.  Keep
that column, add a nullable website column, and only migrate values that look
like URLs; ordinary email addresses remain untouched.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260805_0006_partner_website"
down_revision: Union[str, Sequence[str], None] = "20260805_0005_salary_category"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("partners", sa.Column("website", sa.String(length=2048), nullable=True))
    # Do not reinterpret arbitrary email addresses as URLs. Existing URL-like
    # values are copied while the legacy email column remains intact.
    op.execute(
        sa.text(
            """
            UPDATE partners
            SET website = trim(email)
            WHERE website IS NULL
              AND email IS NOT NULL
              AND (
                lower(trim(email)) LIKE 'http://%'
                OR lower(trim(email)) LIKE 'https://%'
                OR lower(trim(email)) LIKE 'www.%'
              )
            """
        )
    )


def downgrade() -> None:
    op.drop_column("partners", "website")
