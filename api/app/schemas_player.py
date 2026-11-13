from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PlayerRegistration(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[a-zA-Z0-9._-]+$")
    email: str = Field(
        min_length=5,
        max_length=255,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )
    password: str = Field(min_length=12, max_length=128)
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    birth_date: date
    country_code: str = Field(min_length=2, max_length=2, pattern=r"^[a-zA-Z]{2}$")


class PlayerLogin(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=1, max_length=128)


class PlayerTopUp(BaseModel):
    amount: Decimal = Field(
        ge=Decimal("1.00"), le=Decimal("50000.00"), max_digits=7, decimal_places=2
    )
    method: Literal["card", "e_wallet", "bank_transfer", "crypto"]


class ChipPackagePurchase(BaseModel):
    chips: Literal[100, 500, 1000, 5000]


class VipPurchase(BaseModel):
    tier: Literal["silver", "gold", "platinum", "diamond"]


class PlayerView(BaseModel):
    id: int
    username: str
    first_name: str
    balance: int


class DemoBet(BaseModel):
    stake: int = Field(ge=10, le=100, multiple_of=10)


class RouletteBet(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["number", "color", "parity", "dozen"]
    value: int | Literal["red", "black", "odd", "even"]
    amount: int = Field(ge=10, le=100, multiple_of=10)

    @model_validator(mode="after")
    def validate_value(self):
        if self.kind == "number" and isinstance(self.value, int) and 0 <= self.value <= 36:
            return self
        if self.kind == "color" and self.value in {"red", "black"}:
            return self
        if self.kind == "parity" and self.value in {"odd", "even"}:
            return self
        if self.kind == "dozen" and isinstance(self.value, int) and 1 <= self.value <= 3:
            return self
        raise ValueError("Value does not match roulette bet kind")


class RouletteSpin(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    bets: list[RouletteBet] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_total(self):
        total = sum(bet.amount for bet in self.bets)
        if not 10 <= total <= 100:
            raise ValueError("Total roulette stake must be between 10 and 100 credits")
        return self


class BlackjackAction(BaseModel):
    action: Literal["hit", "stand", "split"]


class BlackjackRoundId(BaseModel):
    round_id: UUID
