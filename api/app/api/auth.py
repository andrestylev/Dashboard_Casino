import secrets
from datetime import UTC, datetime
from typing import Annotated

import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.security import AdminRecoveryCode, AdminSession, AdminUser, Role
from app.schemas import AdminRead, LoginRequest, TotpEnableRequest
from app.security import (
    SESSION_COOKIE,
    AdminPrincipal,
    DatabaseSession,
    add_audit,
    clear_session_cookie,
    consume_recovery_code,
    create_session,
    current_admin,
    record_failed_login,
    recovery_code_digest,
    set_session_cookie,
    token_digest,
    totp_is_valid,
    user_by_email,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["authentication"])


def admin_read(user: AdminUser, role: Role) -> AdminRead:
    return AdminRead(id=user.id, email=user.email, full_name=user.full_name, role=role.name)


def invalid_login() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials or verification code",
    )


def build_login_response(
    db: Session,
    request: Request,
    user: AdminUser,
    role: Role,
    response: Response,
    *,
    recovery_codes: list[str] | None = None,
) -> dict:
    now = datetime.now(UTC)
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    user.updated_at = now
    token = create_session(db, user, request)
    add_audit(
        db,
        request,
        "auth.login",
        admin_user_id=user.id,
        resource_type="admin_user",
        resource_id=str(user.id),
    )
    db.commit()
    set_session_cookie(response, token)
    result = {"admin": admin_read(user, role).model_dump(mode="json")}
    if recovery_codes is not None:
        result["recovery_codes"] = recovery_codes
    return result


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DatabaseSession,
):
    if payload.totp_code and payload.recovery_code:
        raise HTTPException(status_code=422, detail="Use either a TOTP code or a recovery code")

    email = payload.email.lower().strip()
    user = user_by_email(db, email, lock=True)
    role = None
    if user is not None:
        role = db.get(Role, user.role_id)
    now = datetime.now(UTC)

    if user is None or role is None or not user.is_active:
        record_failed_login(db, user, request, email)
        db.commit()
        raise invalid_login()

    if user.locked_until is not None and user.locked_until > now:
        add_audit(
            db,
            request,
            "auth.login_locked",
            admin_user_id=user.id,
            resource_type="admin_user",
            resource_id=str(user.id),
        )
        db.commit()
        raise invalid_login()

    if user.locked_until is not None:
        user.failed_login_attempts = 0
        user.locked_until = None

    if not verify_password(user.password_hash, payload.password):
        record_failed_login(db, user, request, email)
        db.commit()
        raise invalid_login()

    if not user.totp_enabled:
        if user.totp_secret is None:
            user.totp_secret = pyotp.random_base32()
        add_audit(
            db,
            request,
            "auth.totp_setup_started",
            admin_user_id=user.id,
            resource_type="admin_user",
            resource_id=str(user.id),
        )
        db.commit()
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "status": "totp_setup_required",
                "provisioning_uri": pyotp.TOTP(user.totp_secret).provisioning_uri(
                    name=user.email, issuer_name="Casino Admin"
                ),
            },
        )

    if user.totp_secret is None:
        raise HTTPException(status_code=500, detail="TOTP is enabled without a configured secret")

    valid = payload.totp_code is not None and totp_is_valid(user.totp_secret, payload.totp_code)
    if payload.recovery_code is not None:
        valid = consume_recovery_code(db, user, payload.recovery_code)
    if not valid:
        record_failed_login(db, user, request, email)
        db.commit()
        raise invalid_login()

    return build_login_response(db, request, user, role, response)


@router.post("/totp/enable", status_code=status.HTTP_200_OK)
def enable_totp(
    payload: TotpEnableRequest,
    request: Request,
    response: Response,
    db: DatabaseSession,
):
    email = payload.email.lower().strip()
    user = user_by_email(db, email, lock=True)
    if (
        user is None
        or not user.is_active
        or not verify_password(user.password_hash, payload.password)
    ):
        record_failed_login(db, user, request, email)
        db.commit()
        raise invalid_login()

    now = datetime.now(UTC)
    if user.locked_until is not None and user.locked_until > now:
        add_audit(
            db,
            request,
            "auth.login_locked",
            admin_user_id=user.id,
            resource_type="admin_user",
            resource_id=str(user.id),
        )
        db.commit()
        raise invalid_login()
    if user.locked_until is not None:
        user.failed_login_attempts = 0
        user.locked_until = None

    role = db.get(Role, user.role_id)
    if role is None:
        raise HTTPException(status_code=500, detail="Administrator role is missing")
    if user.totp_enabled:
        raise HTTPException(status_code=409, detail="TOTP is already enabled")
    if user.totp_secret is None or not totp_is_valid(user.totp_secret, payload.totp_code):
        record_failed_login(db, user, request, email)
        db.commit()
        raise invalid_login()

    user.totp_enabled = True
    recovery_codes = [secrets.token_urlsafe(24) for _ in range(10)]
    db.add_all(
        [
            AdminRecoveryCode(
                admin_user_id=user.id,
                code_hash=recovery_code_digest(code),
            )
            for code in recovery_codes
        ]
    )
    add_audit(
        db,
        request,
        "auth.totp_enabled",
        admin_user_id=user.id,
        resource_type="admin_user",
        resource_id=str(user.id),
    )
    return build_login_response(
        db,
        request,
        user,
        role,
        response,
        recovery_codes=recovery_codes,
    )


@router.post("/refresh")
def refresh(request: Request, response: Response, db: DatabaseSession):
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise invalid_login()
    now = datetime.now(UTC)
    row = db.execute(
        select(AdminSession, AdminUser, Role)
        .join(AdminUser, AdminUser.id == AdminSession.admin_user_id)
        .join(Role, Role.id == AdminUser.role_id)
        .where(
            AdminSession.token_hash == token_digest(token),
            AdminSession.revoked_at.is_(None),
            AdminSession.expires_at > now,
            AdminUser.is_active.is_(True),
            AdminUser.totp_enabled.is_(True),
        )
        .with_for_update()
    ).first()
    if row is None:
        raise invalid_login()
    session, user, role = row
    session.revoked_at = now
    next_token = create_session(db, user, request)
    add_audit(
        db,
        request,
        "auth.session_refreshed",
        admin_user_id=user.id,
        resource_type="admin_session",
        resource_id=str(session.id),
    )
    db.commit()
    set_session_cookie(response, next_token)
    return {"admin": admin_read(user, role).model_dump(mode="json")}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: DatabaseSession):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        session = db.scalar(
            select(AdminSession).where(
                AdminSession.token_hash == token_digest(token),
                AdminSession.revoked_at.is_(None),
            )
        )
        if session is not None:
            session.revoked_at = datetime.now(UTC)
            add_audit(
                db,
                request,
                "auth.logout",
                admin_user_id=session.admin_user_id,
                resource_type="admin_session",
                resource_id=str(session.id),
            )
            db.commit()
    clear_session_cookie(response)


@router.get("/me", response_model=AdminRead)
def me(
    principal: Annotated[AdminPrincipal, Depends(current_admin)],
    db: DatabaseSession,
):
    role = db.scalar(select(Role).where(Role.name == principal.role))
    if role is None:
        raise HTTPException(status_code=500, detail="Administrator role is missing")
    return admin_read(principal.user, role)
