from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=100)
    password: str = Field(min_length=8, max_length=72)

    @model_validator(mode="after")
    def normalize_credentials(self):
        self.username = self.username.strip()
        if len(self.username) < 2:
            raise ValueError("username must contain at least two non-space characters")
        if not self.password.strip():
            raise ValueError("password must not be blank")
        if len(self.password.encode("utf-8")) > 72:
            raise ValueError("password must not exceed 72 UTF-8 bytes")
        return self


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    is_active: bool
    created_at: datetime


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=72)

    @model_validator(mode="after")
    def normalize_username(self):
        self.username = self.username.strip()
        if not self.password.strip():
            raise ValueError("password must not be blank")
        if len(self.password.encode("utf-8")) > 72:
            raise ValueError("password must not exceed 72 UTF-8 bytes")
        return self


# ---------------------------------------------------------------------------
# Core bookkeeping schemas
# ---------------------------------------------------------------------------

Direction = Literal["income", "expense"]
PaymentMethodRole = Literal["cash", "liability", "investment"]
TransactionKind = Literal["cashflow", "transfer"]


class _ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    direction: Direction
    icon: str | None = Field(default=None, max_length=100)
    sort_order: int = Field(default=0, ge=0)
    is_active: bool = True

    @model_validator(mode="after")
    def trim_name(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("name must not be blank")
        return self


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    direction: Direction | None = None
    icon: str | None = Field(default=None, max_length=100)
    sort_order: int | None = Field(default=None, ge=0)
    is_active: bool | None = None

    @model_validator(mode="after")
    def trim_name(self):
        if self.name is not None:
            self.name = self.name.strip()
            if not self.name:
                raise ValueError("name must not be blank")
        return self


class CategoryRead(_ORMModel):
    id: int
    user_id: int | None = None
    name: str
    direction: Direction
    icon: str | None = None
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class PaymentMethodCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    icon: str | None = Field(default=None, max_length=100)
    account_role: PaymentMethodRole = "cash"
    track_balance: bool = True
    current_balance_cents: int | None = None
    sort_order: int = Field(default=0, ge=0)
    is_active: bool = True

    @model_validator(mode="after")
    def validate_values(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("name must not be blank")
        if self.current_balance_cents is not None and isinstance(self.current_balance_cents, bool):
            raise ValueError("current_balance_cents must be an integer")
        # Every funds account maintains a running balance. Keeping this
        # invariant in the API prevents older clients from recreating the
        # removed UI toggle by submitting track_balance=false.
        self.track_balance = True
        return self


class PaymentMethodUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    icon: str | None = Field(default=None, max_length=100)
    account_role: PaymentMethodRole | None = None
    track_balance: bool | None = None
    current_balance_cents: int | None = None
    sort_order: int | None = Field(default=None, ge=0)
    is_active: bool | None = None

    @model_validator(mode="after")
    def trim_name(self):
        if self.name is not None:
            self.name = self.name.strip()
            if not self.name:
                raise ValueError("name must not be blank")
        self.track_balance = True
        return self


class PaymentMethodRead(_ORMModel):
    id: int
    user_id: int | None = None
    name: str
    icon: str | None = None
    account_role: PaymentMethodRole
    track_balance: bool
    current_balance_cents: int | None = None
    # Account lists expose an immediately usable balance for dashboards. For
    # tracked accounts this mirrors current_balance_cents; legacy cash methods
    # that only recorded transactions receive a ledger-derived balance.
    effective_balance_cents: int | None = None
    balance_source: Literal["tracked", "transactions"] | None = None
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TransactionCreate(BaseModel):
    occurred_at: datetime | None = None
    kind: TransactionKind = "cashflow"
    direction: Direction
    amount_cents: int = Field(gt=0)
    category_id: int | None = Field(default=None, gt=0)
    payment_method_id: int = Field(gt=0)
    transfer_payment_method_id: int | None = Field(default=None, gt=0)
    partner_id: int | None = Field(default=None, gt=0)
    notes: str | None = Field(default=None, max_length=5000)
    source: str = Field(default="manual", min_length=1, max_length=16)

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_names(cls, value):
        if isinstance(value, dict):
            value = dict(value)
            if "amount_cents" not in value and "amount" in value:
                value["amount_cents"] = value["amount"]
            if "kind" not in value:
                for key in ("transaction_kind", "type"):
                    if key in value and value[key] in {"cashflow", "transfer"}:
                        value["kind"] = value[key]
                        break
            if "transfer_payment_method_id" not in value:
                for key in ("target_payment_method_id", "counterparty_payment_method_id", "to_payment_method_id"):
                    if key in value:
                        value["transfer_payment_method_id"] = value[key]
                        break
            if "occurred_at" not in value:
                for key in ("occurred_time", "transaction_time", "happened_at"):
                    if key in value:
                        value["occurred_at"] = value[key]
                        break
        return value

    @model_validator(mode="after")
    def validate_values(self):
        if isinstance(self.amount_cents, bool):
            raise ValueError("amount_cents must be an integer")
        if self.category_id is not None and isinstance(self.category_id, bool):
            raise ValueError("category_id must be an integer")
        if self.kind == "transfer":
            self.direction = "expense"
        else:
            self.transfer_payment_method_id = None
        self.source = self.source.strip().lower()
        if self.source in {"natural_language", "nl", "assistant"}:
            self.source = "ai"
        if self.notes is not None:
            self.notes = self.notes.strip() or None
        return self


class TransactionUpdate(BaseModel):
    occurred_at: datetime | None = None
    kind: TransactionKind | None = None
    direction: Direction | None = None
    amount_cents: int | None = Field(default=None, gt=0)
    category_id: int | None = Field(default=None, gt=0)
    payment_method_id: int | None = Field(default=None, gt=0)
    transfer_payment_method_id: int | None = Field(default=None, gt=0)
    partner_id: int | None = Field(default=None, gt=0)
    notes: str | None = Field(default=None, max_length=5000)
    source: str | None = Field(default=None, min_length=1, max_length=16)

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_names(cls, value):
        if isinstance(value, dict):
            value = dict(value)
            if "amount_cents" not in value and "amount" in value:
                value["amount_cents"] = value["amount"]
            if "kind" not in value:
                for key in ("transaction_kind", "type"):
                    if key in value and value[key] in {"cashflow", "transfer"}:
                        value["kind"] = value[key]
                        break
            if "transfer_payment_method_id" not in value:
                for key in ("target_payment_method_id", "counterparty_payment_method_id", "to_payment_method_id"):
                    if key in value:
                        value["transfer_payment_method_id"] = value[key]
                        break
            if "occurred_at" not in value:
                for key in ("occurred_time", "transaction_time", "happened_at"):
                    if key in value:
                        value["occurred_at"] = value[key]
                        break
        return value

    @model_validator(mode="after")
    def normalize_values(self):
        if self.source is not None:
            self.source = self.source.strip().lower()
            if self.source in {"natural_language", "nl", "assistant"}:
                self.source = "ai"
        if self.notes is not None:
            self.notes = self.notes.strip() or None
        if self.kind == "transfer":
            self.direction = "expense"
        elif self.kind == "cashflow":
            self.transfer_payment_method_id = None
        return self


class TransactionVoidRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class TransactionRead(_ORMModel):
    id: int
    user_id: int | None = None
    occurred_at: datetime
    kind: TransactionKind
    direction: Direction
    amount_cents: int
    category_id: int | None = None
    payment_method_id: int
    transfer_payment_method_id: int | None = None
    partner_id: int | None = None
    notes: str | None = None
    source: str
    status: str
    voided_at: datetime | None = None
    void_reason: str | None = None
    created_at: datetime
    updated_at: datetime
    category_name: str | None = None
    payment_method_name: str | None = None
    transfer_payment_method_name: str | None = None
    partner_name: str | None = None


class CategoryListResponse(BaseModel):
    items: list[CategoryRead]
    total: int
    page: int
    page_size: int


class PaymentMethodListResponse(BaseModel):
    items: list[PaymentMethodRead]
    total: int
    page: int
    page_size: int


class TransactionListResponse(BaseModel):
    items: list[TransactionRead]
    total: int
    page: int
    page_size: int
