from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.security import AdminSession, AdminUser, Role
from app.schemas import AdminRead, LoginRequest, RegistrationRequest
from app.security import (
    SESSION_COOKIE,
    AdminPrincipal,
    DatabaseSession,
    add_audit,
    clear_session_cookie,
    create_session,
    current_admin,
    password_hasher,
    record_failed_login,
    set_session_cookie,
    token_digest,
    user_by_username,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["authentication"])


def admin_read(user: AdminUser, role: Role) -> AdminRead:
    return AdminRead(
        id=user.id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        role=role.name,
    )


def invalid_login() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid username or password",
    )


def build_login_response(
    db: Session,
    request: Request,
    user: AdminUser,
    role: Role,
    response: Response,
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
    return {"admin": admin_read(user, role).model_dump(mode="json")}


@router.post("/register", status_code=status.HTTP_202_ACCEPTED)
def register(payload: RegistrationRequest, request: Request, db: DatabaseSession):
    username = payload.username.lower().strip()
    email = payload.email.lower().strip()
    full_name = payload.full_name.strip()
    if len(full_name) < 2:
        raise HTTPException(status_code=422, detail="Enter your full name")

    support_role = db.scalar(select(Role).where(Role.name == "support"))
    if support_role is None:
        raise HTTPException(status_code=500, detail="Support role is not configured")

    user = AdminUser(
        username=username,
        email=email,
        password_hash=password_hasher.hash(payload.password),
        full_name=full_name,
        role_id=support_role.id,
        is_active=False,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email is already registered",
        ) from exc

    add_audit(
        db,
        request,
        "auth.registration_requested",
        admin_user_id=user.id,
        resource_type="admin_user",
        resource_id=str(user.id),
    )
    db.commit()
    return {"status": "pending_approval"}


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DatabaseSession,
):
    username = payload.username.lower().strip()
    user = user_by_username(db, username, lock=True)
    role = db.get(Role, user.role_id) if user is not None else None
    now = datetime.now(UTC)

    if user is None or role is None or not user.is_active:
        record_failed_login(db, user, request, username)
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
        record_failed_login(db, user, request, username)
        db.commit()
        raise invalid_login()

    return build_login_response(db, request, user, role, response)


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
