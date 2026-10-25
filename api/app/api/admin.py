from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import String, cast, exists, func, select

from app.models.security import AdminUser, AuditLog, Role
from app.schemas import AdminRead, Page, PendingAdminRead
from app.security import (
    AdminPrincipal,
    DatabaseSession,
    add_audit,
    require_super_admin,
)

router = APIRouter(
    prefix="/api/admin",
    tags=["administrator management"],
    dependencies=[Depends(require_super_admin)],
)


@router.get("/pending-registrations", response_model=Page[PendingAdminRead])
def pending_registrations(
    db: DatabaseSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
):
    registration_request = exists(
        select(AuditLog.id).where(
            AuditLog.action == "auth.registration_requested",
            AuditLog.resource_type == "admin_user",
            AuditLog.resource_id == cast(AdminUser.id, String),
        )
    )
    statement = select(AdminUser).where(
        AdminUser.is_active.is_(False),
        registration_request,
    )
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = db.scalars(
        statement.order_by(AdminUser.created_at.desc(), AdminUser.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return Page(
        items=[PendingAdminRead.model_validate(user) for user in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/users/{user_id}/approve", response_model=AdminRead)
def approve_registration(
    user_id: int,
    request: Request,
    principal: Annotated[AdminPrincipal, Depends(require_super_admin)],
    db: DatabaseSession,
):
    registration_request = exists(
        select(AuditLog.id).where(
            AuditLog.action == "auth.registration_requested",
            AuditLog.resource_type == "admin_user",
            AuditLog.resource_id == cast(AdminUser.id, String),
        )
    )
    user = db.scalar(
        select(AdminUser)
        .where(
            AdminUser.id == user_id,
            AdminUser.is_active.is_(False),
            registration_request,
        )
        .with_for_update()
    )
    if user is None:
        raise HTTPException(status_code=404, detail="Administrator not found")
    support_role = db.scalar(select(Role).where(Role.name == "support"))
    if support_role is None:
        raise HTTPException(status_code=500, detail="Support role is not configured")

    user.role_id = support_role.id
    user.is_active = True
    user.updated_at = datetime.now(UTC)
    add_audit(
        db,
        request,
        "admin.registration_approved",
        admin_user_id=principal.user.id,
        resource_type="admin_user",
        resource_id=str(user.id),
    )
    db.commit()
    return AdminRead(
        id=user.id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        role=support_role.name,
    )
