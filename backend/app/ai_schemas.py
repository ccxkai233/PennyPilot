"""Public request/response contracts for the optional AI features.

These models are intentionally separate from the bookkeeping schemas.  The
AI parser returns a proposal only; a client must still submit a normal
``POST /api/transactions`` request after the user confirms it.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AIConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, min_length=1, max_length=4096)
    model: str | None = Field(default=None, min_length=1, max_length=200)
    fallback_base_url: str | None = Field(default=None, max_length=500)
    fallback_api_key: str | None = Field(default=None, min_length=1, max_length=4096)
    fallback_model: str | None = Field(default=None, min_length=1, max_length=200)
    clear_api_key: bool = False

    @field_validator("base_url", "model", "fallback_base_url", "fallback_model", "fallback_api_key", mode="before")
    @classmethod
    def trim_strings(cls, value):
        if isinstance(value, str):
            return value.strip()
        return value


class AIConfigRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configured: bool
    base_url: str
    model: str
    api_key_set: bool
    api_key_hint: str | None = None
    fallback_configured: bool
    fallback_base_url: str | None = None
    fallback_model: str | None = None
    fallback_api_key_set: bool = False
    fallback_api_key_hint: str | None = None


class AICandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=100)
    direction: Literal["income", "expense"] | None = None
    kind: str | None = Field(default=None, max_length=32)


class AIConversationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class AIParseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4000)
    # ``cash`` is the safe/default mode and only proposes a cash transaction.
    # ``partner`` records a supplier/customer current-account movement without
    # touching cash. ``combined`` explicitly proposes both atomically.
    mode: Literal["cash", "partner", "combined"] = "cash"
    conversation: list[AIConversationMessage] = Field(default_factory=list, max_length=12)
    reference_time: datetime | None = None

    @field_validator("text", mode="before")
    @classmethod
    def trim_text(cls, value):
        if isinstance(value, str):
            value = value.strip()
        return value


class AIParsedTransaction(BaseModel):
    """Strict normalized proposal returned by the parser.

    IDs are preferred when a candidate list is available.  Names are retained
    for the confirmation UI and for unresolved entities; neither this model
    nor the parse endpoint writes a transaction.
    """

    model_config = ConfigDict(extra="forbid")

    occurred_at: datetime | None = None
    kind: Literal["cashflow", "transfer"] = "cashflow"
    direction: Literal["income", "expense"] | None = None
    amount_cents: int | None = Field(default=None, gt=0)
    category_id: int | None = Field(default=None, gt=0)
    category_name: str | None = Field(default=None, max_length=100)
    payment_method_id: int | None = Field(default=None, gt=0)
    payment_method_name: str | None = Field(default=None, max_length=100)
    transfer_payment_method_id: int | None = Field(default=None, gt=0)
    transfer_payment_method_name: str | None = Field(default=None, max_length=100)
    partner_id: int | None = Field(default=None, gt=0)
    partner_name: str | None = Field(default=None, max_length=100)
    partner_ledger_type: Literal[
        "prepaid_in",
        "prepaid_out",
        "credit_use",
        "credit_repay",
        "limit_adjust",
        "refund",
        "balance_check",
    ] | None = None
    partner_ledger_amount_cents: int | None = Field(default=None)
    # A supplied post-movement balance is a reconciliation observation, not a
    # second movement. It is persisted only when the user confirms the draft.
    partner_balance_after_cents: int | None = Field(default=None, ge=0)
    partner_balance_kind: Literal["prepaid_balance", "credit_limit", "credit_used", "credit_remaining", "available_credit"] | None = None
    notes: str | None = Field(default=None, max_length=5000)
    # Explicit/inferred/missing information is useful to the UI, but the
    # values are constrained so arbitrary model text cannot become metadata.
    field_status: dict[str, Literal["explicit", "inferred", "missing"]] = Field(
        default_factory=dict
    )

    @field_validator("partner_ledger_amount_cents")
    @classmethod
    def validate_ledger_amount(cls, value):
        if value is not None and isinstance(value, bool):
            raise ValueError("partner_ledger_amount_cents must be an integer")
        return value

    @model_validator(mode="after")
    def validate_ledger_amount_for_type(self):
        if self.kind == "transfer":
            self.direction = "expense"
            self.category_id = None
            self.category_name = None
            self.partner_ledger_type = None
            self.partner_ledger_amount_cents = None
        if self.partner_ledger_amount_cents == 0 and self.partner_ledger_type != "balance_check":
            raise ValueError("partner_ledger_amount_cents must be non-zero unless this is a balance check")
        if self.partner_ledger_amount_cents is not None and self.partner_ledger_type not in {"limit_adjust", "balance_check"} and self.partner_ledger_amount_cents < 0:
            raise ValueError("partner_ledger_amount_cents must be positive for this ledger type")
        return self


class AIParseResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["complete", "need_more_info", "fallback", "error"]
    mode: Literal["cash", "partner", "combined"] = "cash"
    parsed: AIParsedTransaction
    missing_fields: list[str] = Field(default_factory=list, max_length=16)
    follow_up_question: str | None = Field(default=None, max_length=1000)
    brief_comment: str | None = Field(default=None, max_length=300)
    source: Literal["model", "fallback"]
    warning: str | None = Field(default=None, max_length=300)

    @field_validator("brief_comment", mode="before")
    @classmethod
    def trim_brief_comment(cls, value):
        if isinstance(value, str):
            value = " ".join(value.split()).strip()
        return value or None


class AIConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Literal true makes omission/false fail validation instead of silently
    # turning an AI proposal into a ledger write.
    confirm: Literal[True]
    draft: AIParsedTransaction | dict[str, Any]
    mode: Literal["cash", "partner", "combined"] | None = None
    partner_ledger_type: Literal[
        "prepaid_in",
        "prepaid_out",
        "credit_use",
        "credit_repay",
        "limit_adjust",
        "refund",
        "balance_check",
    ] | None = None
    partner_ledger_amount_cents: int | None = Field(default=None)
    observed_balance_cents: int | None = Field(default=None, ge=0)
    observed_balance_kind: Literal["prepaid_balance", "credit_limit", "credit_used", "credit_remaining", "available_credit"] | None = None
    apply_balance_reconciliation: bool = False

    @model_validator(mode="before")
    @classmethod
    def accept_proposal_aliases(cls, value):
        if isinstance(value, dict):
            value = dict(value)
            if "draft" not in value:
                for key in ("parsed", "proposal", "transaction"):
                    if key in value:
                        value["draft"] = value[key]
                        break
        return value

    @model_validator(mode="after")
    def normalize_draft(self):
        if isinstance(self.draft, dict):
            self.draft = AIParsedTransaction.model_validate(self.draft)
        if self.partner_ledger_type is None:
            self.partner_ledger_type = self.draft.partner_ledger_type
        if self.partner_ledger_amount_cents is None:
            self.partner_ledger_amount_cents = self.draft.partner_ledger_amount_cents
        if self.observed_balance_cents is None:
            self.observed_balance_cents = self.draft.partner_balance_after_cents
        if self.observed_balance_kind is None:
            self.observed_balance_kind = self.draft.partner_balance_kind
        # Existing clients used partner_ledger_type to request a combined
        # transaction. Preserve that behavior when mode was omitted. New
        # clients must opt into partner-only explicitly.
        if self.mode is None:
            self.mode = "combined" if self.partner_ledger_type is not None else "cash"
        if self.partner_ledger_amount_cents is not None and (
            isinstance(self.partner_ledger_amount_cents, bool)
            or (self.partner_ledger_amount_cents == 0 and self.partner_ledger_type != "balance_check")
            or (self.partner_ledger_type not in {"limit_adjust", "balance_check"} and self.partner_ledger_amount_cents < 0)
        ):
            raise ValueError("invalid partner ledger amount")
        return self


class AIConfirmResponse(BaseModel):
    transaction: dict | None = None
    mode: Literal["cash", "partner", "combined"] = "cash"
    partner_ledger: dict | None = None
    balance_reconciliation: dict | None = None
    warning: str | None = None


class AIAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period: Literal["day", "week", "month", "custom"] = "month"
    start_date: date | None = None
    end_date: date | None = None
    save_history: bool = True


class AIReportSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    period: str
    start_date: date
    end_date: date
    source: Literal["model", "fallback"]
    model: str | None = None
    created_at: datetime


class AIAnalyzeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: int | None = None
    period: str
    start_date: date
    end_date: date
    source: Literal["model", "fallback"]
    model: str | None = None
    content: str = Field(max_length=100_000)
    data_summary: dict
    warning: str | None = Field(default=None, max_length=300)
    generated_at: datetime


class AIReportRead(AIAnalyzeResponse):
    pass
