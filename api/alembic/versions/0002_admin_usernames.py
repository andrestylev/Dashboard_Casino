"""add usernames for administrator accounts

Revision ID: 0002
Revises: 0001
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("admin_users", sa.Column("username", sa.String(length=40), nullable=True))
    op.execute(
        """
        WITH normalized AS (
            SELECT
                id,
                COALESCE(
                    NULLIF(
                        regexp_replace(lower(split_part(email, '@', 1)), '[^a-z0-9._-]', '', 'g'),
                        ''
                    ),
                    'admin'
                ) AS base
            FROM admin_users
        ),
        duplicates AS (
            SELECT base, count(*) AS total
            FROM normalized
            GROUP BY base
        )
        UPDATE admin_users AS admin
        SET username = CASE
            WHEN duplicates.total = 1 THEN left(normalized.base, 40)
            ELSE left(normalized.base, 30) || '_' || admin.id::text
        END
        FROM normalized
        JOIN duplicates ON duplicates.base = normalized.base
        WHERE admin.id = normalized.id
        """
    )
    op.alter_column("admin_users", "username", nullable=False)
    op.create_check_constraint(
        "ck_admin_users_username_lowercase",
        "admin_users",
        "username = lower(username)",
    )
    op.create_unique_constraint("uq_admin_users_username", "admin_users", ["username"])


def downgrade() -> None:
    op.drop_constraint("uq_admin_users_username", "admin_users", type_="unique")
    op.drop_constraint("ck_admin_users_username_lowercase", "admin_users", type_="check")
    op.drop_column("admin_users", "username")
