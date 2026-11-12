from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


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


class PlayerView(BaseModel):
    id: int
    username: str
    first_name: str
    balance: int


class DemoBet(BaseModel):
    stake: int = Field(ge=10, le=100, multiple_of=10)


class BlackjackAction(BaseModel):
    action: Literal["hit", "stand", "split"]


class BlackjackRoundId(BaseModel):
    round_id: UUID
