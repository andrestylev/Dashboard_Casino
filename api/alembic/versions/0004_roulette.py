"""allow European roulette demo rounds

Revision ID: 0004
Revises: 0003
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_demo_game_rounds_game_code_allowed"),
        "demo_game_rounds",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_demo_game_rounds_game_code_allowed"),
        "demo_game_rounds",
        "game_code IN ('slots', 'blackjack', 'roulette')",
    )


def downgrade() -> None:
    has_roulette_rounds = op.get_bind().execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM demo_game_rounds WHERE game_code = 'roulette')")
    ).scalar_one()
    if has_roulette_rounds:
        raise RuntimeError("Cannot downgrade while roulette rounds exist")
    op.drop_constraint(
        op.f("ck_demo_game_rounds_game_code_allowed"),
        "demo_game_rounds",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_demo_game_rounds_game_code_allowed"),
        "demo_game_rounds",
        "game_code IN ('slots', 'blackjack')",
    )
