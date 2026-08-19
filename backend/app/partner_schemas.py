"""Pydantic contracts for supplier/customer accounts and their ledger."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


PartnerType = Literal["supplier", "customer"]
PartnerStatus = Literal["active", "inactive"]
PartnerLedgerType = Literal[
    "prepaid_in",
    "prepaid_out",
    "credit_use",
    "credit_repay",
    "limit_adjust",
    "refund",
    "balance_check",
]


class _ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class PartnerCreate(BaseModel):
    # ``type`` is the documented field.  ``partner_type`` is accepted as an
    # ergonomic alias for clients that avoid the generic Python word.
    type: PartnerType
    name: str = Field(min_length=1, max_length=200)
    contact: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=64)
    website: str | None = Field(default=None, max_length=2048)
    # URL is accepted as a wire-level alias by integrations that use the
    # shorter field name. It is never persisted as a separate ORM attribute.
    url: str | None = Field(default=None, max_length=2048, exclude=True)
    # Kept for old clients and historical records. New clients should send
    # website; an email value is never silently reclassified as a URL.
    email: str | None = Field(default=None, max_length=254)
    unsettled_balance_cents: int = Field(default=0, ge=0)
    prepaid_balance_cents: int = Field(default=0, ge=0)
    credit_limit_cents: int = Field(default=0, ge=0)
    credit_used_cents: int = Field(default=0, ge=0)
    status: PartnerStatus = "active"
    notes: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="before")
    @classmethod
    def accept_aliases(cls, value):
        if isinstance(value, dict):
            value = dict(value)
            if "type" not in value:
                for key in ("partner_type", "kind"):
                    if key in value:
                        value["type"] = value[key]
                        break
            if "unsettled_balance_cents" not in value and "balance_cents" in value:
                value["unsettled_balance_cents"] = value["balance_cents"]
            # The plan uses both "contact" and "contact_info" in different
            # clients; retaining this alias costs no storage ambiguity.
            if "contact" not in value and "contact_info" in value:
                value["contact"] = value["contact_info"]
            if not value.get("website") and value.get("url"):
                value["website"] = value["url"]
        return value

    @model_validator(mode="after")
    def normalize_values(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("name must not be blank")
        for field in ("contact", "phone", "website", "email", "notes"):
            value = getattr(self, field)
            if value is not None:
                setattr(self, field, value.strip() or None)
        if self.type == "customer" and self.credit_used_cents > self.credit_limit_cents:
            raise ValueError("credit_used_cents cannot exceed credit_limit_cents")
        return self


class PartnerUpdate(BaseModel):
    type: PartnerType | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    contact: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=64)
    website: str | None = Field(default=None, max_length=2048)
    url: str | None = Field(default=None, max_length=2048, exclude=True)
    email: str | None = Field(default=None, max_length=254)
    status: PartnerStatus | None = None
    notes: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="before")
    @classmethod
    def accept_aliases(cls, value):
        if isinstance(value, dict):
            value = dict(value)
            if "type" not in value:
                for key in ("partner_type", "kind"):
                    if key in value:
                        value["type"] = value[key]
                        break
            if "contact" not in value and "contact_info" in value:
                value["contact"] = value["contact_info"]
            if not value.get("website") and value.get("url"):
                value["website"] = value["url"]
            # Some clients use the boolean spelling for archive/restore.  It
            # is normalized here so route code only ever persists the
            # canonical active/inactive status column.
            if "status" not in value and "is_active" in value:
                value["status"] = "active" if value.pop("is_active") else "inactive"
            else:
                value.pop("is_active", None)
        return value

    @model_validator(mode="after")
    def normalize_values(self):
        if self.name is not None:
            self.name = self.name.strip()
            if not self.name:
                raise ValueError("name must not be blank")
        for field in ("contact", "phone", "website", "email", "notes"):
            value = getattr(self, field)
            if value is not None:
                setattr(self, field, value.strip() or None)
        return self


class PartnerRead(_ORMModel):
    id: int
    user_id: int
    type: PartnerType
    name: str
    contact: str | None = None
    phone: str | None = None
    website: str | None = None
    url: str | None = None
    email: str | None = None
    unsettled_balance_cents: int
    prepaid_balance_cents: int
    credit_limit_cents: int
    credit_used_cents: int
    credit_remaining_cents: int | None = None
    status: PartnerStatus
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class PartnerListResponse(BaseModel):
    items: list[PartnerRead]
    total: int
    page: int
    page_size: int


class PartnerLedgerCreate(BaseModel):
    entry_type: PartnerLedgerType
    amount_cents: int
    occurred_at: datetime | None = None
    transaction_id: int | None = Field(default=None, gt=0)
    notes: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="before")
    @classmethod
    def accept_aliases(cls, value):
        if isinstance(value, dict):
            value = dict(value)
            if "entry_type" not in value:
                for key in ("type", "change_type", "ledger_type"):
                    if key in value:
                        value["entry_type"] = value[key]
                        break
        return value

    @model_validator(mode="after")
    def validate_values(self):
        if isinstance(self.amount_cents, bool) or (self.amount_cents == 0 and self.entry_type != "balance_check"):
            raise ValueError("amount_cents must be a non-zero integer unless this is a balance check")
        if self.entry_type != "limit_adjust" and self.amount_cents < 0:
            raise ValueError("amount_cents must be positive for this ledger type")
        if self.notes is not None:
            self.notes = self.notes.strip() or None
        return self


class PartnerLedgerReverseRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def normalize_reason(self):
        if self.reason is not None:
            self.reason = self.reason.strip() or None
        return self


class PartnerLedgerRead(_ORMModel):
    id: int
    user_id: int
    partner_id: int
    occurred_at: datetime
    entry_type: PartnerLedgerType
    amount_cents: int
    balance_before_cents: int
    balance_after_cents: int
    prepaid_before_cents: int
    prepaid_after_cents: int
    credit_limit_before_cents: int
    credit_limit_after_cents: int
    credit_used_before_cents: int
    credit_used_after_cents: int
    transaction_id: int | None = None
    reversal_of_id: int | None = None
    reversed_entry_id: int | None = None
    status: str
    notes: str | None = None
    created_at: datetime


class PartnerLedgerListResponse(BaseModel):
    items: list[PartnerLedgerRead]
    total: int
    page: int
    page_size: int
