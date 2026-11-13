"""Importing this package registers every table on Base.metadata (needed by Alembic)."""

from app.models.base import Base
from app.models.games import Bet, Game, GameCategory, GameSession
from app.models.player_casino import (
    DemoCreditEntry,
    DemoCreditWallet,
    DemoGameRound,
    PlayerChipEntry,
    PlayerChipWallet,
    PlayerCredential,
    PlayerSession,
    PlayerVipSubscription,
)
from app.models.players import Bonus, Player, PlayerNote, Transaction, Wallet
from app.models.risk import RiskAlert
from app.models.security import AdminRecoveryCode, AdminSession, AdminUser, AuditLog, Role

__all__ = [
    "AdminRecoveryCode",
    "AdminSession",
    "AdminUser",
    "AuditLog",
    "Base",
    "Bet",
    "Bonus",
    "DemoCreditEntry",
    "DemoCreditWallet",
    "DemoGameRound",
    "PlayerChipEntry",
    "PlayerChipWallet",
    "Game",
    "GameCategory",
    "GameSession",
    "Player",
    "PlayerCredential",
    "PlayerNote",
    "PlayerSession",
    "PlayerVipSubscription",
    "RiskAlert",
    "Role",
    "Transaction",
    "Wallet",
]
