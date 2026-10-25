import calendar
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Date, Integer, case, cast, extract, func, select

from app.models.enums import (
    AlertSeverity,
    AlertStatus,
    AlertType,
    Channel,
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
    DashboardDailyMetrics,
    DashboardDistributionItem,
    DashboardHeatmapCell,
    DashboardMetrics,
    DashboardMonthlyGGR,
    GameRead,
    Page,
    PlayerRead,
    RiskAlertRead,
    TransactionRead,
)
from app.security import DatabaseSession, current_admin, require_super_admin

router = APIRouter(prefix="/api", tags=["casino data"], dependencies=[Depends(current_admin)])
PAGE_SIZE_MAX = 100
DASHBOARD_RANGE_DAYS_MAX = 366
VIP_TIER_LABELS = {
    VipTier.STANDARD: "Standard",
    VipTier.SILVER: "Silver",
    VipTier.GOLD: "Gold",
    VipTier.PLATINUM: "Platinum",
    VipTier.DIAMOND: "Diamond",
}
AGE_BANDS = ("18-25", "26-35", "36-45", "46-55", "56+")


def page_bounds(page: int, page_size: int) -> tuple[int, int]:
    return (page - 1) * page_size, page_size


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def subtract_months(value: datetime, months: int) -> datetime:
    month_index = value.year * 12 + value.month - 1 - months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def distribution_items(
    counts: dict[str, int], labels: dict[str, str], total: int
) -> list[DashboardDistributionItem]:
    return [
        DashboardDistributionItem(
            key=key,
            label=labels[key],
            count=counts.get(key, 0),
            percentage=round(counts.get(key, 0) * 100 / total, 1) if total else 0,
        )
        for key in labels
    ]


