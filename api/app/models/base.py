from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import DateTime, Enum, MetaData, Numeric, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint/index names: migrations stay stable and tests can match on them.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# Single currency for the whole casino (configured, not stored per row).
Money = Numeric(12, 2)
TZDateTime = DateTime(timezone=True)


def enum_type(enum_cls: type[PyEnum], name: str) -> Enum:
    """Python enum stored as VARCHAR + CHECK constraint.

    Native PostgreSQL enums are painful to migrate (ALTER TYPE), a CHECK is not.
    """
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda e: [m.value for m in e],
    )


def now_column(*, on_update: bool = False) -> Mapped[datetime]:
    """timestamptz NOT NULL DEFAULT now() (optionally refreshed on every ORM update)."""
    if on_update:
        return mapped_column(TZDateTime, server_default=func.now(), onupdate=func.now())
    return mapped_column(TZDateTime, server_default=func.now())
