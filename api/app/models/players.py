from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Money, TZDateTime, enum_type, now_column
from app.models.enums import (
    BonusStatus,
    BonusType,
    Channel,
    KycStatus,
    PaymentMethod,
    PlayerStatus,
    TransactionStatus,
    TransactionType,
    VipTier,
)


class Player(Base):
    """A casino customer. Never deleted: close the account with status = 'closed'."""

    __tablename__ = "players"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    username: Mapped[str] = mapped_column(String(40), unique=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    birth_date: Mapped[date] = mapped_column(Date)
    country_code: Mapped[str] = mapped_column(String(2))
    status: Mapped[PlayerStatus] = mapped_column(
        enum_type(PlayerStatus, "player_status"), server_default=text("'active'")
    )
    kyc_status: Mapped[KycStatus] = mapped_column(
        enum_type(KycStatus, "kyc_status"), server_default=text("'pending'")
    )
    vip_tier: Mapped[VipTier] = mapped_column(
        enum_type(VipTier, "vip_tier"), server_default=text("'standard'")
    )
    registration_channel: Mapped[Channel] = mapped_column(
        enum_type(Channel, "registration_channel")
    )
    registered_at: Mapped[datetime] = now_column()
    last_login_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    self_exclusion_until: Mapped[datetime | None] = mapped_column(TZDateTime)
    deposit_limit_monthly: Mapped[Decimal | None] = mapped_column(Money)
    loss_limit_monthly: Mapped[Decimal | None] = mapped_column(Money)
    updated_at: Mapped[datetime] = now_column(on_update=True)

    __table_args__ = (
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        CheckConstraint("country_code = upper(country_code)", name="country_code_uppercase"),
        CheckConstraint(
            "birth_date <= ((registered_at AT TIME ZONE 'UTC')::date - INTERVAL '18 years')",
            name="adult_at_registration",
        ),
        CheckConstraint(
            "(deposit_limit_monthly IS NULL OR deposit_limit_monthly > 0)"
            " AND (loss_limit_monthly IS NULL OR loss_limit_monthly > 0)",
            name="limits_positive",
        ),
        Index("ix_players_status", "status"),
        Index("ix_players_registered_at", "registered_at"),
        Index("ix_players_country_code", "country_code"),
    )


class PlayerNote(Base):
    """Internal notes written by staff (support can add them)."""

    __tablename__ = "player_notes"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    player_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    admin_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("admin_users.id", ondelete="RESTRICT")
    )
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = now_column()


class Wallet(Base):
    """One wallet per player (single currency). Primary key = the player's id."""

    __tablename__ = "wallets"

    player_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("players.id", ondelete="RESTRICT"), primary_key=True
    )
    balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))
    updated_at: Mapped[datetime] = now_column(on_update=True)

    __table_args__ = (CheckConstraint("balance >= 0", name="balance_non_negative"),)


class Transaction(Base):
    """Money movements of a wallet. `amount` is always positive; the type gives the direction."""

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    player_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("wallets.player_id", ondelete="RESTRICT")
    )
    type: Mapped[TransactionType] = mapped_column(enum_type(TransactionType, "transaction_type"))
    status: Mapped[TransactionStatus] = mapped_column(
        enum_type(TransactionStatus, "transaction_status"), server_default=text("'pending'")
    )
    amount: Mapped[Decimal] = mapped_column(Money)
    method: Mapped[PaymentMethod | None] = mapped_column(enum_type(PaymentMethod, "payment_method"))
    created_at: Mapped[datetime] = now_column()
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    external_ref: Mapped[str | None] = mapped_column(String(64), unique=True)
    created_by_admin_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("admin_users.id", ondelete="RESTRICT")
    )
    note: Mapped[str | None] = mapped_column(String(255))
    ip_address: Mapped[str | None] = mapped_column(INET)

    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        # deposits/withdrawals go through a payment method; bonus credits and adjustments do not
        CheckConstraint(
            "(type IN ('deposit', 'withdrawal')) = (method IS NOT NULL)", name="method_matches_type"
        ),
        # manual adjustments must say who did it and why
        CheckConstraint(
            "type <> 'adjustment' OR (created_by_admin_id IS NOT NULL AND note IS NOT NULL)",
            name="adjustment_needs_admin_and_note",
        ),
        CheckConstraint(
            "(status = 'completed') = (completed_at IS NOT NULL)",
            name="completed_at_matches_status",
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= created_at", name="completed_after_created"
        ),
        Index("ix_transactions_player_id_created_at", "player_id", "created_at"),
        Index("ix_transactions_created_at", "created_at"),
        Index("ix_transactions_type_status", "type", "status"),
    )


class Bonus(Base):
    __tablename__ = "bonuses"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    player_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("players.id", ondelete="RESTRICT"), index=True
    )
    type: Mapped[BonusType] = mapped_column(enum_type(BonusType, "bonus_type"))
    status: Mapped[BonusStatus] = mapped_column(
        enum_type(BonusStatus, "bonus_status"), server_default=text("'active'")
    )
    amount: Mapped[Decimal] = mapped_column(Money)
    wagering_multiplier: Mapped[Decimal] = mapped_column(Numeric(5, 2))  # e.g. 30.00 = 30x
    wagered_amount: Mapped[Decimal] = mapped_column(Money, server_default=text("0"))
    granted_at: Mapped[datetime] = now_column()
    expires_at: Mapped[datetime] = mapped_column(TZDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    transaction_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("transactions.id", ondelete="RESTRICT"), unique=True
    )

    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("wagering_multiplier >= 0", name="wagering_non_negative"),
        CheckConstraint("wagered_amount >= 0", name="wagered_non_negative"),
        CheckConstraint("expires_at > granted_at", name="expires_after_granted"),
        CheckConstraint(
            "(status = 'completed') = (completed_at IS NOT NULL)",
            name="completed_at_matches_status",
        ),
        Index("ix_bonuses_status_expires_at", "status", "expires_at"),
    )
