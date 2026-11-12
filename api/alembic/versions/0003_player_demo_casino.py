"""add isolated player accounts and demo game credits

Revision ID: 0003
Revises: 0002
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "player_credentials",
        sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("failed_login_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "failed_login_attempts >= 0",
            name=op.f("ck_player_credentials_failed_attempts_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["player_id"], ["players.id"], name=op.f("fk_player_credentials_player_id_players"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("player_id", name=op.f("pk_player_credentials")),
    )
    op.create_table(
        "player_sessions",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f("ck_player_sessions_expires_after_created")
        ),
        sa.ForeignKeyConstraint(
            ["player_id"], ["players.id"], name=op.f("fk_player_sessions_player_id_players"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_player_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_player_sessions_token_hash")),
    )
    op.create_index(op.f("ix_player_sessions_player_id"), "player_sessions", ["player_id"], unique=False)

    op.create_table(
        "demo_credit_wallets",
        sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("balance", sa.Integer(), server_default=sa.text("1000"), nullable=False),
        sa.Column("last_refilled_on", sa.Date(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "balance >= 0 AND balance <= 1000",
            name=op.f("ck_demo_credit_wallets_balance_in_demo_range"),
        ),
        sa.ForeignKeyConstraint(
            ["player_id"], ["players.id"], name=op.f("fk_demo_credit_wallets_player_id_players"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("player_id", name=op.f("pk_demo_credit_wallets")),
    )

    op.create_table(
        "demo_game_rounds",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("game_code", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'in_progress'"), nullable=False),
        sa.Column("stake", sa.Integer(), nullable=False),
        sa.Column("state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("outcome", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "game_code IN ('slots', 'blackjack')",
            name=op.f("ck_demo_game_rounds_game_code_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('in_progress', 'completed', 'voided')",
            name=op.f("ck_demo_game_rounds_status_allowed"),
        ),
        sa.CheckConstraint("stake BETWEEN 10 AND 100", name=op.f("ck_demo_game_rounds_stake_in_demo_range")),
        sa.ForeignKeyConstraint(
            ["player_id"], ["players.id"], name=op.f("fk_demo_game_rounds_player_id_players"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_demo_game_rounds")),
    )
    op.create_index(
        op.f("ix_demo_game_rounds_player_created"),
        "demo_game_rounds",
        ["player_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_demo_game_rounds_player_active_blackjack",
        "demo_game_rounds",
        ["player_id"],
        unique=True,
        postgresql_where=sa.text("game_code = 'blackjack' AND status = 'in_progress'"),
    )

    op.create_table(
        "demo_credit_entries",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=30), nullable=False),
        sa.Column("round_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("delta <> 0", name=op.f("ck_demo_credit_entries_delta_nonzero")),
        sa.CheckConstraint(
            "reason IN ('initial_credit', 'daily_refill', 'wager', 'payout', 'refund')",
            name=op.f("ck_demo_credit_entries_reason_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["player_id"], ["players.id"], name=op.f("fk_demo_credit_entries_player_id_players"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["round_id"], ["demo_game_rounds.id"], name=op.f("fk_demo_credit_entries_round_id_demo_game_rounds"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_demo_credit_entries")),
    )
    op.create_index(
        op.f("ix_demo_credit_entries_player_created"),
        "demo_credit_entries",
        ["player_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_demo_credit_entries_player_created"), table_name="demo_credit_entries")
    op.drop_table("demo_credit_entries")
    op.drop_index("uq_demo_game_rounds_player_active_blackjack", table_name="demo_game_rounds")
    op.drop_index(op.f("ix_demo_game_rounds_player_created"), table_name="demo_game_rounds")
    op.drop_table("demo_game_rounds")
    op.drop_table("demo_credit_wallets")
    op.drop_index(op.f("ix_player_sessions_player_id"), table_name="player_sessions")
    op.drop_table("player_sessions")
    op.drop_table("player_credentials")
