"""Importing this package registers every table on Base.metadata (needed by Alembic)."""

from app.models.base import Base
from app.models.games import Bet, Game, GameCategory, GameSession
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
    "Game",
    "GameCategory",
    "GameSession",
    "Player",
    "PlayerNote",
    "RiskAlert",
    "Role",
    "Transaction",
    "Wallet",
]
