from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select

from app.models.enums import (
    AlertSeverity,
    AlertStatus,
    AlertType,
    KycStatus,
    PlayerStatus,
    TransactionStatus,
    TransactionType,
    VipTier,
)
from app.models.games import Bet, Game, GameCategory, GameSession
from app.models.players import Player, Transaction, Wallet
from app.models.risk import RiskAlert
from app.models.security import AuditLog
from app.schemas import (
    AuditRead,
    BetRead,
    GameRead,
    Page,
    PlayerRead,
    RiskAlertRead,
    TransactionRead,
)
from app.security import DatabaseSession, current_admin, require_super_admin

router = APIRouter(prefix="/api", tags=["casino data"], dependencies=[Depends(current_admin)])
PAGE_SIZE_MAX = 100


def page_bounds(page: int, page_size: int) -> tuple[int, int]:
    return (page - 1) * page_size, page_size


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/players", response_model=Page[PlayerRead])
def list_players(
    db: DatabaseSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=PAGE_SIZE_MAX)] = 25,
    q: Annotated[str | None, Query(max_length=100)] = None,
    status: PlayerStatus | None = None,
    kyc_status: KycStatus | None = None,
    vip_tier: VipTier | None = None,
    country_code: Annotated[
        str | None, Query(min_length=2, max_length=2, pattern="^[A-Za-z]{2}$")
    ] = None,
    registered_after: datetime | None = None,
    registered_before: datetime | None = None,
):
    filters = []
    if q:
        pattern = f"%{escape_like(q.strip())}%"
        filters.append(
            Player.username.ilike(pattern, escape="\\")
            | Player.email.ilike(pattern, escape="\\")
            | Player.first_name.ilike(pattern, escape="\\")
            | Player.last_name.ilike(pattern, escape="\\")
        )
    if status is not None:
        filters.append(Player.status == status)
    if kyc_status is not None:
        filters.append(Player.kyc_status == kyc_status)
    if vip_tier is not None:
        filters.append(Player.vip_tier == vip_tier)
    if country_code is not None:
        filters.append(Player.country_code == country_code.upper())
    if registered_after is not None:
        filters.append(Player.registered_at >= registered_after)
    if registered_before is not None:
        filters.append(Player.registered_at <= registered_before)

    base = select(Player).outerjoin(Wallet, Wallet.player_id == Player.id).where(*filters)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    offset, limit = page_bounds(page, page_size)
    rows = db.execute(
        select(Player, Wallet.balance)
        .outerjoin(Wallet, Wallet.player_id == Player.id)
        .where(*filters)
        .order_by(Player.registered_at.desc(), Player.id.desc())
        .offset(offset)
        .limit(limit)
    )
    items = [
        PlayerRead.model_validate(player).model_copy(update={"wallet_balance": balance})
        for player, balance in rows
    ]
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/players/{player_id}", response_model=PlayerRead)
def get_player(player_id: int, db: DatabaseSession):
    row = db.execute(
        select(Player, Wallet.balance)
        .outerjoin(Wallet, Wallet.player_id == Player.id)
        .where(Player.id == player_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Player not found")
    return PlayerRead.model_validate(row[0]).model_copy(update={"wallet_balance": row[1]})


@router.get("/games", response_model=Page[GameRead])
def list_games(
    db: DatabaseSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=PAGE_SIZE_MAX)] = 25,
    category_code: Annotated[str | None, Query(max_length=30)] = None,
    provider: Annotated[str | None, Query(max_length=60)] = None,
    is_active: bool | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
):
    filters = []
    if category_code:
        filters.append(GameCategory.code == category_code.lower())
    if provider:
        filters.append(Game.provider.ilike(f"%{escape_like(provider.strip())}%", escape="\\"))
    if is_active is not None:
        filters.append(Game.is_active.is_(is_active))
    if q:
        filters.append(Game.name.ilike(f"%{escape_like(q.strip())}%", escape="\\"))
    base = select(Game.id).join(GameCategory).where(*filters)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    offset, limit = page_bounds(page, page_size)
    rows = db.execute(
        select(Game, GameCategory)
        .join(GameCategory, Game.category_id == GameCategory.id)
        .where(*filters)
        .order_by(Game.name, Game.id)
        .offset(offset)
        .limit(limit)
    )
    items = [
        GameRead(
            id=game.id,
            category_code=category.code,
            category_name=category.name,
            name=game.name,
            provider=game.provider,
            theoretical_rtp=game.theoretical_rtp,
            volatility=game.volatility,
            min_bet=game.min_bet,
            max_bet=game.max_bet,
            is_active=game.is_active,
            released_at=game.released_at,
        )
        for game, category in rows
    ]
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/transactions", response_model=Page[TransactionRead])
def list_transactions(
    db: DatabaseSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=PAGE_SIZE_MAX)] = 25,
    player_id: int | None = None,
    type: TransactionType | None = None,
    status: TransactionStatus | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
):
    filters = []
    if player_id is not None:
        filters.append(Transaction.player_id == player_id)
    if type is not None:
        filters.append(Transaction.type == type)
    if status is not None:
        filters.append(Transaction.status == status)
    if created_after is not None:
        filters.append(Transaction.created_at >= created_after)
    if created_before is not None:
        filters.append(Transaction.created_at <= created_before)
    base = select(Transaction.id).where(*filters)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    offset, limit = page_bounds(page, page_size)
    rows = db.scalars(
        select(Transaction)
        .where(*filters)
        .order_by(Transaction.created_at.desc(), Transaction.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return Page(
        items=[TransactionRead.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/bets", response_model=Page[BetRead])
def list_bets(
    db: DatabaseSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=PAGE_SIZE_MAX)] = 25,
    player_id: int | None = None,
    game_id: int | None = None,
    is_win: bool | None = None,
    placed_after: datetime | None = None,
    placed_before: datetime | None = None,
):
    filters = []
    if player_id is not None:
        filters.append(GameSession.player_id == player_id)
    if game_id is not None:
        filters.append(GameSession.game_id == game_id)
    if is_win is not None:
        filters.append(Bet.is_win.is_(is_win))
    if placed_after is not None:
        filters.append(Bet.placed_at >= placed_after)
    if placed_before is not None:
        filters.append(Bet.placed_at <= placed_before)
    base = select(Bet.id).join(GameSession).where(*filters)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    offset, limit = page_bounds(page, page_size)
    rows = db.execute(
        select(Bet, GameSession.player_id, GameSession.game_id)
        .join(GameSession, Bet.session_id == GameSession.id)
        .where(*filters)
        .order_by(Bet.placed_at.desc(), Bet.id.desc())
        .offset(offset)
        .limit(limit)
    )
    items = [
        BetRead(
            id=bet.id,
            player_id=player_id_value,
            game_id=game_id_value,
            session_id=bet.session_id,
            stake=bet.stake,
            payout=bet.payout,
            is_win=bet.is_win,
            placed_at=bet.placed_at,
        )
        for bet, player_id_value, game_id_value in rows
    ]
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/risk-alerts", response_model=Page[RiskAlertRead])
def list_risk_alerts(
    db: DatabaseSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=PAGE_SIZE_MAX)] = 25,
    player_id: int | None = None,
    alert_type: AlertType | None = None,
    severity: AlertSeverity | None = None,
    status: AlertStatus | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
):
    filters = []
    if player_id is not None:
        filters.append(RiskAlert.player_id == player_id)
    if alert_type is not None:
        filters.append(RiskAlert.alert_type == alert_type)
    if severity is not None:
        filters.append(RiskAlert.severity == severity)
    if status is not None:
        filters.append(RiskAlert.status == status)
    if created_after is not None:
        filters.append(RiskAlert.created_at >= created_after)
    if created_before is not None:
        filters.append(RiskAlert.created_at <= created_before)
    base = select(RiskAlert.id).where(*filters)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    offset, limit = page_bounds(page, page_size)
    rows = db.scalars(
        select(RiskAlert)
        .where(*filters)
        .order_by(RiskAlert.created_at.desc(), RiskAlert.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return Page(
        items=[RiskAlertRead.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/audit-log",
    response_model=Page[AuditRead],
    dependencies=[Depends(require_super_admin)],
)
def list_audit_log(
    db: DatabaseSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=PAGE_SIZE_MAX)] = 25,
    admin_user_id: int | None = None,
    action: Annotated[str | None, Query(max_length=60)] = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
):
    filters = []
    if admin_user_id is not None:
        filters.append(AuditLog.admin_user_id == admin_user_id)
    if action is not None:
        filters.append(AuditLog.action == action)
    if created_after is not None:
        filters.append(AuditLog.created_at >= created_after)
    if created_before is not None:
        filters.append(AuditLog.created_at <= created_before)
    base = select(AuditLog.id).where(*filters)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    offset, limit = page_bounds(page, page_size)
    rows = db.scalars(
        select(AuditLog)
        .where(*filters)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return Page(
        items=[AuditRead.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )
