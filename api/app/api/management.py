import csv
import io
import json
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.read import (
    list_bets,
    list_games,
    list_players,
    list_risk_alerts,
    list_transactions,
)
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
from app.schemas import (
    BetRead,
    GameRead,
    GameStatusUpdate,
    PlayerRead,
    PlayerStatusUpdate,
    RiskAlertRead,
    RiskAlertUpdate,
    TransactionRead,
)
from app.security import (
    AdminPrincipal,
    DatabaseSession,
    add_audit,
    current_admin,
    require_super_admin,
)

router = APIRouter(
    prefix="/api",
    tags=["casino management"],
    dependencies=[Depends(current_admin)],
)
CSV_EXPORT_LIMIT = 10_000
RESOLUTION_STATUSES = {AlertStatus.RESOLVED, AlertStatus.DISMISSED}


@router.get("/games/{game_id}/detail", response_model=GameRead)
def get_game_detail(game_id: int, db: DatabaseSession):
    row = db.execute(
        select(Game, GameCategory)
        .join(GameCategory, Game.category_id == GameCategory.id)
        .where(Game.id == game_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Game not found")
    game, category = row
    return GameRead(
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


@router.get("/transactions/{transaction_id}/detail", response_model=TransactionRead)
def get_transaction_detail(transaction_id: int, db: DatabaseSession):
    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return transaction


@router.get("/bets/{bet_id}/detail", response_model=BetRead)
def get_bet_detail(bet_id: int, db: DatabaseSession):
    row = db.execute(
        select(Bet, GameSession.player_id, GameSession.game_id)
        .join(GameSession, Bet.session_id == GameSession.id)
        .where(Bet.id == bet_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Bet not found")
    bet, player_id, game_id = row
    return BetRead(
        id=bet.id,
        player_id=player_id,
        game_id=game_id,
        session_id=bet.session_id,
        stake=bet.stake,
        payout=bet.payout,
        is_win=bet.is_win,
        placed_at=bet.placed_at,
    )


@router.get("/risk-alerts/{alert_id}/detail", response_model=RiskAlertRead)
def get_risk_alert_detail(alert_id: int, db: DatabaseSession):
    alert = db.get(RiskAlert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Risk alert not found")
    return alert


@router.patch(
    "/players/{player_id}/status",
    response_model=PlayerRead,
    dependencies=[Depends(require_super_admin)],
)
def update_player_status(
    player_id: int,
    body: PlayerStatusUpdate,
    request: Request,
    principal: Annotated[AdminPrincipal, Depends(require_super_admin)],
    db: DatabaseSession,
):
    player = db.scalar(select(Player).where(Player.id == player_id).with_for_update())
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found")
    if player.status == PlayerStatus.CLOSED and body.status != PlayerStatus.CLOSED:
        raise HTTPException(
            status_code=409, detail="Closed player accounts cannot be reactivated"
        )
    if (
        body.status == PlayerStatus.SELF_EXCLUDED
        and player.status != PlayerStatus.SELF_EXCLUDED
    ):
        raise HTTPException(
            status_code=422,
            detail="Self-exclusion must use the dedicated responsible-gaming process",
        )
    if (
        player.status == PlayerStatus.SELF_EXCLUDED
        and body.status != PlayerStatus.SELF_EXCLUDED
        and body.status != PlayerStatus.CLOSED
        and (
            player.self_exclusion_until is None
            or player.self_exclusion_until > datetime.now(UTC)
        )
    ):
        raise HTTPException(
            status_code=409, detail="Active self-exclusion cannot be overridden"
        )

    if player.status == body.status:
        wallet_balance = db.scalar(
            select(Wallet.balance).where(Wallet.player_id == player.id)
        )
        return PlayerRead.model_validate(player).model_copy(
            update={"wallet_balance": wallet_balance}
        )

    previous_status = player.status
    player.status = body.status
    player.updated_at = datetime.now(UTC)
    add_audit(
        db,
        request,
        "player.status_changed",
        admin_user_id=principal.user.id,
        resource_type="player",
        resource_id=str(player.id),
        details={"from": previous_status.value, "to": body.status.value},
    )
    db.flush()
    wallet_balance = db.scalar(
        select(Wallet.balance).where(Wallet.player_id == player.id)
    )
    db.commit()
    return PlayerRead.model_validate(player).model_copy(
        update={"wallet_balance": wallet_balance}
    )


@router.patch(
    "/games/{game_id}/status",
    response_model=GameRead,
    dependencies=[Depends(require_super_admin)],
)
def update_game_status(
    game_id: int,
    body: GameStatusUpdate,
    request: Request,
    principal: Annotated[AdminPrincipal, Depends(require_super_admin)],
    db: DatabaseSession,
):
    row = db.execute(
        select(Game, GameCategory)
        .join(GameCategory, Game.category_id == GameCategory.id)
        .where(Game.id == game_id)
        .with_for_update(of=Game)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Game not found")
    game, category = row
    previous_state = game.is_active
    if previous_state == body.is_active:
        return GameRead(
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
    game.is_active = body.is_active
    add_audit(
        db,
        request,
        "game.availability_changed",
        admin_user_id=principal.user.id,
        resource_type="game",
        resource_id=str(game.id),
        details={"from": previous_state, "to": body.is_active},
    )
    db.commit()
    return GameRead(
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


@router.patch("/risk-alerts/{alert_id}", response_model=RiskAlertRead)
def update_risk_alert(
    alert_id: int,
    body: RiskAlertUpdate,
    request: Request,
    principal: Annotated[AdminPrincipal, Depends(current_admin)],
    db: DatabaseSession,
):
    alert = db.scalar(
        select(RiskAlert).where(RiskAlert.id == alert_id).with_for_update()
    )
    if alert is None:
        raise HTTPException(status_code=404, detail="Risk alert not found")
    if alert.status in RESOLUTION_STATUSES:
        raise HTTPException(status_code=409, detail="Resolved alerts cannot be changed")
    if body.status == AlertStatus.OPEN:
        raise HTTPException(
            status_code=422, detail="Alerts cannot be moved back to open"
        )
    if alert.status == AlertStatus.OPEN and body.status in RESOLUTION_STATUSES:
        raise HTTPException(
            status_code=409, detail="Move the alert to in_review before resolving it"
        )

    previous_status = alert.status
    now = datetime.now(UTC)
    alert.status = body.status
    alert.updated_at = now
    if body.status == AlertStatus.IN_REVIEW:
        alert.assigned_to_admin_id = principal.user.id
        alert.resolved_at = None
        alert.resolution_note = None
    else:
        alert.resolved_at = now
        alert.resolution_note = body.resolution_note.strip()
    add_audit(
        db,
        request,
        f"risk_alert.{body.status.value}",
        admin_user_id=principal.user.id,
        resource_type="risk_alert",
        resource_id=str(alert.id),
        details={"from": previous_status.value, "to": body.status.value},
    )
    db.commit()
    return alert


@router.get("/exports/{resource}.csv")
def export_filtered_csv(
    resource: str,
    request: Request,
    principal: Annotated[AdminPrincipal, Depends(current_admin)],
    db: DatabaseSession,
    q: Annotated[str | None, Query(max_length=100)] = None,
    status: str | None = None,
    kyc_status: str | None = None,
    vip_tier: str | None = None,
    country_code: Annotated[
        str | None, Query(min_length=2, max_length=2, pattern="^[A-Za-z]{2}$")
    ] = None,
    registered_after: datetime | None = None,
    registered_before: datetime | None = None,
    category_code: Annotated[str | None, Query(max_length=30)] = None,
    provider: Annotated[str | None, Query(max_length=60)] = None,
    is_active: bool | None = None,
    player_id: int | None = None,
    type: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    game_id: int | None = None,
    is_win: bool | None = None,
    placed_after: datetime | None = None,
    placed_before: datetime | None = None,
    alert_type: str | None = None,
    severity: str | None = None,
):
    filters = {
        "q": q,
        "status": status,
        "kyc_status": kyc_status,
        "vip_tier": vip_tier,
        "country_code": country_code,
        "registered_after": registered_after,
        "registered_before": registered_before,
        "category_code": category_code,
        "provider": provider,
        "is_active": is_active,
        "player_id": player_id,
        "type": type,
        "created_after": created_after,
        "created_before": created_before,
        "game_id": game_id,
        "is_win": is_win,
        "placed_after": placed_after,
        "placed_before": placed_before,
        "alert_type": alert_type,
        "severity": severity,
    }
    filters = {key: value for key, value in filters.items() if value is not None}
    page_size = CSV_EXPORT_LIMIT + 1
    try:
        if resource == "players":
            status_filter = PlayerStatus(status) if status else None
            kyc_filter = KycStatus(kyc_status) if kyc_status else None
            vip_filter = VipTier(vip_tier) if vip_tier else None
        elif resource == "transactions":
            status_filter = TransactionStatus(status) if status else None
            type_filter = TransactionType(type) if type else None
        elif resource == "risk-alerts":
            status_filter = AlertStatus(status) if status else None
            type_filter = AlertType(alert_type) if alert_type else None
            severity_filter = AlertSeverity(severity) if severity else None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid filter value") from exc

    if resource == "players":
        result = list_players(
            db,
            page=1,
            page_size=page_size,
            q=q,
            status=status_filter,
            kyc_status=kyc_filter,
            vip_tier=vip_filter,
            country_code=country_code,
            registered_after=registered_after,
            registered_before=registered_before,
        )
    elif resource == "games":
        result = list_games(
            db,
            page=1,
            page_size=page_size,
            category_code=category_code,
            provider=provider,
            is_active=is_active,
            q=q,
        )
    elif resource == "transactions":
        result = list_transactions(
            db,
            page=1,
            page_size=page_size,
            player_id=player_id,
            type=type_filter,
            status=status_filter,
            created_after=created_after,
            created_before=created_before,
        )
    elif resource == "bets":
        result = list_bets(
            db,
            page=1,
            page_size=page_size,
            player_id=player_id,
            game_id=game_id,
            is_win=is_win,
            placed_after=placed_after,
            placed_before=placed_before,
        )
    elif resource == "risk-alerts":
        result = list_risk_alerts(
            db,
            page=1,
            page_size=page_size,
            player_id=player_id,
            alert_type=type_filter,
            severity=severity_filter,
            status=status_filter,
            created_after=created_after,
            created_before=created_before,
        )
    else:
        raise HTTPException(status_code=404, detail="Unknown export resource")

    if result.total > CSV_EXPORT_LIMIT or len(result.items) > CSV_EXPORT_LIMIT:
        raise HTTPException(
            status_code=413,
            detail=f"Export exceeds the {CSV_EXPORT_LIMIT:,}-row limit; add filters and retry",
        )

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    records = [item.model_dump(mode="json") for item in result.items]
    headers = list(records[0]) if records else _export_headers(resource)
    writer.writerow(headers)
    for record in records:
        writer.writerow([_csv_value(record.get(header)) for header in headers])

    add_audit(
        db,
        request,
        "data.export_csv",
        admin_user_id=principal.user.id,
        resource_type=resource,
        details={"row_count": result.total, "filter_names": sorted(filters)},
    )
    db.commit()
    filename = f"{resource}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Exported-Count": str(result.total),
        },
    )


def _export_headers(resource: str) -> list[str]:
    return {
        "players": list(PlayerRead.model_fields),
        "games": list(GameRead.model_fields),
        "transactions": list(TransactionRead.model_fields),
        "bets": list(BetRead.model_fields),
        "risk-alerts": list(RiskAlertRead.model_fields),
    }[resource]


def _csv_value(value):
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, str) and value.lstrip(" \t\r\n").startswith(
        ("=", "+", "-", "@")
    ):
        return f"'{value}"
    return value
