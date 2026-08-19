"""Request/response contracts for daily settlement snapshots."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DailySnapshotRead(_ORMModel):
    id: int
    user_id: int
    settlement_date: date
    settled_at: datetime
    income_cents: int
    expense_cents: int
    net_cents: int
    total_assets_cents: int
    account_balances: list[dict[str, Any]] = Field(default_factory=list)
    account_changes: list[dict[str, Any]] = Field(default_factory=list)
    is_recalculated: bool = False
    # Today is returned as a read-only live preview until the Beijing day is
    # closed and the scheduled settlement creates its immutable snapshot.
    is_live: bool = False
    recalculated_at: datetime | None = None
    created_at: datetime


class DailySnapshotListResponse(BaseModel):
    items: list[DailySnapshotRead]
    total: int
    page: int
    page_size: int


class SettlementRunRequest(BaseModel):
    """Run one day; omitted date means the previous Beijing calendar day."""

    settlement_date: date | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_aliases(cls, value: Any) -> Any:
        if isinstance(value, dict):
            value = dict(value)
            if "settlement_date" not in value:
                for alias in ("date", "target_date"):
                    if alias in value:
                        value["settlement_date"] = value[alias]
                        break
        return value


class SettlementRecalculateRequest(BaseModel):
    """Refresh snapshots from ``from_date`` through ``to_date``.

    ``to_date`` is optional and defaults to the latest existing snapshot (or
    the previous Beijing day when no later row exists).  The API accepts ``date``
    as a backwards-compatible alias for ``from_date``.
    """

    from_date: date
    to_date: date | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_aliases(cls, value: Any) -> Any:
        if isinstance(value, dict):
            value = dict(value)
            if "from_date" not in value:
                for alias in ("date", "start_date"):
                    if alias in value:
                        value["from_date"] = value[alias]
                        break
            if "to_date" not in value and "end_date" in value:
                value["to_date"] = value["end_date"]
        return value

    @model_validator(mode="after")
    def validate_range(self) -> "SettlementRecalculateRequest":
        if self.to_date is not None and self.to_date < self.from_date:
            raise ValueError("to_date must be on or after from_date")
        return self


class SettlementRecalculateResponse(BaseModel):
    from_date: date
    to_date: date
    recalculated_count: int
    created_count: int = 0
    items: list[DailySnapshotRead]
