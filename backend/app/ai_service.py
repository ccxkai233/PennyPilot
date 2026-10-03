"""Safe OpenAI-compatible client and deterministic AI fallbacks.

The service is deliberately independent of FastAPI routes.  It never writes a
transaction: parsing produces a proposal and the route requires an explicit
confirmation before calling the normal accounting code.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import hashlib
import ipaddress
import json
import logging
import re
import time
from typing import Any, Callable, Iterable
from urllib.parse import quote, urlsplit

import anthropic
import httpx
import uuid
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .ai_schemas import MAX_PARSE_RECORDS, AIAnalyzeRequest, AIParsedRecord, AIParsedTransaction, AIParseResponse
from .config import Settings, get_settings
from .models import AIConfig, AIReport, Category, Partner, PartnerLedgerEntry, PaymentMethod, Transaction, User
from .timezone import BUSINESS_TIMEZONE_NAME, BUSINESS_TZ, now_utc, to_business, to_utc


MAX_INPUT_CHARS = 4_000
MAX_CONVERSATION_MESSAGES = 12
MAX_CANDIDATES = 100
MAX_REPORT_CHARS = 100_000
# DeepSeek's JSON Output mode recommends an explicit completion limit.  The
# parser envelope is small, but reasoning-capable models may spend tokens on
# hidden reasoning before returning it, so leave enough headroom to avoid a
# truncated JSON object.
AI_PARSE_MAX_TOKENS = 4_096
# The parser streams its completion, so the read timeout only bounds the gap
# between two chunks (a reasoning model may stay silent while it thinks) and
# a long multi-record envelope is not cut off while it is still arriving.
AI_STREAM_IDLE_TIMEOUT_SECONDS = 30.0
AI_STREAM_TOTAL_TIMEOUT_SECONDS = 90.0
# Anthropic counts thinking against ``max_tokens``, so the small caps used for
# the other formats would truncate the answer.
ANTHROPIC_MAX_TOKENS = 16_000
# Ledger questions and reports run at full reasoning depth; reasoning tokens
# count against the cap on several families, so leave plenty of room.
ANALYSIS_MAX_TOKENS = 16_000
DEEPSEEK_READ_TIMEOUT_SECONDS = 30.0
DEEPSEEK_CONNECT_TIMEOUT_SECONDS = 10.0

# Neutral channel defaults for users who may not see the server's own channel.
PUBLIC_AI_BASE_URL: str = Settings.model_fields["ai_base_url"].default
PUBLIC_AI_MODEL: str = Settings.model_fields["ai_model"].default

logger = logging.getLogger(__name__)


# The parser is the only AI operation that needs a machine-readable contract.
# Keep every property required (nullable values represent an unknown field), as
# required-by-strict is part of the OpenAI-compatible structured-output
# contract.  The backend still recomputes field_status and completeness after
# matching candidates, so those model hints never become bookkeeping facts.
_AI_PARSE_RECORD_PROPERTIES: dict[str, Any] = {
    "occurred_at": {"type": ["string", "null"]},
    "kind": {"type": "string", "enum": ["cashflow", "transfer", "balance_check"]},
    "direction": {"type": ["string", "null"], "enum": ["income", "expense", None]},
    "amount_cents": {"type": ["integer", "null"], "minimum": 1},
    "account_balance_cents": {"type": ["integer", "null"], "minimum": 0},
    "category_id": {"type": ["integer", "null"], "minimum": 1},
    "category_name": {"type": ["string", "null"]},
    "payment_method_id": {"type": ["integer", "null"], "minimum": 1},
    "payment_method_name": {"type": ["string", "null"]},
    "transfer_payment_method_id": {"type": ["integer", "null"], "minimum": 1},
    "transfer_payment_method_name": {"type": ["string", "null"]},
    "partner_id": {"type": ["integer", "null"], "minimum": 1},
    "partner_name": {"type": ["string", "null"]},
    "partner_ledger_type": {"type": ["string", "null"], "enum": ["balance_check", None]},
    "partner_ledger_amount_cents": {"type": ["integer", "null"]},
    "partner_balance_after_cents": {"type": ["integer", "null"], "minimum": 0},
    "partner_balance_kind": {"type": ["string", "null"], "enum": ["prepaid_balance", "credit_used", None]},
    "notes": {"type": ["string", "null"]},
}

# Extra records are matched by candidate name and never carry a partner
# balance, so they use a compact shape: output length drives the provider's
# response time, and a long run of purchases must still fit the timeout.
_AI_PARSE_EXTRA_RECORD_KEYS = [
    "occurred_at", "kind", "direction", "amount_cents", "account_balance_cents", "category_name",
    "payment_method_name", "transfer_payment_method_name", "partner_name", "notes",
]

_AI_PARSE_FIELD_STATUS_KEYS = [
    "occurred_at", "direction", "amount_cents", "category",
    "payment_method", "transfer_payment_method", "partner",
]

AI_PARSE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {"type": "string", "enum": ["complete", "need_more_info"]},
        "parsed": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                **_AI_PARSE_RECORD_PROPERTIES,
                "field_status": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        key: {"type": "string", "enum": ["explicit", "inferred", "missing"]}
                        for key in _AI_PARSE_FIELD_STATUS_KEYS
                    },
                    "required": _AI_PARSE_FIELD_STATUS_KEYS,
                },
            },
            "required": [*_AI_PARSE_RECORD_PROPERTIES, "field_status"],
        },
        "missing_fields": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": ["direction", "amount_cents", "account_balance_cents", "category", "payment_method", "transfer_payment_method", "partner"],
            },
        },
        "follow_up_question": {"type": ["string", "null"]},
        "brief_comment": {"type": ["string", "null"]},
        # Further records described by the same message.
        "extra_records": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {key: _AI_PARSE_RECORD_PROPERTIES[key] for key in _AI_PARSE_EXTRA_RECORD_KEYS},
                "required": _AI_PARSE_EXTRA_RECORD_KEYS,
            },
        },
    },
    "required": ["status", "parsed", "missing_fields", "follow_up_question", "brief_comment", "extra_records"],
}

AI_PARSE_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "pennypilot_parse",
        "strict": True,
        "schema": AI_PARSE_JSON_SCHEMA,
    },
}


def _is_deepseek_model(model: str) -> bool:
    return "deepseek" in (model or "").strip().lower()


def response_format_for_provider(
    provider: "Provider", response_format: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Select the structured-output dialect supported by a model family.

    OpenAI-compatible gateways are not uniform: GPT models support the
    strict ``json_schema`` contract used by PennyPilot, while DeepSeek's
    documented JSON Output API accepts ``json_object``.  Keep this decision
    model-based so a gateway URL or a per-user endpoint does not determine the
    wire protocol.
    """

    if response_format is None:
        return None
    model = (provider.model or "").strip().lower()
    if _is_deepseek_model(model):
        return {"type": "json_object"}
    return response_format


def reasoning_controls_for_provider(provider: "Provider", effort: str = "low") -> dict[str, Any]:
    """Reasoning parameters for a model family at the requested effort.

    ``low`` is the lowest-latency mode the family supports and is used by the
    parser; ``high`` asks for the deepest reasoning and is used for ledger
    questions and reports.  DeepSeek and GPT-5 expose different
    OpenAI-compatible request fields.  Keep the decision tied to the model
    name so primary and fallback channels behave the same regardless of which
    endpoint the user assigns to them.  Unknown families keep their defaults.
    """

    model = (provider.model or "").strip().lower()
    deep = effort == "high"
    if _is_deepseek_model(model):
        return {"thinking": {"type": "enabled" if deep else "disabled"}}
    if re.match(r"^gpt-5(?:[.\-]|$)", model):
        return {"reasoning_effort": "high" if deep else "none"}
    if re.match(r"^gpt-6(?:[.\-]|$)", model):
        # GPT-6 cannot switch reasoning off; "low" is its fastest level and
        # makes the gateway stream the reasoning summary.
        return {"reasoning_effort": "high" if deep else "low"}
    return {}


