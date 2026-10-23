from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


class AdminRead(BaseModel):
    id: int
    email: str
    full_name: str
    role: str


class ORMRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)


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


class AuditRead(ORMRead):
    id: int
    admin_user_id: int | None
    action: str
    resource_type: str | None
    resource_id: str | None
    details: dict | None
    ip_address: str | None
    created_at: datetime


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)
    totp_code: str | None = Field(default=None, min_length=6, max_length=8)
    recovery_code: str | None = Field(default=None, min_length=16, max_length=64)


class TotpEnableRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)
    totp_code: str = Field(min_length=6, max_length=8)
