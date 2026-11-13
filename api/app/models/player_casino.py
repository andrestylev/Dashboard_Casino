import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Money, TZDateTime, enum_type, now_column
from app.models.enums import VipTier


class PlayerCredential(Base):
    __tablename__ = "player_credentials"

    player_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    password_hash: Mapped[str] = mapped_column(String(255))
    failed_login_attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(TZDateTime)
    last_login_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    created_at: Mapped[datetime] = now_column()

    __table_args__ = (
        CheckConstraint("failed_login_attempts >= 0", name="failed_attempts_non_negative"),
    )


class PlayerSession(Base):
    __tablename__ = "player_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    player_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = now_column()
    expires_at: Mapped[datetime] = mapped_column(TZDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(255))

    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="expires_after_created"),
    )


class DemoCreditWallet(Base):
    __tablename__ = "demo_credit_wallets"

    player_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    balance: Mapped[int] = mapped_column(Integer, server_default=text("1000"))
    last_refilled_on: Mapped[date] = mapped_column(Date)
    updated_at: Mapped[datetime] = now_column(on_update=True)

    __table_args__ = (
        CheckConstraint("balance >= 0 AND balance <= 1000", name="balance_in_demo_range"),
    )


class DemoCreditEntry(Base):
    __tablename__ = "demo_credit_entries"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    player_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("players.id", ondelete="CASCADE")
    )
    delta: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(30))
    round_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("demo_game_rounds.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = now_column()

    __table_args__ = (
        CheckConstraint("delta <> 0", name="delta_nonzero"),
        CheckConstraint(
            "reason IN ('initial_credit', 'daily_refill', 'wager', 'payout', 'refund')",
            name="reason_allowed",
        ),
        Index("ix_demo_credit_entries_player_created", "player_id", "created_at"),
    )


class PlayerChipWallet(Base):
    __tablename__ = "player_chip_wallets"

    player_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    balance: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    updated_at: Mapped[datetime] = now_column(on_update=True)

    __table_args__ = (
        CheckConstraint("balance >= 0 AND balance <= 10000000", name="balance_in_chip_range"),
    )


class PlayerChipEntry(Base):
    __tablename__ = "player_chip_entries"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    player_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("players.id", ondelete="CASCADE")
    )
    delta: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(String(30))
    round_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("demo_game_rounds.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = now_column()

    __table_args__ = (
        CheckConstraint("delta <> 0", name="delta_nonzero"),
        CheckConstraint(
            "reason IN ('migration', 'chip_purchase', 'wager', 'payout', 'refund')",
            name="reason_allowed",
        ),
        Index("ix_player_chip_entries_player_created", "player_id", "created_at"),
    )


class PlayerVipSubscription(Base):
    __tablename__ = "player_vip_subscriptions"

    player_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    tier: Mapped[VipTier] = mapped_column(enum_type(VipTier, "vip_subscription_tier"))
    started_at: Mapped[datetime] = mapped_column(TZDateTime)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime)
    amount: Mapped[Decimal] = mapped_column(Money)
    updated_at: Mapped[datetime] = now_column(on_update=True)

    __table_args__ = (
        CheckConstraint("tier <> 'standard'", name="paid_tier_only"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("expires_at > started_at", name="expires_after_started"),
    )


class DemoGameRound(Base):
    __tablename__ = "demo_game_rounds"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    player_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("players.id", ondelete="CASCADE")
    )
    game_code: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), server_default=text("'in_progress'"))
    stake: Mapped[int] = mapped_column(Integer)
    state: Mapped[dict] = mapped_column(JSONB)
    outcome: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = now_column()
    updated_at: Mapped[datetime] = now_column(on_update=True)
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    __table_args__ = (
        CheckConstraint(
            "game_code IN ('slots', 'blackjack', 'roulette')",
            name="game_code_allowed",
        ),
        CheckConstraint(
            "status IN ('in_progress', 'completed', 'voided')", name="status_allowed"
        ),
        CheckConstraint("stake BETWEEN 10 AND 100", name="stake_in_demo_range"),
        Index("ix_demo_game_rounds_player_created", "player_id", "created_at"),
        Index(
            "uq_demo_game_rounds_player_active_blackjack",
            "player_id",
            unique=True,
            postgresql_where=text("game_code = 'blackjack' AND status = 'in_progress'"),
        ),
    )
