from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Money, TZDateTime, enum_type, now_column
from app.models.enums import DeviceType, Volatility


class GameCategory(Base):
    """slots, roulette, blackjack, poker, baccarat, live_casino. Loaded by the seed."""

    __tablename__ = "game_categories"

    id: Mapped[int] = mapped_column(SmallInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(60))


class Game(Base):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    category_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("game_categories.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(100), unique=True)
    provider: Mapped[str] = mapped_column(String(60))
    theoretical_rtp: Mapped[Decimal] = mapped_column(Numeric(5, 2))  # percent, e.g. 96.50
    volatility: Mapped[Volatility] = mapped_column(enum_type(Volatility, "volatility"))
    min_bet: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    max_bet: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    released_at: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (
        CheckConstraint("theoretical_rtp > 0 AND theoretical_rtp <= 100", name="rtp_percent"),
        CheckConstraint("min_bet > 0", name="min_bet_positive"),
        CheckConstraint("max_bet >= min_bet", name="max_bet_gte_min_bet"),
    )


class GameSession(Base):
    """A player's visit to one game: device, IP and country feed the risk rules."""

    __tablename__ = "game_sessions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    player_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("players.id", ondelete="RESTRICT")
    )
    game_id: Mapped[int] = mapped_column(Integer, ForeignKey("games.id", ondelete="RESTRICT"))
    started_at: Mapped[datetime] = now_column()
    ended_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    device_type: Mapped[DeviceType] = mapped_column(enum_type(DeviceType, "device_type"))
    ip_address: Mapped[str | None] = mapped_column(INET)
    country_code: Mapped[str | None] = mapped_column(String(2))
    device_fingerprint: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="ended_after_started"),
        Index("ix_game_sessions_player_id_started_at", "player_id", "started_at"),
        Index("ix_game_sessions_game_id_started_at", "game_id", "started_at"),
        Index("ix_game_sessions_device_fingerprint", "device_fingerprint"),
    )


class Bet(Base):
    """The largest table. GGR of a bet = stake - payout."""

    __tablename__ = "bets"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("game_sessions.id", ondelete="RESTRICT")
    )
    stake: Mapped[Decimal] = mapped_column(Money)
    payout: Mapped[Decimal] = mapped_column(Money, server_default=text("0"))
    placed_at: Mapped[datetime] = now_column()
    is_win: Mapped[bool] = mapped_column(Boolean, Computed("payout > stake", persisted=True))

    __table_args__ = (
        CheckConstraint("stake > 0", name="stake_positive"),
        CheckConstraint("payout >= 0", name="payout_non_negative"),
        Index("ix_bets_session_id_placed_at", "session_id", "placed_at"),
        Index("ix_bets_placed_at", "placed_at"),
    )
