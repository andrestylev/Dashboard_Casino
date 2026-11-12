import hashlib
import ipaddress
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models.player_casino import PlayerSession
from app.models.players import Player

PLAYER_SESSION_COOKIE = "player_session"
PLAYER_SESSION_LIFETIME = timedelta(hours=24)
PLAYER_MAX_FAILED_LOGINS = 5
PLAYER_LOCKOUT_DURATION = timedelta(minutes=15)
player_password_hasher = PasswordHasher()
PlayerDatabaseSession = Annotated[Session, Depends(get_db)]


class PlayerPrincipal:
    def __init__(self, player: Player):
        self.player = player


def player_token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_player_password(password_hash: str, password: str) -> bool:
    try:
        return player_password_hasher.verify(password_hash, password)
    except (VerificationError, VerifyMismatchError):
        return False


def set_player_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        PLAYER_SESSION_COOKIE,
        token,
        max_age=int(PLAYER_SESSION_LIFETIME.total_seconds()),
        httponly=True,
        secure=settings.secure_auth_cookies,
        samesite="strict",
        path="/api/player",
    )


def clear_player_session_cookie(response: Response) -> None:
    response.delete_cookie(
        PLAYER_SESSION_COOKIE,
        httponly=True,
        secure=settings.secure_auth_cookies,
        samesite="strict",
        path="/api/player",
    )


def create_player_session(db: Session, player: Player, request: Request) -> str:
    token = secrets.token_urlsafe(48)
    client_ip = request.client.host if request.client else None
    try:
        if client_ip is not None:
            client_ip = str(ipaddress.ip_address(client_ip))
    except ValueError:
        client_ip = None
    db.add(
        PlayerSession(
            player_id=player.id,
            token_hash=player_token_digest(token),
            expires_at=datetime.now(UTC) + PLAYER_SESSION_LIFETIME,
            ip_address=client_ip,
            user_agent=request.headers.get("user-agent", "")[:255] or None,
        )
    )
    return token


def current_player(
    request: Request,
    db: PlayerDatabaseSession,
) -> PlayerPrincipal:
    token = request.cookies.get(PLAYER_SESSION_COOKIE)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Player authentication required"
        )

    row = db.execute(
        select(PlayerSession, Player)
        .join(Player, Player.id == PlayerSession.player_id)
        .where(
            PlayerSession.token_hash == player_token_digest(token),
            PlayerSession.revoked_at.is_(None),
            PlayerSession.expires_at > datetime.now(UTC),
            Player.status == "active",
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Player authentication required"
        )
    return PlayerPrincipal(row[1])
