"""add simulated USD, chip wallets, and VIP subscriptions

Revision ID: 0005
Revises: 0004
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    over_limit_wallet = bind.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM wallets WHERE balance > 500000)")
    ).scalar_one()
    if over_limit_wallet:
        raise RuntimeError(
            "Cannot add the simulated wallet limit: an existing USD wallet exceeds $500,000"
        )

    op.add_column(
        "transactions",
        sa.Column(
            "origin",
            sa.String(length=40),
            server_default=sa.text("'seeded_demo'"),
            nullable=False,
        ),
    )
    op.alter_column(
        "transactions",
        "type",
        existing_type=sa.String(length=12),
        type_=sa.String(length=14),
        existing_nullable=False,
    )
    op.drop_constraint(
        op.f("ck_transactions_transaction_type"), "transactions", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_transactions_transaction_type"),
        "transactions",
        "type IN ('deposit', 'withdrawal', 'bonus_credit', 'adjustment', "
        "'chip_purchase', 'vip_membership')",
    )
    op.create_check_constraint(
        op.f("ck_wallets_balance_maximum"), "wallets", "balance <= 500000"
    )

    op.create_table(
        "player_chip_wallets",
        sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("balance", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "balance >= 0 AND balance <= 10000000",
            name=op.f("ck_player_chip_wallets_balance_in_chip_range"),
        ),
        sa.ForeignKeyConstraint(
            ["player_id"], ["players.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("player_id"),
    )
    op.create_table(
        "player_chip_entries",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("delta", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(length=30), nullable=False),
        sa.Column("round_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "delta <> 0",
            name=op.f("ck_player_chip_entries_delta_nonzero"),
        ),
        sa.CheckConstraint(
            "reason IN ('migration', 'chip_purchase', 'wager', 'payout', 'refund')",
            name=op.f("ck_player_chip_entries_reason_allowed"),
        ),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["round_id"], ["demo_game_rounds.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_player_chip_entries_player_created"),
        "player_chip_entries",
        ["player_id", "created_at"],
    )
    op.create_table(
        "player_vip_subscriptions",
        sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("tier", sa.String(length=8), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "tier IN ('standard', 'silver', 'gold', 'platinum', 'diamond')",
            name=op.f("ck_player_vip_subscriptions_vip_subscription_tier"),
        ),
        sa.CheckConstraint(
            "tier <> 'standard'",
            name=op.f("ck_player_vip_subscriptions_paid_tier_only"),
        ),
        sa.CheckConstraint(
            "amount > 0",
            name=op.f("ck_player_vip_subscriptions_amount_positive"),
        ),
        sa.CheckConstraint(
            "expires_at > started_at",
            name=op.f("ck_player_vip_subscriptions_expires_after_started"),
        ),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("player_id"),
    )

    bind.execute(
        sa.text(
            "INSERT INTO wallets (player_id, balance) "
            "SELECT id, 0 FROM players ON CONFLICT (player_id) DO NOTHING"
        )
    )
    bind.execute(
        sa.text(
            "INSERT INTO player_chip_wallets (player_id, balance) "
            "SELECT p.id, COALESCE(d.balance, 0) "
            "FROM players AS p LEFT JOIN demo_credit_wallets AS d ON d.player_id = p.id"
        )
    )
    bind.execute(
        sa.text(
            "INSERT INTO player_chip_entries (player_id, delta, reason) "
            "SELECT player_id, balance, 'migration' FROM demo_credit_wallets WHERE balance > 0"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    has_economy_data = bind.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM player_chip_entries) "
            "OR EXISTS (SELECT 1 FROM player_vip_subscriptions) "
            "OR EXISTS (SELECT 1 FROM transactions "
            "WHERE type IN ('chip_purchase', 'vip_membership'))"
        )
    ).scalar_one()
    if has_economy_data:
        raise RuntimeError("Cannot downgrade while simulated economy data exists")

    op.drop_table("player_vip_subscriptions")
    op.drop_index(
        op.f("ix_player_chip_entries_player_created"),
        table_name="player_chip_entries",
    )
    op.drop_table("player_chip_entries")
    op.drop_table("player_chip_wallets")
    op.drop_constraint(op.f("ck_wallets_balance_maximum"), "wallets", type_="check")
    op.drop_constraint(
        op.f("ck_transactions_transaction_type"), "transactions", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_transactions_transaction_type"),
        "transactions",
        "type IN ('deposit', 'withdrawal', 'bonus_credit', 'adjustment')",
    )
    op.drop_column("transactions", "origin")
