"""Add the built-in salary income category for existing users.

The insert is deliberately data-preserving and idempotent.  A user's existing
category (including an inactive or customized row) is never changed or
duplicated.  The downgrade is intentionally a no-op because this migration
cannot distinguish a row it inserted from one a user created independently.
"""

# Revision ID: 20260805_0005_salary_category
# Revises: 20260804_0004_settlements

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260805_0005_salary_category"
down_revision: Union[str, Sequence[str], None] = "20260804_0004_settlements"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use a correlated NOT EXISTS predicate instead of a blind bulk insert so
    # rerunning the statement, or upgrading a partially populated database,
    # cannot create duplicate (user, name, direction) rows.
    op.execute(
        sa.text(
            """
            INSERT INTO categories
                (user_id, name, direction, icon, sort_order, is_active)
            SELECT
                u.id,
                '工资收入',
                'income',
                '💼',
                COALESCE(
                    (
                        SELECT MAX(existing.sort_order) + 1
                        FROM categories AS existing
                        WHERE existing.user_id = u.id
                    ),
                    0
                ),
                TRUE
            FROM users AS u
            WHERE NOT EXISTS (
                SELECT 1
                FROM categories AS current_category
                WHERE current_category.user_id = u.id
                  AND current_category.name = '工资收入'
                  AND current_category.direction = 'income'
            )
            """
        )
    )


def downgrade() -> None:
    # Do not delete by name: a user may have created or edited this category
    # after the upgrade, and the migration has no ownership marker to tell the
    # rows apart safely.
    pass
