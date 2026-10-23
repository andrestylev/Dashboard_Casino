"""Value sets used by the schema. Stored as VARCHAR + CHECK (not native PG enums)."""

from enum import StrEnum


class PlayerStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    SELF_EXCLUDED = "self_excluded"
    CLOSED = "closed"


class KycStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class VipTier(StrEnum):
    STANDARD = "standard"
    SILVER = "silver"
    GOLD = "gold"
    PLATINUM = "platinum"
    DIAMOND = "diamond"


class Channel(StrEnum):
    WEB = "web"
    MOBILE = "mobile"


class DeviceType(StrEnum):
    DESKTOP = "desktop"
    MOBILE = "mobile"
    TABLET = "tablet"


class TransactionType(StrEnum):
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    BONUS_CREDIT = "bonus_credit"
    ADJUSTMENT = "adjustment"


class TransactionStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PaymentMethod(StrEnum):
    CARD = "card"
    E_WALLET = "e_wallet"
    BANK_TRANSFER = "bank_transfer"
    CRYPTO = "crypto"


class BonusType(StrEnum):
    WELCOME = "welcome"
    DEPOSIT_MATCH = "deposit_match"
    FREE_SPINS = "free_spins"
    CASHBACK = "cashback"
    LOYALTY = "loyalty"


class BonusStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    EXPIRED = "expired"
    FORFEITED = "forfeited"


class Volatility(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AlertType(StrEnum):
    RAPID_DEPOSITS = "rapid_deposits"
    STRUCTURED_WITHDRAWALS = "structured_withdrawals"
    SHARED_DEVICE = "shared_device"
    LOSS_CHASING = "loss_chasing"
    UNUSUAL_BET_SIZE = "unusual_bet_size"


class AlertSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertStatus(StrEnum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"
