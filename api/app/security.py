import hashlib
import ipaddress
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models.security import AdminSession, AdminUser, AuditLog, Role

password_hasher = PasswordHasher()
DatabaseSession = Annotated[Session, Depends(get_db)]
SESSION_COOKIE = "admin_session"
SESSION_LIFETIME = timedelta(hours=12)
MAX_FAILED_LOGINS = 5
LOCKOUT_DURATION = timedelta(minutes=15)


class AdminPrincipal:
    def __init__(self, user: AdminUser, role: str):
        self.user = user
        self.role = role


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerificationError, VerifyMismatchError):
        return False


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def add_audit(
    db: Session,
    request: Request,
    action: str,
    *,
    admin_user_id: int | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    details: dict | None = None,
) -> None:
    client_ip = request.client.host if request.client else None
    try:
        if client_ip is not None:
            client_ip = str(ipaddress.ip_address(client_ip))
    except ValueError:
        client_ip = None
    db.add(
        AuditLog(
            admin_user_id=admin_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=client_ip,
        )
    )


def record_failed_login(
    db: Session, user: AdminUser | None, request: Request, username: str
) -> None:
    now = datetime.now(UTC)
    if user is not None:
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= MAX_FAILED_LOGINS:
            user.locked_until = now + LOCKOUT_DURATION
    add_audit(
        db,
        request,
        "auth.login_failed",
        admin_user_id=user.id if user else None,
        resource_type="admin_user",
        resource_id=str(user.id) if user else None,
        details={"username": username},
    )


def user_by_username(db: Session, username: str, *, lock: bool = False) -> AdminUser | None:
    statement = select(AdminUser).where(AdminUser.username == username.lower().strip())
    if lock:
        statement = statement.with_for_update()
    return db.scalar(statement)


def create_session(db: Session, user: AdminUser, request: Request) -> str:
    token = secrets.token_urlsafe(48)
    now = datetime.now(UTC)
    client_ip = request.client.host if request.client else None
    try:
        if client_ip is not None:
            client_ip = str(ipaddress.ip_address(client_ip))
    except ValueError:
        client_ip = None
    db.add(
        AdminSession(
            admin_user_id=user.id,
            token_hash=token_digest(token),
            created_at=now,
            expires_at=now + SESSION_LIFETIME,
            ip_address=client_ip,
            user_agent=request.headers.get("user-agent", "")[:255] or None,
        )
    )
    return token


def set_session_cookie(response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        httponly=True,
        secure=settings.secure_auth_cookies,
        samesite="strict",
        path="/api",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(
        SESSION_COOKIE,
        httponly=True,
        secure=settings.secure_auth_cookies,
        samesite="strict",
        path="/api",
    )


def current_admin(
    request: Request,
    db: DatabaseSession,
) -> AdminPrincipal:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    row = db.execute(
        select(AdminSession, AdminUser, Role)
        .join(AdminUser, AdminUser.id == AdminSession.admin_user_id)
        .join(Role, Role.id == AdminUser.role_id)
        .where(
            AdminSession.token_hash == token_digest(token),
            AdminSession.revoked_at.is_(None),
            AdminSession.expires_at > datetime.now(UTC),
            AdminUser.is_active.is_(True),
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    return AdminPrincipal(row[1], row[2].name)


def require_super_admin(
    principal: Annotated[AdminPrincipal, Depends(current_admin)],
) -> AdminPrincipal:
    if principal.role != "super_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
    return principal
