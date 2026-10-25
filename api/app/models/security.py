import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TZDateTime, now_column


class Role(Base):
    """super_admin, support. Rows are loaded by the seed (Phase 2)."""

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(SmallInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(30), unique=True)
    description: Mapped[str | None] = mapped_column(String(200))


class AdminUser(Base):
    """Back-office staff account. Never deleted (audit trail): deactivate with is_active."""

    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    username: Mapped[str] = mapped_column(String(40), unique=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(120))
    role_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("roles.id", ondelete="RESTRICT"), index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    totp_secret: Mapped[str | None] = mapped_column(String(64))
    totp_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    failed_login_attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(TZDateTime)
    last_login_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    created_at: Mapped[datetime] = now_column()
    updated_at: Mapped[datetime] = now_column(on_update=True)

    __table_args__ = (
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        CheckConstraint("username = lower(username)", name="username_lowercase"),
        CheckConstraint("failed_login_attempts >= 0", name="failed_attempts_non_negative"),
        CheckConstraint("NOT totp_enabled OR totp_secret IS NOT NULL", name="totp_secret_required"),
    )


class AdminRecoveryCode(Base):
    """One-time 2FA recovery codes (only the hash is stored)."""

    __tablename__ = "admin_recovery_codes"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    admin_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("admin_users.id", ondelete="CASCADE"), index=True
    )
    code_hash: Mapped[str] = mapped_column(String(255))
    used_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    created_at: Mapped[datetime] = now_column()


class AdminSession(Base):
    """Refresh-token sessions (rotating, revocable). Only the token hash is stored."""

    __tablename__ = "admin_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    admin_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("admin_users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = now_column()
    expires_at: Mapped[datetime] = mapped_column(TZDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(255))

    __table_args__ = (CheckConstraint("expires_at > created_at", name="expires_after_created"),)


class AuditLog(Base):
    """Who did what. admin_user_id is NULL for events with no known user (e.g. unknown login)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    admin_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("admin_users.id", ondelete="RESTRICT")
    )
    action: Mapped[str] = mapped_column(String(60))  # e.g. player.view, player.suspend, export.csv
    resource_type: Mapped[str | None] = mapped_column(String(40))
    resource_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict | None] = mapped_column(JSONB)
    ip_address: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = now_column()

    __table_args__ = (
        Index("ix_audit_log_created_at", "created_at"),
        Index("ix_audit_log_admin_user_id_created_at", "admin_user_id", "created_at"),
    )
