from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Identity, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TZDateTime, enum_type, now_column
from app.models.enums import AlertSeverity, AlertStatus, AlertType


class RiskAlert(Base):
    __tablename__ = "risk_alerts"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    player_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("players.id", ondelete="RESTRICT"), index=True
    )
    alert_type: Mapped[AlertType] = mapped_column(enum_type(AlertType, "alert_type"))
    severity: Mapped[AlertSeverity] = mapped_column(enum_type(AlertSeverity, "alert_severity"))
    status: Mapped[AlertStatus] = mapped_column(
        enum_type(AlertStatus, "alert_status"), server_default=text("'open'")
    )
    assigned_to_admin_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("admin_users.id", ondelete="RESTRICT")
    )
    details: Mapped[dict | None] = mapped_column(JSONB)  # evidence that triggered the alert
    created_at: Mapped[datetime] = now_column()
    updated_at: Mapped[datetime] = now_column(on_update=True)
    resolved_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    resolution_note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "(status IN ('resolved', 'dismissed')) = (resolved_at IS NOT NULL)",
            name="resolved_at_matches_status",
        ),
        Index("ix_risk_alerts_status_severity_created_at", "status", "severity", "created_at"),
    )
