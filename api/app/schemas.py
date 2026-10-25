from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import AlertStatus, PlayerStatus


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


class AdminRead(BaseModel):
    id: int
    username: str
    email: str
    full_name: str
    role: str


class ORMRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PendingAdminRead(ORMRead):
    id: int
    username: str
    email: str
    full_name: str
    created_at: datetime


class PlayerRead(ORMRead):
    id: int
    username: str
    email: str
    first_name: str
    last_name: str
    birth_date: date
    country_code: str
    status: str
    kyc_status: str
    vip_tier: str
    registration_channel: str
    registered_at: datetime
    last_login_at: datetime | None
    self_exclusion_until: datetime | None
    deposit_limit_monthly: Decimal | None
    loss_limit_monthly: Decimal | None
    wallet_balance: Decimal | None = None


class GameRead(ORMRead):
    id: int
    category_code: str
    category_name: str
    name: str
    provider: str
    theoretical_rtp: Decimal
    volatility: str
    min_bet: Decimal
    max_bet: Decimal
    is_active: bool
    released_at: date | None


class TransactionRead(ORMRead):
    id: int
    player_id: int
    type: str
    status: str
    amount: Decimal
    method: str | None
    created_at: datetime
    completed_at: datetime | None
    external_ref: str | None
    created_by_admin_id: int | None
    note: str | None


class BetRead(ORMRead):
    id: int
    player_id: int
    game_id: int
    session_id: int
    stake: Decimal
    payout: Decimal
    is_win: bool
    placed_at: datetime


class RiskAlertRead(ORMRead):
    id: int
    player_id: int
    alert_type: str
    severity: str
    status: str
    assigned_to_admin_id: int | None
    details: dict | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    resolution_note: str | None


class PlayerStatusUpdate(BaseModel):
    status: PlayerStatus


class GameStatusUpdate(BaseModel):
    is_active: bool


class RiskAlertUpdate(BaseModel):
    status: AlertStatus
    resolution_note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def require_resolution_note(self):
        if self.status in {AlertStatus.RESOLVED, AlertStatus.DISMISSED} and not (
            self.resolution_note and self.resolution_note.strip()
        ):
            raise ValueError(
                "A resolution note is required to resolve or dismiss an alert"
            )
        return self


class AuditRead(ORMRead):
    id: int
    admin_user_id: int | None
    action: str
    resource_type: str | None
    resource_id: str | None
    details: dict | None
    ip_address: str | None
    created_at: datetime


class DashboardDailyMetrics(BaseModel):
    date: date
    ggr: Decimal
    deposits: Decimal
    withdrawals: Decimal


class DashboardDistributionItem(BaseModel):
    key: str
    label: str
    count: int
    percentage: float


class DashboardMonthlyGGR(BaseModel):
    month: date
    label: str
    ggr: Decimal


class DashboardHeatmapCell(BaseModel):
    weekday: int
    hour: int
    bets_count: int


class DashboardMetrics(BaseModel):
    start_date: date
    end_date: date
    ggr: Decimal
    deposits: Decimal
    withdrawals: Decimal
    active_players: int
    bets_count: int
    daily: list[DashboardDailyMetrics]
    registration_channel_period: str
    registration_channels: list[DashboardDistributionItem]
    vip_tiers: list[DashboardDistributionItem]
    age_bands: list[DashboardDistributionItem]
    all_time_ggr: Decimal
    monthly_ggr: list[DashboardMonthlyGGR]
    bet_heatmap: list[DashboardHeatmapCell]


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[a-zA-Z0-9._-]+$")
    password: str = Field(min_length=1, max_length=128)


class RegistrationRequest(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[a-zA-Z0-9._-]+$")
    email: str = Field(
        min_length=5,
        max_length=255,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=12, max_length=128)