class AIServiceError(Exception):
    """Internal, non-sensitive code for a provider or schema failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Candidate:
    id: int
    name: str
    direction: str | None = None
    kind: str | None = None
    track_balance: bool | None = None
    current_balance_cents: int | None = None
    unsettled_balance_cents: int | None = None
    status: str | None = None


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    api_key: str | None
    model: str
    # Wire protocol of the channel: "openai", "anthropic" or "gemini".
    api_format: str = "openai"

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


def _fernet(settings: Settings) -> Fernet:
    # Deriving the key means no second master secret is needed.  A context
    # string prevents this key from being reused for another purpose.
    material = hashlib.sha256(
        ("PennyPilot/ai-config/v1\0" + settings.secret_key).encode("utf-8")
    ).digest()
    return Fernet(base64.urlsafe_b64encode(material))


def encrypt_api_key(value: str, settings: Settings | None = None) -> str:
    return _fernet(settings or get_settings()).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_api_key(value: str | None, settings: Settings | None = None) -> str | None:
    if not value:
        return None
    try:
        plain = _fernet(settings or get_settings()).decrypt(value.encode("ascii"))
        return plain.decode("utf-8")
    except (InvalidToken, ValueError, UnicodeDecodeError):
        # A changed application secret or corrupted row must not crash every
        # request, and the ciphertext is never sent back to a caller.
        return None


def _validated_base_url(value: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    value = (value or "").strip().rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AIServiceError("invalid_provider_url")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise AIServiceError("invalid_provider_url")
    if settings.app_env == "production" and parsed.scheme != "https":
        raise AIServiceError("invalid_provider_url")
    if settings.app_env == "production":
        hostname = (parsed.hostname or "").lower().rstrip(".")
        if hostname in {"localhost", "localhost.localdomain"}:
            raise AIServiceError("invalid_provider_url")
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            address = None
        if address is not None and (
            address.is_private or address.is_loopback or address.is_link_local or address.is_reserved
        ):
            raise AIServiceError("invalid_provider_url")
    return value


def _api_root(base_url: str) -> str:
    """Host root of a channel URL, without an OpenAI-style version or path suffix."""

    root = _validated_base_url(base_url)
    for suffix in ("/chat/completions", "/messages", "/v1", "/v1beta"):
        root = root.removesuffix(suffix)
    return root.rstrip("/")


def _conversation_turns(messages: list[dict[str, str]]) -> tuple[str, list[tuple[str, str]]]:
    """Split OpenAI-style messages into a system prompt and alternating turns.

    The Anthropic and Gemini formats take the system prompt separately and
    expect the conversation to open with the user, so consecutive messages of
    one role are merged and leading assistant messages are dropped.
    """

    system = "\n\n".join(item["content"] for item in messages if item["role"] == "system")
    turns: list[tuple[str, str]] = []
    for item in messages:
        if item["role"] == "system":
            continue
        role = "assistant" if item["role"] == "assistant" else "user"
        if turns and turns[-1][0] == role:
            turns[-1] = (role, turns[-1][1] + "\n\n" + item["content"])
        elif turns or role == "user":
            turns.append((role, item["content"]))
    return system, turns


def _schema_without(node: Any, *, keys: tuple[str, ...] = (), null_enums: bool = False) -> Any:
    """Copy a JSON schema without the keywords a provider dialect rejects."""

    if isinstance(node, dict):
        result = {key: _schema_without(value, keys=keys, null_enums=null_enums) for key, value in node.items() if key not in keys}
        if null_enums and isinstance(result.get("enum"), list):
            result["enum"] = [value for value in result["enum"] if value is not None]
        return result
    if isinstance(node, list):
        return [_schema_without(value, keys=keys, null_enums=null_enums) for value in node]
    return node


def completion_endpoint(base_url: str) -> str:
    base = _validated_base_url(base_url)
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def _amount_to_cents(value: Any, *, cents: bool = False) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        if isinstance(value, str):
            value = value.strip().replace(",", "")
            if not value:
                return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0 or number > 10_000_000_000:
        return None
    result = round(number if cents else number * 100)
    return int(result) if result > 0 else None


_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000, "亿": 100000000}


def _chinese_number(value: str) -> int | None:
    if not value or not all(c in _CN_DIGITS or c in _CN_UNITS for c in value):
        return None
    total = section = number = 0
    for char in value:
        if char in _CN_DIGITS:
            number = _CN_DIGITS[char]
        else:
            unit = _CN_UNITS[char]
            if unit < 10_000:
                # Chinese omits the leading “一” in 十/百/千 (for example
                # 十五 = 15), so an empty digit before a small unit means 1.
                section += (number or 1) * unit
            else:
                section = section + number
                section = section or 1
                section *= unit
                total += section
                section = 0
            number = 0
    result = total + section + number
    return result if result > 0 else None


def _extract_amount(text_value: str) -> int | None:
    # Prefer a number adjacent to a money marker, avoiding years and clock
    # values.  Chinese numerals cover common mobile input such as “三千五百”.
    patterns = [
        # Include the common current-account verbs (充值/充了/预存/还款)
        # so the deterministic fallback still understands phrases such as
        # “给供货商充了两万预存” when no remote model is configured.
        r"(?:人民币|金额|收款|付款|支付|扫了|转账|转给|打给|花了|花费|共|收入|支出|充值|充|预存|还款|还)\s*(?:了|入|到|给)?\s*[:：]?\s*([0-9][0-9,]*(?:\.\d{1,2})?|[零〇一二两三四五六七八九十百千万亿]+)\s*(?:元|块|人民币|元钱)?",
        r"([0-9][0-9,]*(?:\.\d{1,2})?)\s*(?:元|块|人民币)",
        r"([零〇一二两三四五六七八九十百千万亿]+)\s*(?:元|块)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text_value)
        if not match:
            continue
        raw = match.group(1).replace(",", "")
        if raw and raw[0].isdigit():
            return _amount_to_cents(raw)
        chinese = _chinese_number(raw)
        return chinese * 100 if chinese else None
    # A bare number is accepted only when it is not obviously a year/time.
    for match in re.finditer(r"(?<![\d-])([0-9]+(?:\.\d{1,2})?)(?![\d-])", text_value):
        raw = match.group(1)
        number = float(raw)
        if 0 < number <= 10_000_000 and not (len(raw) == 4 and 1900 <= number <= 2200):
            return _amount_to_cents(raw)
    return None


def _parse_time(text_value: str, reference: datetime) -> datetime:
    # Relative Chinese dates and clock expressions are business-local.  Keep
    # the resulting aware value's +08:00 offset until confirmation, where the
    # normal accounting path converts it to the UTC persistence instant.
    ref = to_business(reference)
    if isinstance(text_value, str):
        try:
            parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=ref.tzinfo or BUSINESS_TZ)
        except ValueError:
            pass
    base = ref
    if "前天" in text_value:
        base -= timedelta(days=2)
    elif "昨天" in text_value:
        base -= timedelta(days=1)
    elif "明天" in text_value:
        base += timedelta(days=1)
    date_match = re.search(r"(20\d{2})[-年](\d{1,2})[-月](\d{1,2})日?", text_value)
    if date_match:
        try:
            base = base.replace(year=int(date_match.group(1)), month=int(date_match.group(2)), day=int(date_match.group(3)))
        except ValueError:
            pass
    clock = re.search(r"(?:上午|早上|下午|晚上|中午)?\s*(\d{1,2})(?:[:：点时](\d{1,2})?)", text_value)
    if clock is None:
        # Mobile Chinese input often spells the hour out (for example
        # “今天下午三点”).  Keep the deterministic fallback useful when no
        # remote model is configured.
        clock_cn = re.search(
            r"(?:上午|早上|下午|晚上|中午)?\s*([零〇一二两三四五六七八九十百]+)\s*(?:点|时)(半|([零〇一二两三四五六七八九十]+))?",
            text_value,
        )
        if clock_cn:
            hour = _chinese_number(clock_cn.group(1))
            if clock_cn.group(2) == "半":
                minute = 30
            else:
                minute = _chinese_number(clock_cn.group(3) or "零") or 0
            clock = (hour, minute)
    if clock:
        if isinstance(clock, tuple):
            hour, minute = clock
        else:
            hour = int(clock.group(1))
            minute = int(clock.group(2) or 0)
        if "下午" in text_value or "晚上" in text_value:
            if hour < 12:
                hour += 12
        if "中午" in text_value and hour < 11:
            hour += 12
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            base = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return base


_MISSING_FIELD_ALIASES = {
    "direction": "direction",
    "amount": "amount_cents",
    "amount_cents": "amount_cents",
    "account_balance_cents": "account_balance_cents",
    "account_balance": "account_balance_cents",
    "balance": "account_balance_cents",
    "category": "category",
    "category_id": "category",
    "category_name": "category",
    "payment": "payment_method",
    "payment_method": "payment_method",
    "payment_method_id": "payment_method",
    "payment_method_name": "payment_method",
    "transfer_payment_method": "transfer_payment_method",
    "transfer_payment_method_id": "transfer_payment_method",
    "transfer_payment_method_name": "transfer_payment_method",
    "target_payment_method": "transfer_payment_method",
    "target_payment_method_id": "transfer_payment_method",
    "to_payment_method": "transfer_payment_method",
    "to_payment_method_id": "transfer_payment_method",
    "partner": "partner",
    "partner_id": "partner",
    "partner_name": "partner",
    "occurred_at": "occurred_at",
    "occurred_time": "occurred_at",
    "time": "occurred_at",
    "date": "occurred_at",
}


def _canonical_missing_fields(value: Any) -> list[str]:
    """Normalize provider metadata without letting it drive completeness.

    Provider schemas frequently report display-name keys (for example
    ``category_name``) rather than the business key (``category``).  The
    normalized list is useful for diagnostics/inference, but required fields
    are always recomputed from the resolved proposal below.
    """

    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise AIServiceError("provider_invalid_schema")
    result: list[str] = []
    for item in value:
        canonical = _MISSING_FIELD_ALIASES.get(item.strip().lower())
        if canonical and canonical not in result:
            result.append(canonical)
    return result


def _required_missing_fields(parsed: dict[str, Any], mode: str = "cash") -> list[str]:
    """Return only fields that actually block an explicit confirmation."""

    missing: list[str] = []
    kind = parsed.get("kind") or "cashflow"
    if mode == "partner":
        if parsed.get("amount_cents") is None and parsed.get("partner_ledger_amount_cents") is None:
            missing.append("amount_cents")
    elif kind == "balance_check":
        if parsed.get("payment_method_id") is None:
            missing.append("payment_method")
        if parsed.get("account_balance_cents") is None:
            missing.append("account_balance_cents")
    else:
        if parsed.get("direction") not in {"income", "expense"}:
            missing.append("direction")
        if parsed.get("amount_cents") is None:
            missing.append("amount_cents")
        if kind != "transfer" and parsed.get("category_id") is None:
            missing.append("category")
        if parsed.get("payment_method_id") is None:
            missing.append("payment_method")
        if kind == "transfer" and parsed.get("transfer_payment_method_id") is None:
            missing.append("transfer_payment_method")
    # Ordinary transactions may mention a customer/supplier without creating
    # a current-account movement.  A partner becomes mandatory only when the
    # proposal explicitly asks for such a ledger movement.
    if parsed.get("partner_ledger_type") and parsed.get("partner_id") is None:
        missing.append("partner")
    return missing


def _explicit_fallback_notes(text_value: str) -> tuple[bool, str | None]:
    source = (text_value or "").strip()
    if not source:
        return False, None
    marker = re.search(r"备注\s*(?:是|为)?\s*[:：]?\s*(.*)$", source, flags=re.S)
    if marker:
        note = marker.group(1).strip(" \t\r\n,，;；。:：")
        return True, note or None
    return False, None


def _fallback_notes(text_value: str) -> str | None:
    """Extract an explicit Chinese note, otherwise retain useful source text."""

    source = (text_value or "").strip()
    explicit, note = _explicit_fallback_notes(source)
    return note if explicit else (source or None)


def _field_status(
    parsed: dict[str, Any],
    missing: Iterable[str],
    inferred: Iterable[str] = (),
) -> dict[str, str]:
    missing_set = set(missing)
    inferred_set = set(inferred)
    fields = ["occurred_at", "direction", "amount_cents", "category", "payment_method", "partner"]
    if parsed.get("kind") == "balance_check":
        fields = ["occurred_at", "payment_method", "account_balance_cents"]
    if (
        parsed.get("kind") == "transfer"
        or "transfer_payment_method" in missing_set
        or parsed.get("transfer_payment_method_id") is not None
        or parsed.get("transfer_payment_method_name") is not None
    ):
        fields.append("transfer_payment_method")
    result: dict[str, str] = {}
    for field in fields:
        if field in missing_set:
            result[field] = "missing"
        elif field in inferred_set:
            result[field] = "inferred"
        elif parsed.get(field) is not None or parsed.get(field + "_id") is not None or parsed.get(field + "_name") is not None:
            result[field] = "explicit"
        else:
            result[field] = "inferred"
    return result


def _clean_brief_comment(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split()).strip()
    return cleaned[:300].rstrip() or None


def _default_brief_comment(parsed: AIParsedTransaction, mode: str) -> str:
    """Provide a safe one-sentence comment if a compatible model omits it."""

    has_partner = bool(parsed.partner_ledger_type and (parsed.partner_id or parsed.partner_name))
    has_cash = bool(parsed.amount_cents and parsed.direction and parsed.payment_method_id)
    if has_partner and has_cash:
        return "这笔记录同时包含现金收支和当前未结算余额，确认后会一次同步到两本账。"
    if mode == "partner" or has_partner:
        return "这次只更新往来账户的当前未结算余额，不会影响现金收支。"
    if parsed.kind == "transfer":
        return "这笔记录属于账户间转账或还款，只调整账户余额，不计入日常收入或支出。"
    if parsed.kind == "balance_check":
        return "这是一次余额校准，确认后会按与系统余额的差额生成一笔收入或支出流水。"
    if parsed.direction == "income":
        return "这笔收入会增加所选资金账户余额，确认前请核对金额、分类和到账账户。"
    if parsed.direction == "expense":
        return "这笔支出会计入所选分类并更新对应资金账户余额，确认前请核对关键信息。"
    return "这条描述还缺少必要信息，补充后即可形成可确认的完整记录。"


class AIService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def _config_row_for_user(self, db: Session, user_id: int) -> AIConfig | None:
        try:
            return db.scalar(select(AIConfig).where(AIConfig.user_id == user_id))
        except SQLAlchemyError:
            return None

    def server_default(self, name: str) -> Any:
        """A deployment-level AI setting, or ``None`` when it is not shared.

        The server's own channel (address, model, key) belongs to whoever
        runs the deployment.  With sharing off, a user's missing fields are
        never filled in from it.
        """

        return getattr(self.settings, name) if self.settings.ai_share_with_users else None

    def provider_for_user(self, db: Session, user_id: int) -> Provider:
        default_base_url = self.server_default("ai_base_url") or PUBLIC_AI_BASE_URL
        base_url, model, key = default_base_url, self.server_default("ai_model") or PUBLIC_AI_MODEL, self.server_default("ai_api_key")
        row = self._config_row_for_user(db, user_id)
        if row:
            base_url = row.base_url or base_url
            model = row.model or model
            key = decrypt_api_key(row.encrypted_api_key, self.settings) or key
        try:
            base_url = _validated_base_url(base_url)
        except AIServiceError:
            base_url = default_base_url
        api_format = getattr(row, "api_format", None) or self.server_default("ai_api_format") or "openai"
        return Provider(name="primary", base_url=base_url, api_key=(key or None), model=model.strip(), api_format=api_format)

    def fallback_api_format(self, row: AIConfig | None) -> str:
        return getattr(row, "fallback_api_format", None) or self.server_default("ai_fallback_api_format") or "openai"

    def provider_chain_for_user(self, db: Session, user_id: int) -> list[Provider]:
        primary = self.provider_for_user(db, user_id)
        row = self._config_row_for_user(db, user_id)
        fallback_base_url = getattr(row, "fallback_base_url", None) or self.server_default("ai_fallback_base_url") or primary.base_url
        fallback_model = getattr(row, "fallback_model", None) or self.server_default("ai_fallback_model") or primary.model
        fallback_api_key = (
            decrypt_api_key(getattr(row, "encrypted_fallback_api_key", None), self.settings)
            or self.server_default("ai_fallback_api_key")
            or primary.api_key
        )
        try:
            fallback_base_url = _validated_base_url(fallback_base_url, self.settings)
        except AIServiceError:
            fallback_base_url = None
        fallback = None
        if fallback_base_url and fallback_model:
            fallback = Provider(
                name="fallback",
                base_url=fallback_base_url,
                api_key=(fallback_api_key or None),
                model=fallback_model.strip(),
                api_format=self.fallback_api_format(row),
            )
        providers = [primary]
        if fallback and (fallback.base_url, fallback.api_key, fallback.model, fallback.api_format) != (primary.base_url, primary.api_key, primary.model, primary.api_format):
            providers.append(fallback)
        return providers

    @staticmethod
    def key_hint(key: str | None) -> str | None:
        if not key:
            return None
        return "••••" + key[-4:]

    def candidates(self, db: Session, user_id: int) -> tuple[list[Candidate], list[Candidate], list[Candidate]]:
        categories = [Candidate(x.id, x.name, x.direction) for x in db.scalars(
            select(Category).where(Category.user_id == user_id, Category.is_active.is_(True)).order_by(Category.sort_order, Category.id).limit(MAX_CANDIDATES)
        ).all()]
        methods = [Candidate(
            x.id,
            x.name,
            kind=getattr(x, "account_role", "cash") or "cash",
            track_balance=bool(getattr(x, "track_balance", False)),
            current_balance_cents=getattr(x, "current_balance_cents", None),
        ) for x in db.scalars(
            select(PaymentMethod).where(PaymentMethod.user_id == user_id, PaymentMethod.is_active.is_(True)).order_by(PaymentMethod.sort_order, PaymentMethod.id).limit(MAX_CANDIDATES)
        ).all()]
        partners: list[Candidate] = []
        # Partners are introduced by the adjacent phase.  Reading through a
        # narrowly selected SQL statement keeps this module importable before
        # that migration and avoids coupling to its model class.
        try:
            bind = db.get_bind()
            inspector = inspect(bind)
            if "partners" in inspector.get_table_names():
                columns = {item["name"] for item in inspector.get_columns("partners")}
                if {"id", "name", "user_id"}.issubset(columns):
                    kind_col = "type" if "type" in columns else ("kind" if "kind" in columns else None)
                    kind_sql = f", {kind_col}" if kind_col else ""
                    optional_partner_columns = [
                        column for column in (
                            "prepaid_balance_cents",
                            "credit_limit_cents",
                            "credit_used_cents",
                            "status",
                        ) if column in columns
                    ]
                    balance_sql = "".join(f", {column}" for column in optional_partner_columns)
                    if "is_active" in columns:
                        active_sql = " AND is_active = true"
                    elif "status" in columns:
                        active_sql = " AND status = 'active'"
                    else:
                        active_sql = ""
                    rows = db.execute(text(f"SELECT id, name{kind_sql} AS partner_kind{balance_sql} FROM partners WHERE user_id=:uid{active_sql} ORDER BY id LIMIT :limit"), {"uid": user_id, "limit": MAX_CANDIDATES}).mappings()
                    partners = []
                    for row in rows:
                        partner_kind = str(row.get("partner_kind") or "").lower()
                        unsettled_balance = (
                            int(row.get("credit_used_cents") or 0)
                            if partner_kind == "customer"
                            else int(row.get("prepaid_balance_cents") or 0)
                        )
                        partners.append(Candidate(
                            int(row["id"]),
                            str(row["name"]),
                            kind=partner_kind,
                            unsettled_balance_cents=unsettled_balance,
                            status=str(row.get("status") or "active"),
                        ))
        except Exception:
            partners = []
        return categories, methods, partners

    def _chat(
        self,
        provider: Provider,
        messages: list[dict[str, str]],
        *,
        max_bytes: int | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        request_id: str = "-",
        on_delta: Callable[[str, str], None] | None = None,
        effort: str = "low",
    ) -> str:
        if not self.settings.ai_enabled or not provider.api_key:
            raise AIServiceError("not_configured")
        if provider.api_format != "openai":
            native = self._chat_anthropic if provider.api_format == "anthropic" else self._chat_gemini
            return native(
                provider,
                messages,
                max_tokens=max_tokens,
                response_format=response_format,
                limit=max_bytes or self.settings.ai_max_response_bytes,
                on_delta=on_delta or (lambda kind, text: None),
                request_id=request_id,
                effort=effort,
            )
        endpoint = completion_endpoint(provider.base_url)
        reasoning_controls = reasoning_controls_for_provider(provider, effort)
        base_payload = {
            "model": provider.model,
            "messages": messages,
            "temperature": 0.2,
            # ``on_delta`` switches to a streamed completion: it is called with
            # ("start", "") for every HTTP attempt and then with each
            # ("reasoning" | "content", text) delta.
            "stream": on_delta is not None,
            **reasoning_controls,
        }
        if max_tokens is not None:
            base_payload["max_tokens"] = max_tokens
        headers = {"Authorization": "Bearer " + provider.api_key, "Content-Type": "application/json"}
        limit = max_bytes or self.settings.ai_max_response_bytes
        provider_response_format = response_format_for_provider(provider, response_format)
        is_deepseek = _is_deepseek_model(provider.model)
        # A few OpenAI-compatible gateways have not implemented structured
        # output yet. Try the provider-specific request first, then retry that
        # same provider without response_format only when it rejects the
        # request itself.
        structured_attempts = [True, False] if provider_response_format else [False]
        for structured in structured_attempts:
            payload = dict(base_payload)
            if structured:
                payload["response_format"] = provider_response_format
            payload_bytes = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            empty_content_retries = 0
            while True:
                attempt_started = time.monotonic()
                logger.debug(
                    "AI provider request id=%s provider=%s model=%s reasoning=%s structured=%s format=%s endpoint_host=%s messages=%d payload_bytes=%d",
                    request_id,
                    provider.name,
                    provider.model,
                    "disabled" if reasoning_controls else "provider_default",
                    structured,
                    (provider_response_format or {}).get("type", "none"),
                    urlsplit(endpoint).hostname or "-",
                    len(messages),
                    payload_bytes,
                )
                try:
                    timeout_seconds = max(self.settings.ai_timeout_seconds, DEEPSEEK_READ_TIMEOUT_SECONDS) if is_deepseek else self.settings.ai_timeout_seconds
                    if on_delta is not None:
                        timeout_seconds = max(timeout_seconds, AI_STREAM_IDLE_TIMEOUT_SECONDS)
                        on_delta("start", "")
                    connect_timeout = min(
                        DEEPSEEK_CONNECT_TIMEOUT_SECONDS if is_deepseek else 5.0,
                        timeout_seconds,
                    )
                    timeout = httpx.Timeout(timeout_seconds, connect=connect_timeout)
                    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
                        with client.stream("POST", endpoint, headers=headers, json=payload) as response:
                            if response.status_code >= 400:
                                logger.warning(
                                    "AI provider HTTP error id=%s provider=%s model=%s structured=%s format=%s status=%d elapsed_ms=%d",
                                    request_id,
                                    provider.name,
                                    provider.model,
                                    structured,
                                    (provider_response_format or {}).get("type", "none"),
                                    response.status_code,
                                    round((time.monotonic() - attempt_started) * 1000),
                                )
                                if structured and response.status_code in {400, 404, 422}:
                                    raise AIServiceError("provider_structured_output_unsupported")
                                raise AIServiceError("provider_http_error")
                            chunks: list[bytes] = []
                            size = 0
                            streamed: str | None = None
                            if on_delta is not None:
                                streamed = self._read_stream(
                                    response, limit, on_delta, attempt_started + AI_STREAM_TOTAL_TIMEOUT_SECONDS
                                )
                            else:
                                for chunk in response.iter_bytes():
                                    size += len(chunk)
                                    if size > limit:
                                        raise AIServiceError("provider_response_too_large")
                                    chunks.append(chunk)
                    raw_response = b"".join(chunks)
                    logger.debug(
                        "AI provider response id=%s provider=%s model=%s structured=%s format=%s status=200 response_bytes=%d elapsed_ms=%d",
                        request_id,
                        provider.name,
                        provider.model,
                        structured,
                        (provider_response_format or {}).get("type", "none"),
                        len(raw_response),
                        round((time.monotonic() - attempt_started) * 1000),
                    )
                    if streamed is not None:
                        content = streamed
                    else:
                        data = json.loads(raw_response.decode("utf-8"))
                        content = data.get("choices", [{}])[0].get("message", {}).get("content")
                    if not isinstance(content, str) or not content.strip():
                        # DeepSeek documents that JSON Output can occasionally
                        # return HTTP 200 with an empty content. Retry the same
                        # structured request once before failing over.
                        if structured and (provider_response_format or {}).get("type") == "json_object" and empty_content_retries < 1:
                            empty_content_retries += 1
                            logger.warning(
                                "AI provider returned empty content; retrying structured request id=%s provider=%s model=%s retry=%d",
                                request_id,
                                provider.name,
                                provider.model,
                                empty_content_retries,
                            )
                            continue
                        raise AIServiceError("provider_invalid_response")
                    if len(content.encode("utf-8")) > limit:
                        raise AIServiceError("provider_response_too_large")
                    return content.strip()
                except AIServiceError as exc:
                    if structured and exc.code == "provider_structured_output_unsupported":
                        logger.debug(
                            "AI provider structured output rejected; retrying plain JSON id=%s provider=%s code=%s",
                            request_id,
                            provider.name,
                            (provider_response_format or {}).get("type", "none"),
                            exc.code,
                        )
                        break
                    raise
                except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, UnicodeError) as exc:
                    logger.warning(
                        "AI provider transport/decoding error id=%s provider=%s model=%s structured=%s format=%s error_type=%s elapsed_ms=%d",
                        request_id,
                        provider.name,
                        provider.model,
                        structured,
                        (provider_response_format or {}).get("type", "none"),
                        type(exc).__name__,
                        round((time.monotonic() - attempt_started) * 1000),
                    )
                    raise AIServiceError("provider_unavailable")
        raise AIServiceError("provider_http_error")

    def _chat_gemini(
        self,
        provider: Provider,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None,
        response_format: dict[str, Any] | None,
        limit: int,
        on_delta: Callable[[str, str], None],
        request_id: str,
        effort: str = "low",
    ) -> str:
        """Call a Gemini ``streamGenerateContent`` endpoint.

        Thought summaries are requested so the caller can show the model's
        reasoning.  A channel that rejects them, or the response schema, is
        asked again with a plain request.
        """

        system, turns = _conversation_turns(messages)
        endpoint = f"{_api_root(provider.base_url)}/v1beta/models/{quote(provider.model, safe='')}:streamGenerateContent?alt=sse"
        plain: dict[str, Any] = {"temperature": 0.2}
        if max_tokens is not None:
            plain["maxOutputTokens"] = max_tokens
        # The parser keeps the model's own thinking level; analysis asks for the deepest.
        full: dict[str, Any] = {**plain, "thinkingConfig": {"includeThoughts": True, **({"thinkingLevel": "high"} if effort == "high" else {})}}
        if response_format is not None:
            full["responseMimeType"] = "application/json"
            # Gemini rejects ``null`` inside an enum; nullability stays in ``type``.
            full["responseJsonSchema"] = _schema_without(response_format["json_schema"]["schema"], null_enums=True)
        body: dict[str, Any] = {
            "contents": [{"role": "model" if role == "assistant" else "user", "parts": [{"text": text_value}]} for role, text_value in turns],
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        headers = {"x-goog-api-key": provider.api_key, "Content-Type": "application/json"}
        timeout_seconds = max(self.settings.ai_timeout_seconds, AI_STREAM_IDLE_TIMEOUT_SECONDS)
        timeout = httpx.Timeout(timeout_seconds, connect=min(5.0, timeout_seconds))
        for generation in (full, plain):
            started = time.monotonic()
            on_delta("start", "")
            parts: list[str] = []
            size = 0
            try:
                with httpx.Client(timeout=timeout, follow_redirects=False) as client:
                    with client.stream("POST", endpoint, headers=headers, json={**body, "generationConfig": generation}) as response:
                        if response.status_code >= 400:
                            logger.warning(
                                "AI provider HTTP error id=%s provider=%s model=%s format=gemini enhanced=%s status=%d",
                                request_id,
                                provider.name,
                                provider.model,
                                generation is full,
                                response.status_code,
                            )
                            if generation is full and response.status_code in {400, 422}:
                                continue
                            raise AIServiceError("provider_http_error")
                        for line in response.iter_lines():
                            if time.monotonic() - started > AI_STREAM_TOTAL_TIMEOUT_SECONDS:
                                raise AIServiceError("provider_unavailable")
                            if not line.startswith("data:"):
                                continue
                            for candidate in json.loads(line[5:]).get("candidates") or []:
                                for part in (candidate.get("content") or {}).get("parts") or []:
                                    text_delta = part.get("text")
                                    if not isinstance(text_delta, str) or not text_delta:
                                        continue
                                    if part.get("thought"):
                                        on_delta("reasoning", text_delta)
                                        continue
                                    size += len(text_delta.encode("utf-8"))
                                    if size > limit:
                                        raise AIServiceError("provider_response_too_large")
                                    parts.append(text_delta)
                                    on_delta("content", text_delta)
            except AIServiceError:
                raise
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, AttributeError, UnicodeError) as exc:
                logger.warning(
                    "AI provider transport/decoding error id=%s provider=%s model=%s format=gemini error_type=%s",
                    request_id,
                    provider.name,
                    provider.model,
                    type(exc).__name__,
                )
                raise AIServiceError("provider_unavailable")
            content = "".join(parts).strip()
            if not content:
                raise AIServiceError("provider_invalid_response")
            return content
        raise AIServiceError("provider_http_error")

    def _chat_anthropic(
        self,
        provider: Provider,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None,
        response_format: dict[str, Any] | None,
        limit: int,
        on_delta: Callable[[str, str], None],
        request_id: str,
        effort: str = "low",
    ) -> str:
        """Call the Anthropic Messages API through the official SDK.

        The first request asks for a summarized view of the model's thinking
        at low effort and, for the parser, a schema-constrained answer.
        Models or gateways that reject those options get a plain request.
        """

        system, turns = _conversation_turns(messages)
        plain: dict[str, Any] = {
            "model": provider.model,
            "max_tokens": max(max_tokens or 0, ANTHROPIC_MAX_TOKENS),
            "messages": [{"role": role, "content": text_value} for role, text_value in turns],
        }
        if system:
            plain["system"] = system
        output_config: dict[str, Any] = {"effort": "max" if effort == "high" else "low"}
        if response_format is not None:
            # Structured outputs do not accept numeric constraints.
            output_config["format"] = {
                "type": "json_schema",
                "schema": _schema_without(response_format["json_schema"]["schema"], keys=("minimum",)),
            }
        full = {**plain, "thinking": {"type": "adaptive", "display": "summarized"}, "output_config": output_config}
        timeout_seconds = max(self.settings.ai_timeout_seconds, AI_STREAM_IDLE_TIMEOUT_SECONDS)
        with anthropic.Anthropic(
            api_key=provider.api_key,
            base_url=_api_root(provider.base_url),
            max_retries=0,
            timeout=anthropic.Timeout(timeout_seconds, connect=min(5.0, timeout_seconds)),
        ) as client:
            for params in (full, plain):
                started = time.monotonic()
                on_delta("start", "")
                size = 0
                try:
                    with client.messages.stream(**params) as stream:
                        for event in stream:
                            if time.monotonic() - started > AI_STREAM_TOTAL_TIMEOUT_SECONDS:
                                raise AIServiceError("provider_unavailable")
                            if event.type != "content_block_delta":
                                continue
                            if event.delta.type == "thinking_delta":
                                on_delta("reasoning", event.delta.thinking)
                            elif event.delta.type == "text_delta":
                                size += len(event.delta.text.encode("utf-8"))
                                if size > limit:
                                    raise AIServiceError("provider_response_too_large")
                                on_delta("content", event.delta.text)
                        message = stream.get_final_message()
                except anthropic.BadRequestError:
                    logger.warning(
                        "AI provider rejected request id=%s provider=%s model=%s format=anthropic enhanced=%s",
                        request_id,
                        provider.name,
                        provider.model,
                        params is full,
                    )
                    if params is full:
                        continue
                    raise AIServiceError("provider_http_error")
                except anthropic.APIStatusError as exc:
                    logger.warning(
                        "AI provider HTTP error id=%s provider=%s model=%s format=anthropic status=%d",
                        request_id,
                        provider.name,
                        provider.model,
                        exc.status_code,
                    )
                    raise AIServiceError("provider_http_error")
                except anthropic.APIConnectionError as exc:
                    logger.warning(
                        "AI provider transport error id=%s provider=%s model=%s format=anthropic error_type=%s",
                        request_id,
                        provider.name,
                        provider.model,
                        type(exc).__name__,
                    )
                    raise AIServiceError("provider_unavailable")
                if message.stop_reason == "refusal":
                    raise AIServiceError("provider_refused")
                content = "".join(block.text for block in message.content if block.type == "text").strip()
                if not content:
                    raise AIServiceError("provider_invalid_response")
                return content
        raise AIServiceError("provider_http_error")

    @staticmethod
    def _read_stream(response: Any, limit: int, on_delta: Callable[[str, str], None], deadline: float) -> str:
        """Collect an OpenAI-compatible SSE completion, reporting deltas as they arrive."""

        parts: list[str] = []
        plain: list[str] = []
        size = 0
        for line in response.iter_lines():
            if time.monotonic() > deadline:
                raise AIServiceError("provider_unavailable")
            if not line.startswith("data:"):
                # A gateway that ignores ``stream`` answers with one JSON body.
                size += len(line)
                if size > limit:
                    raise AIServiceError("provider_response_too_large")
                plain.append(line)
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            for choice in (chunk.get("choices") or []) if isinstance(chunk, dict) else []:
                delta = choice.get("delta") or {}
                reasoning = delta.get("reasoning_content")
                if isinstance(reasoning, str) and reasoning:
                    on_delta("reasoning", reasoning)
                text_delta = delta.get("content")
                if isinstance(text_delta, str) and text_delta:
                    # SSE framing is many times larger than the text it
                    # carries, so the limit applies to the collected content.
                    size += len(text_delta.encode("utf-8"))
                    if size > limit:
                        raise AIServiceError("provider_response_too_large")
                    parts.append(text_delta)
                    on_delta("content", text_delta)
        if parts or not plain:
            return "".join(parts)
        body = json.loads("\n".join(plain))
        content = body.get("choices", [{}])[0].get("message", {}).get("content")
        return content if isinstance(content, str) else ""

    @staticmethod
    def _json_content(content: str) -> dict[str, Any]:
        value = content.strip()
        if value.startswith("```"):
            value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.I | re.S).strip()
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            raise AIServiceError("provider_invalid_json")
        if not isinstance(parsed, dict):
            raise AIServiceError("provider_invalid_json")
        return parsed

    @staticmethod
    def _match(name: str | None, options: list[Candidate], direction: str | None = None) -> Candidate | None:
        if not name:
            return None
        needle = name.strip().lower()
        choices = [x for x in options if direction is None or x.direction in (None, direction)]
        for item in choices:
            if item.name.lower() == needle:
                return item
        for item in choices:
            if item.name.lower() in needle or needle in item.name.lower():
                return item
        return None

    @staticmethod
    def _needs_model_recheck(response: AIParseResponse) -> bool:
        """Retry a structurally valid but semantically empty model proposal.

        Some JSON-mode models can describe the user's transaction correctly in
        ``brief_comment`` while copying the all-null example into ``parsed``.
        This is not a schema or transport failure, so provider failover would
        not run.  Give the same model one bounded self-correction opportunity;
        the backend still accepts only a strictly validated proposal.
        """

        if response.status != "need_more_info":
            return False
        parsed = response.parsed
        return all(
            value is None
            for value in (
                parsed.direction,
                parsed.amount_cents,
                parsed.category_id,
                parsed.category_name,
                parsed.payment_method_id,
                parsed.payment_method_name,
                parsed.transfer_payment_method_id,
                parsed.transfer_payment_method_name,
                parsed.partner_id,
                parsed.partner_name,
                parsed.partner_ledger_type,
                parsed.partner_balance_after_cents,
            )
        )

    @staticmethod
    def _proposal_information_score(response: AIParseResponse) -> int:
        parsed = response.parsed
        values = (
            parsed.direction,
            parsed.amount_cents,
            parsed.category_id or parsed.category_name,
            parsed.payment_method_id or parsed.payment_method_name,
            parsed.transfer_payment_method_id or parsed.transfer_payment_method_name,
            parsed.partner_id or parsed.partner_name,
            parsed.partner_ledger_type,
            parsed.partner_balance_after_cents,
        )
        return sum(value is not None for value in values) + (10 if response.status == "complete" else 0)

    @staticmethod
    def _normalize_model_payload(raw: dict[str, Any]) -> dict[str, Any]:
        # Providers in the OpenAI-compatible ecosystem commonly return either
        # a wrapped object (``{"parsed": {...}, "missing_fields": [...]}``)
        # or the requested transaction fields directly.  Accept both shapes,
        # while still rejecting unknown keys so arbitrary model output cannot
        # become a confirmation payload.
        # Some compatible providers incorrectly put ``field_status`` beside
        # the envelope instead of inside ``parsed``.  It is advisory model
        # metadata either way and is intentionally discarded before Pydantic
        # validation; the backend recomputes the authoritative values.
        envelope_keys = {"status", "parsed", "missing_fields", "follow_up_question", "brief_comment", "field_status", "extra_records"}
        if "parsed" in raw:
            if set(raw) - envelope_keys:
                raise AIServiceError("provider_invalid_schema")
            parsed = raw["parsed"]
        else:
            parsed = {key: value for key, value in raw.items() if key not in envelope_keys}
        if not isinstance(parsed, dict):
            raise AIServiceError("provider_invalid_schema")
        parsed = dict(parsed)
        brief_comment = raw.get("brief_comment")
        if brief_comment is None:
            brief_comment = parsed.pop("brief_comment", None)
        extra_records = raw.get("extra_records") or []
        if not isinstance(extra_records, list) or any(not isinstance(item, dict) for item in extra_records):
            raise AIServiceError("provider_invalid_schema")
        return {
            "status": raw.get("status"),
            "parsed": AIService._normalize_record_fields(parsed),
            "missing_fields": _canonical_missing_fields(raw.get("missing_fields", [])),
            "follow_up_question": raw.get("follow_up_question"),
            "brief_comment": _clean_brief_comment(brief_comment),
            "extra_records": [AIService._normalize_record_fields(item) for item in extra_records],
        }

    @staticmethod
    def _normalize_record_fields(parsed: dict[str, Any]) -> dict[str, Any]:
        aliases = {
            "time": "occurred_at",
            "occurred_time": "occurred_at",
            "date": "occurred_at",
            "amount": "amount",
            "type": "kind",
            "transaction_kind": "kind",
            "category": "category_name",
            "payment_method": "payment_method_name",
            "payment": "payment_method_name",
            "target_payment_method": "transfer_payment_method_name",
            "target_payment_method_id": "transfer_payment_method_id",
            "to_payment_method": "transfer_payment_method_name",
            "to_payment_method_id": "transfer_payment_method_id",
            "counterparty_payment_method": "transfer_payment_method_name",
            "counterparty_payment_method_id": "transfer_payment_method_id",
            "partner": "partner_name",
            "note": "notes",
        }
        known = {
            "occurred_at",
            "kind",
            "direction",
            "amount_cents",
            "amount",
            "account_balance_cents",
            "category_id",
            "category_name",
            "payment_method_id",
            "payment_method_name",
            "transfer_payment_method_id",
            "transfer_payment_method_name",
            "partner_id",
            "partner_name",
            "partner_ledger_type",
            "partner_ledger_amount_cents",
            "partner_balance_after_cents",
            "partner_balance_kind",
            "notes",
            "field_status",
        }
        normalized: dict[str, Any] = {}
        for key, value in parsed.items():
            mapped = aliases.get(key, key)
            if mapped not in known:
                raise AIServiceError("provider_invalid_schema")
            if mapped == "field_status":
                continue
            normalized[mapped] = value
        if "amount_cents" not in normalized and "amount" in normalized:
            normalized["amount_cents"] = _amount_to_cents(normalized.pop("amount"))
        return normalized

    @staticmethod
    def _has_cash_fields(value: dict[str, Any]) -> bool:
        return value.get("kind") in {"transfer", "balance_check"} or any(
            value.get(key) is not None
            for key in ("direction", "amount_cents", "payment_method_id", "payment_method_name")
        )

    def _complete_parse(self, raw: dict[str, Any], categories: list[Candidate], methods: list[Candidate], partners: list[Candidate], reference: datetime, mode: str = "cash") -> AIParseResponse:
        normalized = self._normalize_model_payload(raw)
        if normalized["status"] not in {None, "complete", "need_more_info"}:
            raise AIServiceError("provider_invalid_schema")
        # Partner mode confirms exactly one balance observation.
        extras = [] if mode == "partner" else normalized["extra_records"]
        cash_values = [item for item in (normalized["parsed"], *extras) if self._has_cash_fields(item)] if extras else []
        if len(cash_values) < 2:
            record = self._complete_record(normalized["parsed"], normalized["missing_fields"], categories, methods, partners, reference, mode)
            return AIParseResponse(
                status=record.status,
                mode=mode,
                parsed=record.parsed,
                missing_fields=record.missing_fields,
                follow_up_question=record.follow_up_question,
                brief_comment=normalized["brief_comment"] or _default_brief_comment(record.parsed, mode),
                source="model",
                warning="本次只整理了第一笔记录，其余内容请单独描述。" if extras else None,
            )
        # A batch is confirmed as plain cash/transfer records.  Current-account
        # balances keep the single-record contract, so they are dropped here
        # with a visible warning instead of being confirmed half-way.
        warnings: list[str] = []
        ledger_keys = ("partner_ledger_type", "partner_ledger_amount_cents", "partner_balance_after_cents", "partner_balance_kind")
        if any(item.get(key) is not None for item in (normalized["parsed"], *extras) for key in ("partner_ledger_type", "partner_balance_after_cents")):
            warnings.append("多笔记录暂不支持同时更新往来未结算余额，请单独记录余额变化。")
        if len(cash_values) > MAX_PARSE_RECORDS:
            cash_values = cash_values[:MAX_PARSE_RECORDS]
            warnings.append(f"一次最多整理 {MAX_PARSE_RECORDS} 笔记录，超出的部分请分批描述。")
        records: list[AIParsedRecord] = []
        for item in cash_values:
            for key in ledger_keys:
                item[key] = None
            reported = normalized["missing_fields"] if item is normalized["parsed"] else []
            records.append(self._complete_record(item, reported, categories, methods, partners, reference, mode))
        missing = [field for record in records for field in record.missing_fields]
        follow = "".join(
            f"第 {index} 笔{record.follow_up_question}"
            for index, record in enumerate(records, start=1)
            if record.follow_up_question
        )
        return AIParseResponse(
            status="complete" if not missing else "need_more_info",
            mode=mode,
            parsed=records[0].parsed,
            missing_fields=list(dict.fromkeys(missing)),
            follow_up_question=follow[:1000] or None,
            brief_comment=normalized["brief_comment"] or f"共整理出 {len(records)} 笔记录，请逐笔核对后勾选需要入账的记录。",
            source="model",
            warning=" ".join(warnings) or None,
            records=records,
        )

    def _complete_record(self, value: dict[str, Any], reported_missing: list[str], categories: list[Candidate], methods: list[Candidate], partners: list[Candidate], reference: datetime, mode: str = "cash") -> AIParsedRecord:
        # Partner mode has no cash dictionary requirements. Confirmation still
        # enforces the selected mode and ignores legacy partner fields in cash
        # mode, preserving parse compatibility for older clients.
        if mode == "partner":
            value["direction"] = None
            value["category_id"] = None
            value["category_name"] = None
            value["payment_method_id"] = None
            value["payment_method_name"] = None
            value["transfer_payment_method_id"] = None
            value["transfer_payment_method_name"] = None
            value["kind"] = "cashflow"
        inferred: set[str] = set()
        if value.get("occurred_at") is None:
            value["occurred_at"] = reference
            inferred.add("occurred_at")
        elif not isinstance(value.get("occurred_at"), datetime):
            value["occurred_at"] = _parse_time(str(value["occurred_at"]), reference)
        if "occurred_at" in reported_missing:
            inferred.add("occurred_at")
        if value.get("amount_cents") is not None:
            value["amount_cents"] = _amount_to_cents(value["amount_cents"], cents=True)
        if value.get("account_balance_cents") is not None:
            value["account_balance_cents"] = _amount_to_cents(value["account_balance_cents"], cents=True)
        direction = value.get("direction")
        if direction not in {"income", "expense"}:
            direction = None
            value["direction"] = None
        kind = value.get("kind") if value.get("kind") in {"cashflow", "transfer", "balance_check"} else "cashflow"
        value["kind"] = kind
        if kind == "balance_check":
            value["direction"] = None
            value["amount_cents"] = None
            value["category_id"] = None
            value["category_name"] = None
        if kind == "transfer":
            value["direction"] = "expense"
            value["category_id"] = None
            value["category_name"] = None
            value["partner_ledger_type"] = None
            value["partner_ledger_amount_cents"] = None
        for field, options in (("category", categories), ("payment_method", methods), ("transfer_payment_method", methods), ("partner", partners)):
            name_key, id_key = field + "_name", field + "_id"
            candidate = next(
                (
                    x
                    for x in options
                    if x.id == value.get(id_key)
                    and (field != "category" or x.direction in (None, direction))
                ),
                None,
            ) if value.get(id_key) else None
            if field == "category" and kind in {"transfer", "balance_check"}:
                continue
            if candidate is None:
                candidate = self._match(value.get(name_key), options, direction if field == "category" else None)
            if candidate:
                value[id_key], value[name_key] = candidate.id, candidate.name
            elif value.get(id_key) is not None:
                value[id_key] = None
        # Some compatible models confuse the partner type ("supplier" /
        # "customer") with the ledger operation.  In the current-account
        # design the operation is always a balance observation, while the
        # partner type is carried by the matched candidate.  Normalize these
        # harmless aliases before strict Pydantic validation so one malformed
        # enum cannot turn both AI channels into a 503.
        if str(value.get("partner_ledger_type") or "").strip().lower() in {
            "supplier",
            "customer",
            "balance",
            "current_balance",
            "unsettled",
            "unsettled_balance",
        }:
            value["partner_ledger_type"] = "balance_check"
        balance_kind = str(value.get("partner_balance_kind") or "").strip().lower()
        if balance_kind in {"supplier", "customer", "balance_check", "unsettled", "unsettled_balance"}:
            matched_partner = next(
                (item for item in partners if item.id == value.get("partner_id")),
                None,
            )
            if matched_partner is None:
                matched_partner = self._match(value.get("partner_name"), partners)
            if matched_partner is not None:
                value["partner_balance_kind"] = (
                    "prepaid_balance" if matched_partner.kind == "supplier" else "credit_used"
                )
            else:
                value["partner_balance_kind"] = None
        if value.get("payment_method_id") and value.get("transfer_payment_method_id") and value["payment_method_id"] == value["transfer_payment_method_id"]:
            value["transfer_payment_method_id"] = None
            value["transfer_payment_method_name"] = None
        if kind == "balance_check" and value.get("payment_method_id") is not None and value.get("account_balance_cents") is not None:
            # The card shows the stored balance and the resulting entry; the
            # confirmation recomputes both against the locked account row.
            account = next((item for item in methods if item.id == value["payment_method_id"]), None)
            expected = int(account.current_balance_cents or 0) if account else 0
            value["account_balance_expected_cents"] = expected
            value["account_balance_delta_cents"] = int(value["account_balance_cents"]) - expected
        try:
            parsed = AIParsedTransaction.model_validate(value)
        except ValidationError:
            raise AIServiceError("provider_invalid_schema")
        # Provider missing metadata is only a hint.  Resolve candidate names
        # first, then decide completeness from fields that can actually be
        # confirmed.  Time defaults to ``reference`` and partner is optional
        # unless a current-account movement was explicitly proposed.
        missing = _required_missing_fields(parsed.model_dump(), mode)
        status = "complete" if not missing else "need_more_info"
        follow = None
        if missing:
            labels = {"direction": "收支方向", "amount_cents": "金额", "account_balance_cents": "账户当前余额", "category": "分类", "payment_method": "来源账户", "transfer_payment_method": "转入/还款账户", "partner": "往来单位"}
            follow = "请补充：" + "、".join(labels.get(x, x) for x in missing) + "。"
        payload = parsed.model_dump()
        payload["field_status"] = _field_status(payload, missing, inferred)
        parsed = AIParsedTransaction.model_validate(payload)
        return AIParsedRecord(status=status, parsed=parsed, missing_fields=missing, follow_up_question=follow)

    def deterministic_parse(self, text_value: str, categories: list[Candidate], methods: list[Candidate], partners: list[Candidate], reference: datetime, warning: str | None = None, mode: str = "cash") -> AIParseResponse:
        def extract_observed_amount(*patterns: str) -> int | None:
            for pattern in patterns:
                match = re.search(pattern, text_value)
                if not match:
                    continue
                raw_value = match.group(1).replace(",", "")
                if raw_value and raw_value[0].isdigit():
                    cents = _amount_to_cents(raw_value)
                    if cents is not None:
                        return cents
                chinese = _chinese_number(raw_value)
                if chinese is not None:
                    return chinese * 100
            return None

        direction = None
        record_intent = bool(re.search(r"(?:帮我|请帮|帮忙|麻烦)?(?:入账|记账|记一笔|记录|加一笔|补记)", text_value))
        liability_context = bool(re.search(r"(信用卡|花呗|白条|借呗|贷款|分期|京东白条)", text_value))
        if re.search(r"收(到|了)|收入|卖出|退款|客户还款", text_value):
            direction = "income"
        elif re.search(r"支出|付(了|给)|付款|支付|扫了|转账|转给|打给|花费|花了|购买|充值|扣款|给.*充|给.*供应商", text_value):
            direction = "expense"
        amount = _extract_amount(text_value)
        mentions_outstanding = bool(re.search(r"(未结算(?:余额)?|欠款)", text_value))
        mentions_available_credit = bool(re.search(r"(可用额度|目前余额|当前余额|余额)", text_value))
        mentions_credit_limit = bool(re.search(r"(授信额度|总额度|额度调整|调整额度|增加授信|授信额度.*增加|增加.*授信)", text_value))
        mentions_refund = "退款" in text_value
        mentions_recharge = bool(re.search(r"(预存|充值)", text_value))
        mentions_credit_repay = bool(re.search(r"(?:还|归还|偿还|结清|支付).*(?:未结算|欠款|授信)|(?:未结算|欠款|授信).*(?:还|归还|偿还|结清|支付)", text_value))
        if direction is None and (record_intent or liability_context) and amount is not None:
            direction = "expense"
        observed_outstanding = extract_observed_amount(
            r"(?:变动后)?\s*(?:未结算(?:余额)?|欠款)\s*(?:为|是|[:：])?\s*([0-9][0-9,]*(?:\.\d{1,2})?|[零〇一二两三四五六七八九十百千万亿]+)"
        )
        observed_available = extract_observed_amount(
            r"(?:目前|当前|增加后|充值后|变动后)?\s*(?:可用额度|目前余额|当前余额|余额)\s*(?:为|是|[:：])?\s*([0-9][0-9,]*(?:\.\d{1,2})?|[零〇一二两三四五六七八九十百千万亿]+)"
        )
        observed_limit = extract_observed_amount(
            r"(?:目前|当前|增加后|变动后)?\s*(?:授信额度|总额度)\s*(?:为|是|[:：])?\s*([0-9][0-9,]*(?:\.\d{1,2})?|[零〇一二两三四五六七八九十百千万亿]+)"
        )
        balance_after = observed_outstanding if observed_outstanding is not None else (observed_limit if observed_limit is not None else observed_available)
        category = next((x for x in categories if x.name in text_value and (direction is None or x.direction == direction)), None)
        if category is None:
            defaults = [("餐", "餐饮"), ("饭", "餐饮"), ("房租", "房租"), ("进货", "进货"), ("货款", "进货"), ("工资", "工资收入"), ("销售", "销售收入")]
            for keyword, target in defaults:
                if keyword in text_value:
                    category = self._match(target, categories, direction)
                    if category:
                        break
        # A generic expense without a more specific business keyword should
        # remain confirmable.  “其他支出” is the built-in catch-all category
        # and is safer than leaving the draft incomplete (especially for
        # liability-account purchases such as credit-card consumption).
        if category is None and direction == "expense" and (record_intent or liability_context or re.search(r"支出|消费|花费|花了|付款|支付|入账|记账", text_value)) and not re.search(r"供应商|客户|预存|授信", text_value):
            category = self._match("其他支出", categories, direction)
        method = next((x for x in methods if x.name in text_value), None)
        partner = next((x for x in partners if x.name in text_value), None)
        partner_kind = str(partner.kind or "").lower() if partner is not None else ""
        if partner is not None and (liability_context or (method is not None and method.kind == "liability")) and not re.search(r"供应商|客户|预存|授信|往来", text_value):
            partner = None
            partner_kind = ""
        partner_balance_context = bool(partner is not None and re.search(r"(未结算(?:余额)?|欠款|目前余额|当前余额|余额)", text_value))
        kind = "cashflow"
        transfer_method = None
        cash_methods = [x for x in methods if (x.kind or "cash") == "cash"]
        liability_methods = [x for x in methods if x.kind == "liability"]
        investment_methods = [x for x in methods if x.kind == "investment"]
        mentioned_methods = [x for x in methods if x.name in text_value]
        mentioned_cash = [x for x in mentioned_methods if (x.kind or "cash") == "cash"]
        mentioned_liability = [x for x in mentioned_methods if x.kind == "liability"]
        mentioned_investment = [x for x in mentioned_methods if x.kind == "investment"]
        repayment_text = bool(re.search(r"(?:还|还款|还了).*(?:信用卡|花呗|白条|贷款|欠款)|(?:信用卡|花呗|白条|贷款|欠款).*还款", text_value))
        invest_in_text = bool(re.search(r"(?:买入|申购|购买|转入|投入).*(?:基金|股票|证券|理财|投资)", text_value))
        invest_out_text = bool(re.search(r"(?:赎回|卖出|转出|提现).*(?:基金|股票|证券|理财|投资)", text_value))
        if mode != "partner" and (repayment_text or invest_in_text or invest_out_text):
            if repayment_text:
                transfer_method = mentioned_liability[0] if mentioned_liability else (liability_methods[0] if len(liability_methods) == 1 else None)
                method = mentioned_cash[0] if mentioned_cash else (cash_methods[0] if len(cash_methods) == 1 else None)
            elif invest_in_text:
                transfer_method = mentioned_investment[0] if mentioned_investment else (investment_methods[0] if len(investment_methods) == 1 else None)
                method = mentioned_cash[0] if mentioned_cash else (cash_methods[0] if len(cash_methods) == 1 else None)
            elif invest_out_text:
                method = mentioned_investment[0] if mentioned_investment else (investment_methods[0] if len(investment_methods) == 1 else None)
                transfer_method = mentioned_cash[0] if mentioned_cash else (cash_methods[0] if len(cash_methods) == 1 else None)
            kind = "transfer"
            direction = "expense"
            category = None
        ledger_type = None
        inferred_supplier_recharge = False
        if mentions_refund:
            ledger_type = "refund" if partner_kind == "customer" else None
        elif partner_kind == "customer":
            if mentions_credit_limit:
                ledger_type = "limit_adjust"
            elif mentions_outstanding and (mentions_credit_repay or direction == "income"):
                ledger_type = "credit_repay"
            elif mentions_recharge or direction == "income":
                ledger_type = "prepaid_in"
        elif partner_kind == "supplier":
            if mentions_recharge:
                ledger_type = "prepaid_in"
            elif mentions_outstanding or "授信" in text_value:
                ledger_type = "balance_check" if observed_outstanding is not None and (amount is None or amount == observed_outstanding) else "credit_use"
        elif re.search(r"预存|充值", text_value):
            ledger_type = "prepaid_in"
        if ledger_type is None and (
            partner is not None
            and partner.kind == "supplier"
            and direction == "expense"
            and balance_after is not None
            and re.search(r"(?:扫了|付了|支付|转账|转给|打给).*(?:给|至|到).*(?:供应商|供货商)", text_value)
            and not partner_balance_context
        ):
            # A supplier payment followed by an observed account balance is
            # the common shorthand for a prepaid recharge. Treat it as a
            # proposal (never an automatic write) and surface the inference so
            # the confirmation card can be changed to a plain purchase.
            ledger_type = "prepaid_in"
            inferred_supplier_recharge = True
        elif ledger_type is None and re.search(r"授信.*还|还.*授信", text_value):
            ledger_type = "credit_repay"
        elif ledger_type is None and re.search(r"增加\s*授信|授信额度.*增加|增加.*授信", text_value):
            ledger_type = "limit_adjust"
        elif ledger_type is None and "授信" in text_value:
            ledger_type = "credit_use"
        elif ledger_type is None and mode == "partner" and balance_after is not None:
            # A periodic external balance report is an auditable observation,
            # not an inferred consumption/repayment. Persist it as a zero
            # movement so the current balance can be reconciled explicitly.
            ledger_type = "balance_check"
        if partner_balance_context:
            ledger_type = "balance_check"
            if balance_after is None:
                balance_after = observed_outstanding if observed_outstanding is not None else (observed_available if observed_available is not None else observed_limit)
        if mode == "partner":
            kind = "cashflow"
            transfer_method = None
            direction = None
            category = None
            method = None
            ledger_type = "balance_check"
            amount = None
        balance_kind = None
        if balance_after is not None and partner is not None:
            balance_kind = "prepaid_balance" if partner_kind == "supplier" else "credit_used"
        # In a current-account flow the source sentence is an instruction, not
        # a useful memo. Preserve only an explicitly marked note (e.g.
        # ``备注：八月用量``); cash-mode compatibility keeps the historical
        # full-sentence fallback when no note marker was supplied.
        explicit_note, note_value = _explicit_fallback_notes(text_value)
        ledger_amount = 0 if ledger_type == "balance_check" else (amount if ledger_type else None)
        parsed = AIParsedTransaction(
            occurred_at=_parse_time(text_value, reference),
            kind=kind,
            direction=direction,
            amount_cents=amount,
            category_id=category.id if category else None,
            category_name=category.name if category else None,
            payment_method_id=method.id if method else None,
            payment_method_name=method.name if method else None,
            transfer_payment_method_id=transfer_method.id if transfer_method else None,
            transfer_payment_method_name=transfer_method.name if transfer_method else None,
            partner_id=partner.id if partner else None,
            partner_name=partner.name if partner else None,
            partner_ledger_type=ledger_type,
            partner_ledger_amount_cents=ledger_amount,
            partner_balance_after_cents=balance_after,
            partner_balance_kind=balance_kind,
            notes=(note_value if explicit_note else (None if mode in {"partner", "combined"} and ledger_type else _fallback_notes(text_value))),
        )
        payload = parsed.model_dump()
        missing = _required_missing_fields(payload, mode)
        inferred = {"occurred_at"} if not self._has_explicit_time(text_value) else set()
        payload["field_status"] = _field_status(payload, missing, inferred)
        parsed = AIParsedTransaction.model_validate(payload)
        follow = ("请补充：" + "、".join({"direction": "收支方向", "amount_cents": "金额", "category": "分类", "payment_method": "来源账户", "transfer_payment_method": "转入/还款账户", "partner": "往来单位"}.get(x, x) for x in missing) + "。") if missing else None
        parse_warning = warning
        if inferred_supplier_recharge:
            extra = "已按供应商预存充值生成建议；如果这是普通采购，请取消往来变动后再确认。"
            parse_warning = f"{warning} {extra}" if warning else extra
        return AIParseResponse(status="need_more_info" if missing else "complete", mode=mode, parsed=parsed, missing_fields=missing, follow_up_question=follow, brief_comment=_default_brief_comment(parsed, mode), source="fallback", warning=parse_warning)

    @staticmethod
    def _has_explicit_time(text_value: str) -> bool:
        """Whether a user message contains a date or clock expression.

        ``deterministic_parse`` always fills ``occurred_at`` with the
        reference time, so a plain response cannot tell an inferred time from
        one the user actually typed.  This small lexical check lets a later
        follow-up such as “用微信” retain the explicit time from the first
        message instead of replacing it with the current reference.
        """

        return bool(
            re.search(
                r"(?:前天|昨天|今天|明天|20\d{2}[-年]\d{1,2}[-月]\d{1,2}|"
                r"(?:上午|早上|下午|晚上|中午)?\s*(?:[0-9]{1,2}|[零〇一二两三四五六七八九十百]+)\s*(?:[:：点时]))",
                text_value,
            )
        )

    def deterministic_parse_with_context(
        self,
        text_value: str,
        conversation: list[dict[str, str]],
        categories: list[Candidate],
        methods: list[Candidate],
        partners: list[Candidate],
        reference: datetime,
        warning: str | None = None,
        mode: str = "cash",
    ) -> AIParseResponse:
        """Parse a fallback multi-turn exchange without writing anything.

        A local rules parser has no model context window.  Parse each user
        turn independently, then fill fields missing from the current turn
        from the newest historical turn.  Assistant prompts are deliberately
        ignored because their labels and example numbers must never become
        ledger data.  The current turn wins whenever it contains a value.
        """

        history = [
            item.get("content", "").strip()[:MAX_INPUT_CHARS]
            for item in (conversation or [])[-MAX_CONVERSATION_MESSAGES:]
            if item.get("role") == "user"
            and isinstance(item.get("content"), str)
            and item.get("content", "").strip()
        ]
        # The public client normally sends only prior turns, but accepting a
        # repeated last user turn is harmless and avoids doubling its amount.
        if history and history[-1] == text_value:
            history.pop()
        turns = history + [text_value]
        responses = [
            self.deterministic_parse(
                turn, categories, methods, partners, reference, warning, mode
            )
            for turn in turns
        ]
        current = responses[-1]
        merged = current.parsed.model_dump()

        # IDs and their display names travel together.  Prefer the latest turn
        # but fill an omitted value from the newest earlier turn.
        fields = (
            "kind",
            "direction",
            "amount_cents",
            "category_id",
            "category_name",
            "payment_method_id",
            "payment_method_name",
            "transfer_payment_method_id",
            "transfer_payment_method_name",
            "partner_id",
            "partner_name",
            "partner_ledger_type",
            "partner_ledger_amount_cents",
            "partner_balance_after_cents",
            "partner_balance_kind",
        )
        for response in reversed(responses[:-1]):
            previous = response.parsed.model_dump()
            for field in fields:
                if merged.get(field) is None and previous.get(field) is not None:
                    merged[field] = previous[field]

        # An explicit note from any user turn outranks the generic source text
        # retained for compatibility.  This prevents a short follow-up such as
        # “用微信” from replacing “备注：招待客户” from the first turn.
        for turn in reversed(turns):
            explicit, note = _explicit_fallback_notes(turn)
            if explicit:
                merged["notes"] = note
                break

        # A fallback turn without a time expression gets the most recent
        # explicit historical time; otherwise keep the current reference time.
        if not self._has_explicit_time(text_value):
            for turn, response in reversed(list(zip(history, responses[:-1]))):
                if self._has_explicit_time(turn):
                    merged["occurred_at"] = response.parsed.occurred_at
                    break

        if mode == "partner":
            merged["kind"] = "cashflow"
            merged["direction"] = None
            merged["category_id"] = None
            merged["category_name"] = None
            merged["payment_method_id"] = None
            merged["payment_method_name"] = None
            merged["transfer_payment_method_id"] = None
            merged["transfer_payment_method_name"] = None
        elif merged.get("kind") == "transfer":
            merged["direction"] = "expense"
            merged["category_id"] = None
            merged["category_name"] = None
            merged["partner_ledger_type"] = None
            merged["partner_ledger_amount_cents"] = None
        # Recompute required fields after merging, rather than carrying the
        # first turn's stale provider/rules metadata into the confirmation
        # card.  A partner is required only for an actual ledger movement.
        missing = _required_missing_fields(merged, mode)
        has_explicit_time = any(self._has_explicit_time(turn) for turn in turns)
        inferred = set() if has_explicit_time else {"occurred_at"}
        merged["field_status"] = _field_status(merged, missing, inferred)
        parsed = AIParsedTransaction.model_validate(merged)
        follow = (
            "请补充："
            + "、".join(
                {
                    "direction": "收支方向",
                    "amount_cents": "金额",
                    "category": "分类",
                    "payment_method": "来源账户",
                    "transfer_payment_method": "转入/还款账户",
                    "partner": "往来单位",
                }.get(field, field)
                for field in missing
            )
            + "。"
            if missing
            else None
        )
        return AIParseResponse(
            status="need_more_info" if missing else "complete",
            mode=mode,
            parsed=parsed,
            missing_fields=missing,
            follow_up_question=follow,
            brief_comment=_default_brief_comment(parsed, mode),
            source="fallback",
            # ``deterministic_parse`` may add a mode-specific inference note
            # (for example, a supplier payment that looks like a recharge).
            # Preserve that note while merging multi-turn context instead of
            # replacing it with the generic AI-unavailable warning.
            warning=current.warning or warning,
        )

    def parse(self, db: Session, user_id: int, text_value: str, conversation: list[dict[str, str]] | None = None, reference_time: datetime | None = None, mode: str = "cash", on_event: Callable[[dict[str, Any]], None] | None = None) -> AIParseResponse:
        """Parse a bookkeeping message into a proposal.

        ``on_event`` receives progress events while the model works:
        ``provider`` when a channel is tried, ``start`` for each request to
        it, ``reasoning``/``content`` text deltas and ``status`` notes.
        """

        if mode not in {"cash", "partner", "combined"}:
            mode = "cash"
        emit = on_event or (lambda event: None)

        def on_delta(kind: str, text_delta: str) -> None:
            emit({"type": kind, "text": text_delta})
        text_value = text_value.strip()[:MAX_INPUT_CHARS]
        # Normalize the client-provided instant first (naive values retain the
        # legacy UTC interpretation), then derive a Beijing reference for
        # relative-language parsing.  Both represent the same instant.
        reference_utc = to_utc(reference_time) if reference_time is not None else now_utc()
        reference = to_business(reference_utc)
        categories, methods, partners = self.candidates(db, user_id)
        providers = self.provider_chain_for_user(db, user_id)
        options = {"categories": [x.__dict__ for x in categories], "payment_methods": [x.__dict__ for x in methods], "partners": [x.__dict__ for x in partners]}
        system = (
            "你是 PennyPilot 记账解析器。必须只输出一个严格 JSON envelope（json object，合法 JSON 对象），"
            "所有键名和字符串值必须使用双引号。"
            "不要 Markdown、代码围栏、解释或 envelope 之外的键。JSON 结构必须是："
            '{"status":"need_more_info","parsed":{"occurred_at":null,"kind":"cashflow","direction":null,'
            '"amount_cents":null,"account_balance_cents":null,"category_id":null,"category_name":null,'
            '"payment_method_id":null,"payment_method_name":null,'
            '"transfer_payment_method_id":null,"transfer_payment_method_name":null,'
            '"partner_id":null,'
            '"partner_name":null,"partner_ledger_type":null,'
            '"partner_ledger_amount_cents":null,"partner_balance_after_cents":null,'
            '"partner_balance_kind":null,"notes":null,"field_status":{"occurred_at":"inferred",'
            '"direction":"missing","amount_cents":"missing","category":"missing",'
            '"payment_method":"missing","transfer_payment_method":"missing","partner":"missing"}},'
            '"missing_fields":["direction","amount_cents","payment_method"],"follow_up_question":"请补充信息",'
            '"brief_comment":"一句话简评","extra_records":[]}。'
            "status 仅允许 complete 或 need_more_info。kind 仅允许 cashflow、transfer 或 balance_check；direction 仅允许 income 或 expense；"
            "amount_cents 必须是整数分。field_status 的键仅使用 occurred_at、direction、"
            "amount_cents、category、payment_method、transfer_payment_method、partner，值仅允许 explicit、inferred、missing，"
            "禁止 confirmed、known、present 等其他值。missing_fields 中仅允许 direction、"
            "amount_cents、category、payment_method、transfer_payment_method、partner；基础必填为 direction、amount_cents、"
            "payment_method；kind=transfer 时不需要 category，但必须填写 payment_method_id 作为来源账户、transfer_payment_method_id 作为目标账户。kind=cashflow 时必须填写 category。partner 仅在明确输出 partner_ledger_type 且无法确定往来账户时才缺失；"
            "普通交易的 partner 可为 null。若用户未说明发生时间，occurred_at 使用下面的 reference_time，"
            "field_status 标为 inferred，不得把 occurred_at 列入 missing_fields；今天/昨天等相对日期也以"
            f"该时间为准。reference_time={reference_utc.isoformat()}。"
            f"business_reference_time={reference.isoformat()}。business_timezone={BUSINESS_TIMEZONE_NAME}（UTC+8）。"
            "notes 要从用户整句自然语言中提取有实际信息的简短备注，例如消费项目、收付款原因、用途、对方说明或业务背景；"
            "不要求用户使用‘备注/说明/用途’等关键词。例如‘微信35元吃了碗牛肉面’应提取 notes=‘牛肉面’，"
            "‘支付宝收到客户大黄鹅结算款一万元’可提取与结算款相关的有效说明。不要把完整原句、金额、日期、账户或分类重复写入 notes。"
            "商品或项目自带的数量词和单位（如‘两颗’‘三箱’‘一份’）是备注内容的一部分，必须原样保留在 notes 中，"
            "不得当作金额删除：例如‘花5块买了两颗卤蛋’应提取 notes=‘两颗卤蛋’，不能只写‘卤蛋’。"
            "如果原话没有可提取的有效项目、原因、用途或背景，notes 返回 null，不要猜测或编造；notes=null 不属于必填缺失字段。"
            "当前往来账户只记录一项：当前未结算余额。partner 模式只允许 balance_check，"
            "partner_ledger_amount_cents 固定为 0，partner_balance_after_cents 填当前未结算余额；"
            "不要输出 prepaid_in、prepaid_out、credit_use、credit_repay、limit_adjust、refund 等旧流水类型，"
            "也不要把 supplier 或 customer 当作流水类型。"
            "分类、支付方式和往来账户应优先使用下面候选项的 id 与 name。"
            "不可确定的必填字段填 null，并使用规范业务键列入 missing_fields。可选项如下："
            + "多轮对话规则：conversation 与当前消息共同描述同一批尚未确认的记录（通常是一笔，也可能是多笔），必须综合所有 user 消息输出一份字段齐全的最新草稿，不能只解析最后一句；后续省略的字段沿用此前用户已明确的信息，后续明确重述、纠正、否定或删除的字段以最新 user 消息为准。assistant 消息只可能是追问或简评，绝不能把 assistant 消息中的金额、日期、账户、分类或示例当作账务事实。若用户在新消息中明确说‘新的一笔’‘另记一笔’来另起一张记录，只解析该标记之后的新记录，不得混入此前消息里的记录。"
            + "多笔记录规则：一条消息里可能包含多笔相互独立的记录，例如一连串消费‘早餐微信12元，午饭支付宝35元，打车花呗28元’，或用‘还有’‘另外’‘然后’连接的几笔收支。此时第一笔写入 parsed，其余按用户描述的顺序逐笔写入 extra_records 数组；extra_records 的每个元素只包含 " + "、".join(_AI_PARSE_EXTRA_RECORD_KEYS) + " 这几个键，含义与 parsed 中的同名字段一致，分类、账户和往来单位直接填写候选项的 name 原文，不要输出 id 和 field_status；每笔都有各自的金额、分类、账户、时间和备注，金额不得相加或合并，最多 " + str(MAX_PARSE_RECORDS) + " 笔。只有一笔记录时 extra_records 必须是空数组 []。用户没有逐笔重复、但显然共用的信息（如同一天、同一个支付账户）要填入每一笔。missing_fields 与 follow_up_question 只针对 parsed，extra_records 中无法确定的必填字段填 null 即可。此前草稿已包含多笔时，后续消息只补充或修改其中某几笔（如‘第二笔是支付宝’），必须重新输出全部记录的最新草稿并保持原有顺序。一笔现金收支及其对应的往来未结算余额仍是同一条记录，必须都写在 parsed 中，不得拆成两笔。"
            + "抵扣规则：还款或转账时使用了还款券、立减金、红包等抵扣，抵扣部分并没有从来源账户实际扣除，必须拆成两笔：parsed 为 kind=transfer 的还款，amount_cents 是包含抵扣在内的还款总额，来源账户转入被还款的账户；extra_records 再加一笔 kind=cashflow、direction=income，amount_cents 是抵扣金额，payment_method 与还款来源账户相同，分类优先‘其他收入’，notes 写明如‘还款券抵扣’。例如‘招行储蓄卡还信用卡2000元，用了一张50元还款券’应输出 transfer amount_cents=200000（招行储蓄卡转入信用卡）和 income amount_cents=5000（招行储蓄卡，其他收入，notes=还款券抵扣）。若用户给出的是实际扣款金额，则还款总额=实际扣款+抵扣金额。"
            + "brief_comment 必须根据合并后的本次记录写一句自然、具体、不过度评价的中文简评，建议不超过 80 个汉字；可以提示这笔记录会影响现金、负债、投资或未结算余额中的哪些账，但不得编造用户未提供的事实。若 notes=null，必须在 brief_comment 中顺带礼貌询问用户补充这笔收付款的用途、项目或原因；不要因此把记录改成 need_more_info，也不要把 notes 加入 missing_fields。brief_comment 不得代替真正缺失必填字段时的 follow_up_question。"
            + f"当前模式={mode}。cash 只输出现金收支；partner 只输出未结算余额，不需要 direction/category/payment_method；combined 用于统一对话：有现金就输出现金字段，有往来就输出 partner_balance 字段，只有往来变化时现金字段可以全部为 null，同时包含两者时两组字段都输出；现金动作和往来余额盘点必须分开解析，即使金额相同也不能合并或丢弃其中一组。例如‘支付宝给供应商A充值1000元，目前未结算余额1000元’应同时输出现金 expense/amount_cents=100000/payment_method_name=支付宝（分类优先其他支出），以及 partner_ledger_type=balance_check/partner_ledger_amount_cents=0/partner_balance_after_cents=100000/partner_balance_kind=prepaid_balance。所有结果都必须由用户明确确认。"
            + "payment_methods 的 kind 是账户性质：cash=现金账户，liability=信用卡/花呗/白条/贷款等负债账户，investment=投资账户。京东白条、花呗、信用卡、借呗等属于 payment_method，不是 partner。"
            + "partner_balance_after_cents 表示往来当前未结算余额，客户和供应商都只记录这一项。partner_ledger_type 是流水操作类型，不是客户/供应商类型；只要记录当前未结算余额，就必须输出 partner_ledger_type=balance_check，绝不能输出 supplier 或 customer。partner_balance_kind 也不是客户/供应商类型：供应商固定使用 prepaid_balance，客户固定使用 credit_used；绝不能输出 balance_check、supplier 或 customer。"
            + "常用省略表达也必须按完整业务语义解析：如果句首名称能匹配 partners 中的客户，后面紧接支付方式和‘转账/付款/打款+金额’，例如‘客户A支付宝转账一万’，表示该客户通过该支付方式向用户付款；应输出现金收入、对应支付账户、金额（中文数词和万/千等单位要换算成整数分），分类优先匹配‘其他收入’，并关联该客户。若已匹配客户或供应商，原话中的‘已结清’‘结清了’‘已清账’表示该往来账户当前未结算余额为 0；必须同时输出 partner_ledger_type=balance_check、partner_ledger_amount_cents=0、partner_balance_after_cents=0，并按账户类型填写 partner_balance_kind。若同一句还包含现金收付款，必须保留现金与往来两组字段，不能因余额为 0 就省略往来字段。"
            + "候选项中的 payment_method.current_balance_cents 是系统当前账户余额（仅作核对，不要把它当成用户本次金额），每个资金账户都会自动维护余额，liability 账户的余额表示当前欠款。partners 中 unsettled_balance_cents 是当前未结算余额，优先用 partner_id 精确匹配同名账户。若用户只说‘支出/消费’且没有更具体用途，优先选择候选分类‘其他支出’；余额校准规则：用户报告某个资金账户此刻的余额而没有描述收支动作，例如‘支付宝现在余额2345.67’‘校准一下微信余额，实际有103.01元’‘工商银行卡里有5000元’‘信用卡目前欠款3000’，输出 kind=balance_check，payment_method 为该账户，account_balance_cents 为用户报告的余额（负债账户填当前欠款），direction、amount_cents、category 都为 null；系统会用它和当前余额的差额生成校准流水，不要自己计算差额，也不要把余额当成一笔收入或支出。balance_check 只用于 payment_methods 里的资金账户；客户、供应商等往来单位的未结算余额不是 balance_check，仍按往来规则输出 kind=cashflow、partner_ledger_type=balance_check 和 partner_balance_after_cents，即使该往来单位不在候选项里也要把名字写进 partner_name。"
            + json.dumps(options, ensure_ascii=False)
        )
        messages = [{"role": "system", "content": system}]
        for item in (conversation or [])[-MAX_CONVERSATION_MESSAGES:]:
            if item.get("role") in {"user", "assistant"} and isinstance(item.get("content"), str):
                messages.append({"role": item["role"], "content": item["content"][:MAX_INPUT_CHARS]})
        messages.append({"role": "user", "content": text_value})

        last_error: AIServiceError | None = None
        request_id = uuid.uuid4().hex[:12]
        input_fingerprint = hashlib.sha256(text_value.encode("utf-8")).hexdigest()[:12]
        logger.debug(
            "AI parse started id=%s mode=%s input_chars=%d input_fingerprint=%s conversation_messages=%d providers=%d",
            request_id,
            mode,
            len(text_value),
            input_fingerprint,
            len(conversation or []),
            len(providers),
        )
        for index, provider in enumerate(providers):
            emit({"type": "provider", "name": provider.name, "model": provider.model})
            try:
                raw = self._json_content(
                    self._chat(
                        provider,
                        messages,
                        max_tokens=AI_PARSE_MAX_TOKENS,
                        response_format=AI_PARSE_RESPONSE_FORMAT,
                        request_id=request_id,
                        on_delta=on_delta,
                    )
                )
                response = self._complete_parse(raw, categories, methods, partners, reference, mode)
                if self._needs_model_recheck(response):
                    logger.debug(
                        "AI parse self-check requested id=%s provider=%s model=%s missing=%s",
                        request_id,
                        provider.name,
                        provider.model,
                        response.missing_fields,
                    )
                    review_messages = messages + [
                        {"role": "assistant", "content": json.dumps(raw, ensure_ascii=False)},
                        {
                            "role": "user",
                            "content": (
                                "上一份 JSON 的 parsed 草稿为空，但 brief_comment 显示你已读到用户原话中的实体。"
                                "请重新解析最初那条用户消息，严格遵守 system 中的常用省略表达规则，"
                                "把已经明确的方向、金额、账户、往来单位和结清后余额写入 parsed；"
                                "不要因自然语言省略主语或余额为零就把明确字段留空。只输出修正后的 JSON。"
                            ),
                        },
                    ]
                    emit({"type": "status", "code": "self_check"})
                    try:
                        revised_raw = self._json_content(
                            self._chat(
                                provider,
                                review_messages,
                                max_tokens=AI_PARSE_MAX_TOKENS,
                                response_format=AI_PARSE_RESPONSE_FORMAT,
                                request_id=request_id,
                                on_delta=on_delta,
                            )
                        )
                        revised_response = self._complete_parse(
                            revised_raw, categories, methods, partners, reference, mode
                        )
                        if self._proposal_information_score(revised_response) > self._proposal_information_score(response):
                            raw, response = revised_raw, revised_response
                        logger.debug(
                            "AI parse self-check completed id=%s provider=%s model=%s accepted=%s status=%s missing=%s",
                            request_id,
                            provider.name,
                            provider.model,
                            raw is revised_raw,
                            response.status,
                            response.missing_fields,
                        )
                    except AIServiceError as exc:
                        logger.warning(
                            "AI parse self-check failed id=%s provider=%s model=%s code=%s; keeping first valid response",
                            request_id,
                            provider.name,
                            provider.model,
                            exc.code,
                        )
                logger.debug(
                    "AI parse completed id=%s provider=%s model=%s status=%s source=%s top_level_keys=%s parsed_keys=%s",
                    request_id,
                    provider.name,
                    provider.model,
                    response.status,
                    response.source,
                    sorted(raw.keys()),
                    sorted((raw.get("parsed") or {}).keys()) if isinstance(raw.get("parsed"), dict) else [],
                )
                if index > 0:
                    fallback_warning = "AI 主通道暂不可用，已切换备用通道。"
                    response.warning = f"{fallback_warning} {response.warning}".strip() if response.warning else fallback_warning
                return response
            except AIServiceError as exc:
                last_error = exc
                # Keep diagnostics useful without writing the user's natural
                # language (which may contain financial or personal data) or
                # any provider credential to the application log.
                logger.warning(
                    "AI parse provider failed provider=%s model=%s mode=%s code=%s input_chars=%d",
                    provider.name,
                    provider.model,
                    mode,
                    exc.code,
                    len(text_value),
                )
                logger.debug(
                    "AI parse failed details id=%s provider=%s model=%s last_error=%s",
                    request_id,
                    provider.name,
                    provider.model,
                    exc.code,
                )
            except Exception as exc:
                last_error = AIServiceError("provider_invalid_response")
                logger.exception(
                    "AI parse provider returned an unexpected response provider=%s model=%s mode=%s input_chars=%d",
                    provider.name,
                    provider.model,
                    mode,
                    len(text_value),
                )
                if not self.settings.ai_local_fallback:
                    raise last_error from exc
            if index + 1 < len(providers):
                emit({"type": "status", "code": "provider_failed"})
                continue
            if self.settings.ai_local_fallback:
                emit({"type": "status", "code": "local_fallback"})
                warning = "AI 主通道和备用通道均不可用，已使用本地规则解析。" if len(providers) > 1 else ("AI 服务暂不可用，已使用本地规则解析。" if provider.api_key else "未配置 AI 服务，已使用本地规则解析。")
                return self.deterministic_parse_with_context(text_value, conversation or [], categories, methods, partners, reference, warning, mode)
            raise last_error or AIServiceError("provider_unavailable")

    def aggregate(self, db: Session, user_id: int, start: datetime, end: datetime) -> dict[str, Any]:
        # Callers provide UTC query bounds (normally converted from Beijing
        # calendar dates by ``app.ai``).  Normalize direct/internal callers as
        # well so SQLite's naive round-trip cannot change the boundary.
        start = to_utc(start)
        end = to_utc(end)
        rows = db.execute(
            select(Transaction, Category.name)
            .join(Category, Transaction.category_id == Category.id)
            .where(
                Transaction.user_id == user_id,
                Transaction.status == "normal",
                Transaction.kind == "cashflow",
                Transaction.occurred_at >= start,
                Transaction.occurred_at < end,
            )
            .order_by(Transaction.occurred_at)
            .limit(5000)
        ).all()
        income = sum(x.amount_cents for x, _ in rows if x.direction == "income")
        expense = sum(x.amount_cents for x, _ in rows if x.direction == "expense")
        by_category: dict[str, dict[str, int]] = {}
        by_day: dict[str, dict[str, int]] = {}
        for tx, category_name in rows:
            bucket = by_category.setdefault(category_name, {"income_cents": 0, "expense_cents": 0, "count": 0})
            bucket["count"] += 1
            bucket["income_cents" if tx.direction == "income" else "expense_cents"] += tx.amount_cents
            # Stored timestamps are UTC instants; reporting buckets are
            # Beijing calendar dates so transactions around 00:00 do not fall
            # into the previous day's report.
            day = to_business(tx.occurred_at).date().isoformat()
            daily = by_day.setdefault(day, {"income_cents": 0, "expense_cents": 0, "count": 0})
            daily["count"] += 1
            daily["income_cents" if tx.direction == "income" else "expense_cents"] += tx.amount_cents
        # Include a bounded current-account snapshot so both the model and the
        # deterministic report can flag credit concentration or depleted
        # supplier prepayments.  The query is optional for compatibility with
        # a pre-partner database; a missing table simply yields an empty list.
        partner_health: list[dict[str, Any]] = []
        movements: dict[int, dict[str, int]] = {}
        try:
            partners = db.scalars(
                select(Partner)
                .where(Partner.user_id == user_id)
                .order_by(Partner.status, Partner.id)
                .limit(500)
            ).all()
            ledger_rows = db.execute(
                select(
                    PartnerLedgerEntry.partner_id,
                    PartnerLedgerEntry.amount_cents,
                )
                .where(
                    PartnerLedgerEntry.user_id == user_id,
                    PartnerLedgerEntry.status == "normal",
                    PartnerLedgerEntry.occurred_at >= start,
                    PartnerLedgerEntry.occurred_at < end,
                )
                .limit(5000)
            ).all()
            for partner_id, amount_cents in ledger_rows:
                bucket = movements.setdefault(int(partner_id), {"count": 0, "amount_cents": 0})
                bucket["count"] += 1
                bucket["amount_cents"] += abs(int(amount_cents or 0))
            for partner in partners:
                limit = int(partner.credit_limit_cents or 0)
                used = int(partner.credit_used_cents or 0)
                movement = movements.get(partner.id, {"count": 0, "amount_cents": 0})
                partner_health.append(
                    {
                        "id": partner.id,
                        "name": partner.name,
                        "type": partner.type,
                        "status": partner.status,
                        "prepaid_balance_cents": int(partner.prepaid_balance_cents or 0),
                        "credit_limit_cents": limit,
                        "credit_used_cents": used,
                        "credit_remaining_cents": max(limit - used, 0),
                        "period_ledger_count": movement["count"],
                        "period_ledger_amount_cents": movement["amount_cents"],
                    }
                )
        except SQLAlchemyError:
            db.rollback()
            partner_health = []
        return {
            "transaction_count": len(rows),
            "income_cents": income,
            "expense_cents": expense,
            "net_cents": income - expense,
            "categories": by_category,
            "daily": by_day,
            "partner_count": len(partner_health),
            "partner_health": partner_health,
        }

    @staticmethod
    def fallback_report(summary: dict[str, Any], start: date, end: date) -> str:
        income, expense, net = summary["income_cents"], summary["expense_cents"], summary["net_cents"]
        top = sorted(summary["categories"].items(), key=lambda item: item[1]["expense_cents"] + item[1]["income_cents"], reverse=True)[:3]
        lines = [f"分析区间：{start.isoformat()} 至 {end.isoformat()}", f"共 {summary['transaction_count']} 笔，收入 {income / 100:.2f} 元，支出 {expense / 100:.2f} 元，净收支 {net / 100:.2f} 元。"]
        if top:
            lines.append("主要分类：" + "；".join(f"{name} {((data['income_cents'] + data['expense_cents']) / 100):.2f} 元" for name, data in top) + "。")
        partner_risks = []
        for partner in summary.get("partner_health", []):
            limit = partner.get("credit_limit_cents", 0) or 0
            used = partner.get("credit_used_cents", 0) or 0
            if limit and used / limit >= 0.8:
                partner_risks.append(f"{partner.get('name', '往来单位')}授信占用已达 {used / limit:.0%}")
            elif partner.get("type") == "supplier" and partner.get("prepaid_balance_cents", 0) <= 0:
                partner_risks.append(f"{partner.get('name', '供应商')}预存余额已用尽")
        if partner_risks:
            lines.append("往来提醒：" + "；".join(partner_risks[:3]) + "。")
        if net < 0:
            lines.append("提醒：本区间支出高于收入，建议检查大额支出并预留现金流。")
        elif summary["transaction_count"] == 0:
            lines.append("提醒：该区间暂无正常交易记录。")
        else:
            lines.append("建议：继续按分类记录，并定期核对支付方式余额。")
        return "\n".join(lines)

    def analyze_text(self, db: Session, user_id: int, summary: dict[str, Any], start: date, end: date) -> tuple[str, str | None, str | None, str | None]:
        providers = self.provider_chain_for_user(db, user_id)
        prompt = "你是专业财务分析师。基于下面仅包含聚合金额的 JSON，用中文输出不超过 3000 字的收支趋势、结构、异常和可执行建议。不要编造数据，不要输出 JSON 以外的敏感信息。\n" + json.dumps({"period": [start.isoformat(), end.isoformat()], "summary": summary}, ensure_ascii=False)
        last_error: AIServiceError | None = None
        for index, provider in enumerate(providers):
            try:
                content = self._chat(provider, [{"role": "system", "content": "只分析用户提供的数据。"}, {"role": "user", "content": prompt}], max_bytes=min(self.settings.ai_max_response_bytes, MAX_REPORT_CHARS * 2), max_tokens=ANALYSIS_MAX_TOKENS, effort="high")
                warning = "AI 主通道暂不可用，已切换备用通道。" if index > 0 else None
                return content, "model", warning, provider.model
            except AIServiceError as exc:
                last_error = exc
            if index + 1 < len(providers):
                continue
            warning = "AI 主通道和备用通道均不可用，已生成本地分析。" if len(providers) > 1 else ("未配置 AI 服务，已生成本地分析。" if last_error and last_error.code == "not_configured" else "AI 服务暂不可用，已生成本地分析。")
            return self.fallback_report(summary, start, end), "fallback", warning, None


    def chat_reply(
        self,
        db: Session,
        user_id: int,
        text_value: str,
        conversation: list[dict[str, str]] | None,
        summary: dict[str, Any],
        intent: str,
    ) -> tuple[str, str, str | None, str | None]:
        """Answer a ledger question or write a report from aggregated figures.

        The model only ever sees aggregated numbers, category names and the
        short notes of the largest transactions; it never receives raw rows or
        provider credentials.  Returns ``(content, source, warning, model)``
        and falls back to the deterministic text when no provider answers.
        """

        from .ai_insights import fallback_answer, fallback_report

        providers = self.provider_chain_for_user(db, user_id)
        period = summary.get("period", {})
        label = period.get("label", "该周期")
        today = to_business(now_utc()).date().isoformat()
        common = (
            "你是 PennyPilot 记账应用的财务助手，只根据下面提供的聚合数据回答用户关于账本的问题。"
            f"当前北京日期是 {today}。数据周期：{label}"
            f"（{period.get('start_date') or '最早记录'} 至 {period.get('end_date')}）。"
            + ("数据范围已限定为：" + "，".join(f"{key}={value}" for key, value in summary["scope"].items()) + "；回答和报告都要说明这个范围。" if summary.get("scope") else "")
            + "所有金额字段以“分”为单位（*_cents），回答时必须换算成元并保留两位小数，例如 123456 分 = 1,234.56 元。"
            "share 是占比（0-1 之间的小数），请以百分比表达。previous/change 表示与上一周期的对比；"
            "days_elapsed 小于 days_total 说明本周期尚未结束，做对比时要说明这一点。"
            "不要编造数据中没有的数字或交易；数据为空时如实说明没有记录。"
            "输出纯文本，不要使用 Markdown 标记（如 #、*、|、```），可以用换行和“•”列表。"
        )
        if intent == "report":
            instruction = (
                "用户要求生成一份收支报告。请输出结构化的中文报告，按顺序包含：总览（笔数、收入、支出、净收支）、"
                "收入结构、支出结构（含占比）、趋势或对比（有 daily/monthly/previous 数据时）、大额支出、2-3 条可执行建议。"
                "标题用“【周期 收支报告】”形式，各部分用短标题分段，总长度不超过 1200 字。"
            )
        else:
            instruction = (
                "用户在询问账本情况。请用简洁、自然的中文直接回答问题，优先给出与问题最相关的数字，"
                "必要时补充 1-2 句有价值的观察（如占比最高的分类、与上期的变化）。回答不超过 300 字，不要输出报告格式。"
            )
        system = common + instruction + "\n聚合数据：" + json.dumps(summary, ensure_ascii=False)
        messages = [{"role": "system", "content": system}]
        for item in (conversation or [])[-MAX_CONVERSATION_MESSAGES:]:
            if item.get("role") in {"user", "assistant"} and isinstance(item.get("content"), str) and item["content"].strip():
                messages.append({"role": item["role"], "content": item["content"][:MAX_INPUT_CHARS]})
        messages.append({"role": "user", "content": text_value[:MAX_INPUT_CHARS]})
        last_error: AIServiceError | None = None
        request_id = uuid.uuid4().hex[:12]
        for index, provider in enumerate(providers):
            try:
                content = self._chat(
                    provider,
                    messages,
                    max_bytes=min(self.settings.ai_max_response_bytes, MAX_REPORT_CHARS * 2),
                    max_tokens=ANALYSIS_MAX_TOKENS,
                    request_id=request_id,
                    effort="high",
                )
                warning = "AI 主通道暂不可用，已切换备用通道。" if index > 0 else None
                return content[:MAX_REPORT_CHARS], "model", warning, provider.model
            except AIServiceError as exc:
                last_error = exc
                logger.warning(
                    "AI chat provider failed provider=%s model=%s intent=%s code=%s",
                    provider.name,
                    provider.model,
                    intent,
                    exc.code,
                )
            if index + 1 < len(providers):
                continue
            if last_error and last_error.code == "not_configured" and len(providers) == 1:
                warning = "未配置 AI 服务，已根据账本数据生成本地回答。"
            elif len(providers) > 1:
                warning = "AI 主通道和备用通道均不可用，已根据账本数据生成本地回答。"
            else:
                warning = "AI 服务暂不可用，已根据账本数据生成本地回答。"
            content = fallback_report(summary) if intent == "report" else fallback_answer(summary)
            return content, "fallback", warning, None
        raise AIServiceError("provider_unavailable")