@router.get("/dashboard/metrics", response_model=DashboardMetrics)
def dashboard_metrics(
    db: DatabaseSession,
    start_date: date,
    end_date: date,
    registration_months: Annotated[str, Query(pattern="^(all|1|3|6)$")] = "all",
):
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="end_date must be on or after start_date")
    day_count = (end_date - start_date).days + 1
    if day_count > DASHBOARD_RANGE_DAYS_MAX:
        raise HTTPException(
            status_code=422,
            detail=f"Date range cannot exceed {DASHBOARD_RANGE_DAYS_MAX} days",
        )

    start_at = datetime.combine(start_date, time.min, tzinfo=UTC)
    end_at = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC)
    utc_bet_date = cast(func.timezone("UTC", Bet.placed_at), Date)
    utc_transaction_date = cast(func.timezone("UTC", Transaction.completed_at), Date)

    totals = db.execute(
        select(
            func.count(Bet.id),
            func.coalesce(func.sum(Bet.stake - Bet.payout), 0),
            func.count(func.distinct(GameSession.player_id)),
        )
        .select_from(Bet)
        .join(GameSession, Bet.session_id == GameSession.id)
        .where(Bet.placed_at >= start_at, Bet.placed_at < end_at)
    ).one()
    transaction_totals = db.execute(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (Transaction.type == TransactionType.DEPOSIT, Transaction.amount),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (Transaction.type == TransactionType.WITHDRAWAL, Transaction.amount),
                        else_=0,
                    )
                ),
                0,
            ),
        ).where(
            Transaction.status == TransactionStatus.COMPLETED,
            Transaction.completed_at >= start_at,
            Transaction.completed_at < end_at,
        )
    ).one()
    daily_bets = db.execute(
        select(utc_bet_date, func.coalesce(func.sum(Bet.stake - Bet.payout), 0))
        .select_from(Bet)
        .join(GameSession, Bet.session_id == GameSession.id)
        .where(Bet.placed_at >= start_at, Bet.placed_at < end_at)
        .group_by(utc_bet_date)
    ).all()
    daily_transactions = db.execute(
        select(
            utc_transaction_date,
            func.coalesce(
                func.sum(
                    case(
                        (Transaction.type == TransactionType.DEPOSIT, Transaction.amount),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (Transaction.type == TransactionType.WITHDRAWAL, Transaction.amount),
                        else_=0,
                    )
                ),
                0,
            ),
        )
        .where(
            Transaction.status == TransactionStatus.COMPLETED,
            Transaction.completed_at >= start_at,
            Transaction.completed_at < end_at,
        )
        .group_by(utc_transaction_date)
    ).all()

    daily = {
        start_date + timedelta(days=offset): {
            "ggr": 0,
            "deposits": 0,
            "withdrawals": 0,
        }
        for offset in range(day_count)
    }
    for day, ggr in daily_bets:
        daily[day]["ggr"] = ggr
    for day, deposits, withdrawals in daily_transactions:
        daily[day]["deposits"] = deposits
        daily[day]["withdrawals"] = withdrawals

    now = datetime.now(UTC)
    players_query = select(Player.registration_channel, func.count(Player.id)).group_by(
        Player.registration_channel
    )
    if registration_months != "all":
        players_query = players_query.where(
            Player.registered_at >= subtract_months(now, int(registration_months))
        )
    channel_counts = {
        channel.value: count for channel, count in db.execute(players_query).all()
    }
    channel_total = sum(channel_counts.values())
    channels = distribution_items(
        channel_counts,
        {Channel.WEB.value: "Web", Channel.MOBILE.value: "Mobile"},
        channel_total,
    )

    vip_counts = {
        tier.value: count
        for tier, count in db.execute(
            select(Player.vip_tier, func.count(Player.id)).group_by(Player.vip_tier)
        ).all()
    }
    all_players = sum(vip_counts.values())
    vip_tiers = distribution_items(
        vip_counts,
        {tier.value: label for tier, label in VIP_TIER_LABELS.items()},
        all_players,
    )

    today_utc = datetime.now(UTC).date()
    age = cast(extract("year", func.age(today_utc, Player.birth_date)), Integer)
    age_bucket = case(
        (age < 26, "18-25"),
        (age < 36, "26-35"),
        (age < 46, "36-45"),
        (age < 56, "46-55"),
        else_="56+",
    )
    age_counts = {
        bucket: count
        for bucket, count in db.execute(
            select(age_bucket, func.count(Player.id)).group_by(age_bucket)
        ).all()
    }
    age_bands = distribution_items(
        age_counts, {band: band for band in AGE_BANDS}, all_players
    )

    all_time_ggr = db.scalar(select(func.coalesce(func.sum(Bet.stake - Bet.payout), 0)))
    current_month = date(now.year, now.month, 1)
    first_month = subtract_months(datetime.combine(current_month, time.min), 5).date()
    monthly_start = datetime.combine(first_month, time.min, tzinfo=UTC)
    monthly_end = datetime.combine(
        current_month + timedelta(days=calendar.monthrange(now.year, now.month)[1]),
        time.min,
        tzinfo=UTC,
    )
    bet_month = cast(func.date_trunc("month", func.timezone("UTC", Bet.placed_at)), Date)
    monthly_rows = db.execute(
        select(bet_month, func.coalesce(func.sum(Bet.stake - Bet.payout), 0))
        .where(Bet.placed_at >= monthly_start, Bet.placed_at < monthly_end)
        .group_by(bet_month)
    ).all()
    monthly_counts = {month: ggr for month, ggr in monthly_rows}
    monthly_ggr = []
    for offset in range(6):
        month_start = subtract_months(
            datetime.combine(current_month, time.min), 5 - offset
        ).date()
        monthly_ggr.append(
            DashboardMonthlyGGR(
                month=month_start,
                label=month_start.strftime("%b %Y"),
                ggr=monthly_counts.get(month_start, 0),
            )
        )

    weekday = cast(extract("isodow", func.timezone("UTC", Bet.placed_at)), Integer) - 1
    hour = cast(extract("hour", func.timezone("UTC", Bet.placed_at)), Integer)
    heatmap_counts = {
        (day, hour_of_day): count
        for day, hour_of_day, count in db.execute(
            select(weekday, hour, func.count(Bet.id)).group_by(weekday, hour)
        ).all()
    }
    bet_heatmap = [
        DashboardHeatmapCell(
            weekday=day,
            hour=hour_of_day,
            bets_count=heatmap_counts.get((day, hour_of_day), 0),
        )
        for day in range(7)
        for hour_of_day in range(24)
    ]

    return DashboardMetrics(
        start_date=start_date,
        end_date=end_date,
        ggr=totals[1],
        deposits=transaction_totals[0],
        withdrawals=transaction_totals[1],
        active_players=totals[2],
        bets_count=totals[0],
        daily=[
            DashboardDailyMetrics(date=day, **values)
            for day, values in daily.items()
        ],
        registration_channel_period=registration_months,
        registration_channels=channels,
        vip_tiers=vip_tiers,
        age_bands=age_bands,
        all_time_ggr=all_time_ggr or 0,
        monthly_ggr=monthly_ggr,
        bet_heatmap=bet_heatmap,
    )


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
