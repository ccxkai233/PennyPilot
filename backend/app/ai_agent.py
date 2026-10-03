"""Tool-using ledger assistant for the transactions page.

The model is given a small set of read-only query tools and decides which
to call; every tool is scoped to the current user and returns bounded JSON.
The loop runs one non-streaming model call per round in the channel's own
wire format (OpenAI, Anthropic or Gemini) and reports each tool call through
``emit`` so the client can show progress.  Nothing here writes to the ledger.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
import logging
import time
from typing import Any, Callable
from urllib.parse import quote

import anthropic
import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from dataclasses import dataclass, field

from .ai_insights import SCOPE_KEYS, PeriodSpec, fallback_answer, fallback_report, parse_period_text, resolve_period, summarize_period
from .ai_service import (
    AI_STREAM_IDLE_TIMEOUT_SECONDS,
    ANALYSIS_MAX_TOKENS,
    MAX_CONVERSATION_MESSAGES,
    MAX_INPUT_CHARS,
    AIService,
    AIServiceError,
    Provider,
    _api_root,
    _conversation_turns,
    _schema_without,
    completion_endpoint,
    reasoning_controls_for_provider,
)
from .models import Category, PaymentMethod, Transaction
from .partner_models import Partner
from .timezone import BUSINESS_TZ, business_day_start_utc, business_today, to_business

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 6
MAX_LIST_ROWS = 100
AGENT_TOTAL_TIMEOUT_SECONDS = 150.0
# One tool result is capped so a wide query cannot blow up the next prompt.
MAX_TOOL_RESULT_CHARS = 20_000

_PERIOD_KINDS = ["day", "week", "month", "year", "all", "custom"]
_SCOPE_PROPERTIES: dict[str, Any] = {
    "payment_method_id": {"type": "integer", "description": "资金账户 id，只统计该账户"},
    "category_id": {"type": "integer", "description": "分类 id，只统计该分类"},
    "partner_id": {"type": "integer", "description": "往来单位 id，只统计关联该单位的流水"},
    "direction": {"type": "string", "enum": ["income", "expense"], "description": "只看收入或只看支出"},
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "summarize_period",
        "description": "统计一个时间段的收支汇总：笔数、收入、支出、净收支、分类排名、按日/按月分布、最大几笔、与上一周期的对比。回答“花了多少”“哪类最多”“和上月比”这类问题先用它。",
        "parameters": {
            "type": "object",
            "properties": {
                "period": {"type": "string", "enum": _PERIOD_KINDS, "description": "day/week/month/year 以 start_date 为锚点（默认今天）；custom 需要 start_date 和 end_date；all 为全部历史"},
                "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "YYYY-MM-DD"},
                **_SCOPE_PROPERTIES,
            },
            "required": ["period"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_transactions",
        "description": "按条件列出具体流水（最多 100 条，按时间倒序），用于找某几笔、看明细、按关键词搜索备注。",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "YYYY-MM-DD，含当天"},
                "end_date": {"type": "string", "description": "YYYY-MM-DD，含当天"},
                "keyword": {"type": "string", "description": "备注包含的关键词"},
                "min_amount_cents": {"type": "integer", "description": "金额下限（分）"},
                "max_amount_cents": {"type": "integer", "description": "金额上限（分）"},
                "kind": {"type": "string", "enum": ["cashflow", "transfer"], "description": "cashflow 为收支，transfer 为账户间转账/还款"},
                "limit": {"type": "integer", "description": "返回条数，默认 30，最多 100"},
                **_SCOPE_PROPERTIES,
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "propose_update",
        "description": "提出修改某一笔流水的方案（金额、时间、分类、账户、转入账户、往来单位、备注）。只生成方案，用户在页面上确认后才会执行。先用 list_transactions 找到 transaction_id。",
        "parameters": {
            "type": "object",
            "properties": {
                "transaction_id": {"type": "integer", "description": "要修改的流水 id"},
                "amount_cents": {"type": "integer", "description": "新金额（分）"},
                "occurred_at": {"type": "string", "description": "新的发生时间，北京时间 YYYY-MM-DD HH:MM 或 YYYY-MM-DD"},
                "direction": {"type": "string", "enum": ["income", "expense"], "description": "新的收支方向（仅 cashflow）"},
                "category_id": {"type": "integer", "description": "新分类 id（仅 cashflow）"},
                "payment_method_id": {"type": "integer", "description": "新账户 id（transfer 时为来源账户）"},
                "transfer_payment_method_id": {"type": "integer", "description": "新转入/还款账户 id（仅 transfer）"},
                "partner_id": {"type": "integer", "description": "新关联往来单位 id，0 表示取消关联"},
                "notes": {"type": "string", "description": "新备注"},
                "reason": {"type": "string", "description": "一句话说明为什么这样改"},
            },
            "required": ["transaction_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "propose_void",
        "description": "提出作废某一笔流水的方案（记错、重复等）。只生成方案，用户确认后才执行。",
        "parameters": {
            "type": "object",
            "properties": {
                "transaction_id": {"type": "integer", "description": "要作废的流水 id"},
                "reason": {"type": "string", "description": "作废原因"},
            },
            "required": ["transaction_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "propose_create",
        "description": "提出补记一笔流水的方案（漏记的收支或转账）。只生成方案，用户确认后才执行。",
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["cashflow", "transfer"], "description": "cashflow 为收支，transfer 为账户间转账/还款"},
                "direction": {"type": "string", "enum": ["income", "expense"], "description": "收支方向（cashflow 必填）"},
                "amount_cents": {"type": "integer", "description": "金额（分）"},
                "occurred_at": {"type": "string", "description": "发生时间，北京时间 YYYY-MM-DD HH:MM 或 YYYY-MM-DD；不填为现在"},
                "category_id": {"type": "integer", "description": "分类 id（cashflow 必填）"},
                "payment_method_id": {"type": "integer", "description": "账户 id（transfer 时为来源账户）"},
                "transfer_payment_method_id": {"type": "integer", "description": "转入/还款账户 id（transfer 必填）"},
                "partner_id": {"type": "integer", "description": "关联往来单位 id"},
                "notes": {"type": "string", "description": "备注"},
                "reason": {"type": "string", "description": "一句话说明为什么补记"},
            },
            "required": ["kind", "amount_cents", "payment_method_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_accounts",
        "description": "列出资金账户及当前余额（负债账户的余额表示欠款）。",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "list_partners",
        "description": "列出客户/供应商及其当前未结算余额。",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


@dataclass
class AgentResult:
    content: str
    source: str
    warning: str | None
    model: str | None
    steps: list[dict[str, str]]
    # The period of the first summary the model asked for; reports are filed under it.
    period: PeriodSpec | None
    proposals: list[dict[str, Any]] = field(default_factory=list)


class LedgerTools:
    """Read-only, user-scoped implementations of the tools above."""

    def __init__(self, db: Session, user_id: int):
        self.db = db
        self.user_id = user_id
        self.last_period: PeriodSpec | None = None
        # Change proposals the model made this turn; nothing is written here.
        self.proposals: list[dict[str, Any]] = []

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handler = {
            "summarize_period": self.summarize_period,
            "list_transactions": self.list_transactions,
            "list_accounts": self.list_accounts,
            "list_partners": self.list_partners,
            "propose_update": self.propose_update,
            "propose_void": self.propose_void,
            "propose_create": self.propose_create,
        }.get(name)
        if handler is None:
            return {"error": f"未知工具 {name}"}
        try:
            return handler(arguments or {})
        except ValueError as exc:
            return {"error": str(exc)}

    def label(self, key: str, value: Any) -> str:
        """Name behind an id argument, for progress lines."""

        if key == "direction":
            return "收入" if value == "income" else "支出" if value == "expense" else str(value)
        model = {"payment_method_id": PaymentMethod, "category_id": Category, "partner_id": Partner}.get(key)
        if model is None or _int(value) is None:
            return str(value)
        name = self.db.scalar(select(model.name).where(model.id == _int(value), model.user_id == self.user_id))
        return str(name or value)

    def _scope(self, arguments: dict[str, Any]) -> dict[str, Any]:
        scope = {key: _int(arguments.get(key)) for key in ("payment_method_id", "category_id", "partner_id")}
        if arguments.get("direction") in {"income", "expense"}:
            scope["direction"] = arguments["direction"]
        return {key: value for key, value in scope.items() if value is not None}

    def summarize_period(self, arguments: dict[str, Any]) -> dict[str, Any]:
        kind = arguments.get("period") if arguments.get("period") in _PERIOD_KINDS else "month"
        try:
            spec = resolve_period(kind, _parse_date(arguments.get("start_date")), _parse_date(arguments.get("end_date")))
        except ValueError:
            raise ValueError("custom 周期需要有效的 start_date 和 end_date（start_date 不晚于 end_date）")
        if self.last_period is None:
            self.last_period = spec
        return summarize_period(self.db, self.user_id, spec, scope=self._scope(arguments) or None)

    def list_transactions(self, arguments: dict[str, Any]) -> dict[str, Any]:
        conditions = [Transaction.user_id == self.user_id, Transaction.status == "normal"]
        start, end = _parse_date(arguments.get("start_date")), _parse_date(arguments.get("end_date"))
        if start:
            conditions.append(Transaction.occurred_at >= business_day_start_utc(start))
        if end:
            conditions.append(Transaction.occurred_at < business_day_start_utc(end + (date(1970, 1, 2) - date(1970, 1, 1))))
        if arguments.get("kind") in {"cashflow", "transfer"}:
            conditions.append(Transaction.kind == arguments["kind"])
        scope = self._scope(arguments)
        for key in SCOPE_KEYS:
            if key in scope:
                column = getattr(Transaction, key)
                if key == "payment_method_id":
                    conditions.append(or_(column == scope[key], Transaction.transfer_payment_method_id == scope[key]))
                else:
                    conditions.append(column == scope[key])
        keyword = str(arguments.get("keyword") or "").strip()
        if keyword:
            conditions.append(Transaction.notes.ilike(f"%{keyword[:50]}%"))
        if _int(arguments.get("min_amount_cents")) is not None:
            conditions.append(Transaction.amount_cents >= _int(arguments["min_amount_cents"]))
        if _int(arguments.get("max_amount_cents")) is not None:
            conditions.append(Transaction.amount_cents <= _int(arguments["max_amount_cents"]))
        limit = min(max(_int(arguments.get("limit")) or 30, 1), MAX_LIST_ROWS)
        target = aliased(PaymentMethod)
        rows = self.db.execute(
            select(Transaction, Category.name, PaymentMethod.name, target.name, Partner.name)
            .outerjoin(Category, Transaction.category_id == Category.id)
            .outerjoin(PaymentMethod, Transaction.payment_method_id == PaymentMethod.id)
            .outerjoin(target, Transaction.transfer_payment_method_id == target.id)
            .outerjoin(Partner, Transaction.partner_id == Partner.id)
            .where(*conditions)
            .order_by(Transaction.occurred_at.desc(), Transaction.id.desc())
            .limit(limit + 1)
        ).all()
        total = self.db.scalar(select(func.count(Transaction.id)).where(*conditions)) or 0
        items = [
            {
                "id": tx.id,
                "date": to_business(tx.occurred_at).strftime("%Y-%m-%d %H:%M"),
                "kind": tx.kind,
                "direction": tx.direction if tx.kind == "cashflow" else None,
                "amount_cents": int(tx.amount_cents),
                "category": category or ("转账" if tx.kind == "transfer" else "未分类"),
                "account": account,
                "to_account": to_account,
                "partner": partner,
                "notes": ((tx.notes or "").strip()[:80] or None),
            }
            for tx, category, account, to_account, partner in rows[:limit]
        ]
        return {"total": int(total), "returned": len(items), "truncated": len(rows) > limit, "transactions": items}

    # -- change proposals -------------------------------------------------

    def _name(self, model, item_id: int | None) -> str | None:
        if item_id is None:
            return None
        name = self.db.scalar(select(model.name).where(model.id == item_id, model.user_id == self.user_id))
        if name is None:
            raise ValueError(f"id {item_id} 不在候选项里")
        return str(name)

    def _snapshot(self, tx: Transaction) -> dict[str, Any]:
        return {
            "id": tx.id,
            "occurred_at": to_business(tx.occurred_at).strftime("%Y-%m-%d %H:%M"),
            "kind": tx.kind,
            "direction": tx.direction if tx.kind == "cashflow" else None,
            "amount_cents": int(tx.amount_cents),
            "category": self._name(Category, tx.category_id) if tx.category_id else None,
            "account": self._name(PaymentMethod, tx.payment_method_id),
            "to_account": self._name(PaymentMethod, tx.transfer_payment_method_id) if tx.transfer_payment_method_id else None,
            "partner": self._name(Partner, tx.partner_id) if tx.partner_id else None,
            "notes": tx.notes,
        }

    def _owned_normal_transaction(self, arguments: dict[str, Any]) -> Transaction:
        tx = self.db.scalar(select(Transaction).where(Transaction.id == _int(arguments.get("transaction_id")), Transaction.user_id == self.user_id))
        if tx is None:
            raise ValueError("找不到这笔流水，请先用 list_transactions 确认 id")
        if tx.status != "normal":
            raise ValueError("这笔流水已经作废")
        return tx

    @staticmethod
    def _occurred_at(value: Any) -> str:
        text = str(value or "").strip()
        for pattern in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
            try:
                local = datetime.strptime(text, pattern).replace(tzinfo=BUSINESS_TZ)
                return local.astimezone(timezone.utc).isoformat()
            except ValueError:
                continue
        raise ValueError("occurred_at 需要是北京时间 YYYY-MM-DD HH:MM 或 YYYY-MM-DD")

    def _add_proposal(self, proposal: dict[str, Any]) -> dict[str, Any]:
        proposal["index"] = len(self.proposals)
        proposal["status"] = "pending"
        self.proposals.append(proposal)
        return {"proposal": proposal, "note": "方案已生成，需要用户在页面上确认后才会执行；请在回答里说明改动内容。"}

    def propose_update(self, arguments: dict[str, Any]) -> dict[str, Any]:
        tx = self._owned_normal_transaction(arguments)
        before = self._snapshot(tx)
        after = dict(before)
        changes: dict[str, Any] = {}
        if _int(arguments.get("amount_cents")) is not None:
            if _int(arguments["amount_cents"]) <= 0:
                raise ValueError("金额必须大于 0")
            changes["amount_cents"] = after["amount_cents"] = _int(arguments["amount_cents"])
        if arguments.get("occurred_at"):
            changes["occurred_at"] = self._occurred_at(arguments["occurred_at"])
            after["occurred_at"] = to_business(datetime.fromisoformat(changes["occurred_at"])).strftime("%Y-%m-%d %H:%M")
        if arguments.get("direction") in {"income", "expense"} and tx.kind == "cashflow":
            changes["direction"] = after["direction"] = arguments["direction"]
        if _int(arguments.get("category_id")) is not None and tx.kind == "cashflow":
            changes["category_id"] = _int(arguments["category_id"])
            after["category"] = self._name(Category, changes["category_id"])
        if _int(arguments.get("payment_method_id")) is not None:
            changes["payment_method_id"] = _int(arguments["payment_method_id"])
            after["account"] = self._name(PaymentMethod, changes["payment_method_id"])
        if _int(arguments.get("transfer_payment_method_id")) is not None and tx.kind == "transfer":
            changes["transfer_payment_method_id"] = _int(arguments["transfer_payment_method_id"])
            after["to_account"] = self._name(PaymentMethod, changes["transfer_payment_method_id"])
        if arguments.get("partner_id") is not None and tx.kind == "cashflow":
            partner_id = _int(arguments["partner_id"])
            changes["partner_id"] = partner_id or None
            after["partner"] = self._name(Partner, partner_id) if partner_id else None
        if "notes" in arguments and arguments["notes"] is not None:
            changes["notes"] = after["notes"] = str(arguments["notes"])[:5000]
        if not changes:
            raise ValueError("没有给出任何要修改的字段")
        return self._add_proposal({"type": "update", "transaction_id": tx.id, "reason": str(arguments.get("reason") or ""), "before": before, "after": after, "changes": changes})

    def propose_void(self, arguments: dict[str, Any]) -> dict[str, Any]:
        tx = self._owned_normal_transaction(arguments)
        return self._add_proposal({"type": "void", "transaction_id": tx.id, "reason": str(arguments.get("reason") or ""), "before": self._snapshot(tx)})

    def propose_create(self, arguments: dict[str, Any]) -> dict[str, Any]:
        kind = arguments.get("kind") if arguments.get("kind") in {"cashflow", "transfer"} else "cashflow"
        amount = _int(arguments.get("amount_cents"))
        if amount is None or amount <= 0:
            raise ValueError("金额必须大于 0")
        draft: dict[str, Any] = {
            "kind": kind,
            "direction": "expense" if kind == "transfer" else arguments.get("direction"),
            "amount_cents": amount,
            "occurred_at": self._occurred_at(arguments["occurred_at"]) if arguments.get("occurred_at") else datetime.now(timezone.utc).isoformat(),
            "payment_method_id": _int(arguments.get("payment_method_id")),
            "category_id": _int(arguments.get("category_id")) if kind == "cashflow" else None,
            "transfer_payment_method_id": _int(arguments.get("transfer_payment_method_id")) if kind == "transfer" else None,
            "partner_id": _int(arguments.get("partner_id")) if kind == "cashflow" else None,
            "notes": (str(arguments.get("notes"))[:5000] if arguments.get("notes") else None),
            "source": "ai",
        }
        if kind == "cashflow" and draft["direction"] not in {"income", "expense"}:
            raise ValueError("cashflow 需要 direction")
        if kind == "cashflow" and draft["category_id"] is None:
            raise ValueError("cashflow 需要 category_id")
        if kind == "transfer" and draft["transfer_payment_method_id"] is None:
            raise ValueError("transfer 需要 transfer_payment_method_id")
        after = {
            "occurred_at": to_business(datetime.fromisoformat(draft["occurred_at"])).strftime("%Y-%m-%d %H:%M"),
            "kind": kind,
            "direction": draft["direction"],
            "amount_cents": amount,
            "category": self._name(Category, draft["category_id"]) if draft["category_id"] else None,
            "account": self._name(PaymentMethod, draft["payment_method_id"]),
            "to_account": self._name(PaymentMethod, draft["transfer_payment_method_id"]) if draft["transfer_payment_method_id"] else None,
            "partner": self._name(Partner, draft["partner_id"]) if draft["partner_id"] else None,
            "notes": draft["notes"],
        }
        return self._add_proposal({"type": "create", "reason": str(arguments.get("reason") or ""), "after": after, "draft": draft})

    def list_accounts(self, arguments: dict[str, Any]) -> dict[str, Any]:
        rows = self.db.scalars(
            select(PaymentMethod).where(PaymentMethod.user_id == self.user_id, PaymentMethod.is_active.is_(True)).order_by(PaymentMethod.sort_order, PaymentMethod.id)
        ).all()
        return {
            "accounts": [
                {"id": item.id, "name": item.name, "role": getattr(item, "account_role", "cash") or "cash", "balance_cents": int(item.current_balance_cents or 0)}
                for item in rows
            ]
        }

    def list_partners(self, arguments: dict[str, Any]) -> dict[str, Any]:
        rows = self.db.scalars(select(Partner).where(Partner.user_id == self.user_id, Partner.status == "active").order_by(Partner.id)).all()
        return {
            "partners": [
                {
                    "id": item.id,
                    "name": item.name,
                    "type": item.type,
                    "unsettled_balance_cents": int(item.credit_used_cents or 0) if str(item.type).lower() == "customer" else int(item.prepaid_balance_cents or 0),
                }
                for item in rows
            ]
        }


def _tool_summary(name: str, arguments: dict[str, Any], names: Callable[[str, Any], str] = lambda key, value: str(value)) -> str:
    """One-line Chinese description of a call, for the progress panel."""

    parts: list[str] = []
    if name == "summarize_period":
        period = {"day": "当天", "week": "本周", "month": "本月", "year": "本年", "all": "全部", "custom": "自定义区间"}.get(arguments.get("period"), "")
        dates = " ".join(str(arguments.get(key)) for key in ("start_date", "end_date") if arguments.get(key))
        parts.append(f"统计{period} {dates}".strip())
    elif name == "list_transactions":
        dates = "～".join(str(arguments.get(key)) for key in ("start_date", "end_date") if arguments.get(key))
        parts.append(f"查流水 {dates}".strip())
        if arguments.get("keyword"):
            parts.append(f"关键词“{arguments['keyword']}”")
    elif name == "propose_update":
        parts.append(f"拟修改流水 #{arguments.get('transaction_id')}")
    elif name == "propose_void":
        parts.append(f"拟作废流水 #{arguments.get('transaction_id')}")
    elif name == "propose_create":
        parts.append("拟补记一笔")
    elif name == "list_accounts":
        parts.append("查看账户余额")
    elif name == "list_partners":
        parts.append("查看往来单位")
    else:
        parts.append(name)
    for key, label in (("payment_method_id", "账户"), ("category_id", "分类"), ("partner_id", "往来"), ("direction", "类型")):
        if arguments.get(key) is not None:
            parts.append(f"{label}={names(key, arguments[key])}")
    return " · ".join(parts)


def _result_summary(name: str, result: dict[str, Any]) -> str:
    if "error" in result:
        return f"失败：{result['error']}"
    if name == "summarize_period":
        return f"{result.get('transaction_count', 0)} 笔，收入 {result.get('income_cents', 0) / 100:.2f}，支出 {result.get('expense_cents', 0) / 100:.2f}"
    if name == "list_transactions":
        return f"共 {result.get('total', 0)} 笔，返回 {result.get('returned', 0)} 笔"
    if name.startswith("propose_"):
        return "方案已生成，等你确认"
    if name == "list_accounts":
        return f"{len(result.get('accounts', []))} 个账户"
    if name == "list_partners":
        return f"{len(result.get('partners', []))} 个往来单位"
    return "完成"


def _bounded_json(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False)
    if len(text) > MAX_TOOL_RESULT_CHARS:
        text = text[:MAX_TOOL_RESULT_CHARS] + "…(已截断)"
    return text


def _system_prompt(db: Session, user_id: int, intent: str) -> str:
    today = business_today()
    weekday = "一二三四五六日"[today.weekday()]
    accounts = [f"{item.id}={item.name}({'负债' if getattr(item, 'account_role', 'cash') == 'liability' else '投资' if getattr(item, 'account_role', 'cash') == 'investment' else '现金'})" for item in db.scalars(select(PaymentMethod).where(PaymentMethod.user_id == user_id, PaymentMethod.is_active.is_(True)).order_by(PaymentMethod.sort_order, PaymentMethod.id))]
    categories = [f"{item.id}={item.name}({'收' if item.direction == 'income' else '支' if item.direction == 'expense' else '通用'})" for item in db.scalars(select(Category).where(Category.user_id == user_id, Category.is_active.is_(True)).order_by(Category.sort_order, Category.id))]
    partners = [f"{item.id}={item.name}({'客户' if str(item.type).lower() == 'customer' else '供应商'})" for item in db.scalars(select(Partner).where(Partner.user_id == user_id, Partner.status == "active").order_by(Partner.id))]
    task = (
        "任务：生成一份收支报告。先用工具取得汇总（必要时再取明细），然后输出结构化的中文报告：总览（笔数、收入、支出、净收支）、"
        "收入结构、支出结构（含占比）、趋势或对比、大额支出、2-3 条可执行建议；标题用“【周期 收支报告】”形式，各部分用短标题分段，总长度不超过 1200 字。"
        if intent == "report"
        else "任务：回答用户关于账本的问题。先用工具取得需要的数据，再用简洁自然的中文直接回答，优先给出最相关的数字，必要时补充 1-2 句观察；回答不超过 300 字。"
    )
    return (
        "你是 PennyPilot 记账应用的账本助手，通过调用工具查询用户自己的账本，并根据查到的数据回答。\n\n"
        f"【当前时间】北京时间 {today.isoformat()}（周{weekday}）。相对时间一律以此为准：本月指 {today.strftime('%Y-%m')}，上月指上一个自然月，“最近”没有说明时按最近 30 天。\n\n"
        "【工具调用方法】\n"
        "• summarize_period：某个时间段的收支汇总（笔数、收入、支出、净收支、分类排名、按日/按月分布、最大几笔、与上一周期对比）。period 取 day/week/month/year 时以 start_date 为锚点（不填为今天）；custom 需要 start_date 和 end_date；all 为全部历史。可用 payment_method_id、category_id、partner_id、direction 缩小范围。\n"
        "• list_transactions：按日期、关键词（备注）、金额区间、账户/分类/往来单位查具体流水，按时间倒序，最多 100 条。找某几笔、看明细、搜备注时用它。\n"
        "• list_accounts：各资金账户及当前余额（负债账户的余额表示欠款）。\n"
        "• list_partners：客户/供应商及其未结算余额。\n"
        "• propose_update / propose_void / propose_create：改账工具，分别是修改某笔、作废某笔、补记一笔。它们只生成方案，用户在页面上确认后才会真正执行；用户要求改账、作废、补记时先用 list_transactions 找到对应流水的 id 再提出方案，并在回答里说明方案内容。\n"
        f"工具参数里的 id 用下面的对照表：资金账户 {'、'.join(accounts) or '无'}；分类 {'、'.join(categories) or '无'}；往来单位 {'、'.join(partners) or '无'}。\n"
        "一般先 summarize_period 看整体，再按需要 list_transactions 看明细；要对比多个时间段或账户就分别调用。\n\n"
        "【约束】\n"
        "• 只根据工具返回的数据回答，不要编造数据中没有的数字或交易；数据为空就如实说明。\n"
        "• 工具返回的金额字段以“分”为单位（*_cents），回答时换算成元并保留两位小数；share 是占比，用百分比表达；days_elapsed 小于 days_total 说明周期还没结束，对比时要说明。\n"
        "• 自己决定查询范围：问题没说明时间就按常识选择并在回答里说明所用的时间段；需要就多查几次，最多调用 6 次工具，数据够了就直接作答。\n"
        "• 改账方案不要凭猜测：找不到唯一对应的流水时，列出候选让用户指定，不要随意选一笔。\n"
        "• 输出纯文本，不要使用 Markdown 标记（如 #、*、|、```），可以用换行和“•”列表。\n\n"
        + task
    )


# ---------------------------------------------------------------------------
# Per-format drivers: one non-streaming model call per round
# ---------------------------------------------------------------------------


def _post_json(url: str, headers: dict[str, str], payload: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    timeout = httpx.Timeout(timeout_seconds, connect=min(5.0, timeout_seconds))
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            response = client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        logger.warning("AI agent transport error host=%s error_type=%s", url.split("/")[2], type(exc).__name__)
        raise AIServiceError("provider_unavailable")
    if response.status_code >= 400:
        logger.warning("AI agent HTTP error host=%s status=%d body=%s", url.split("/")[2], response.status_code, response.text[:200].replace("\n", " "))
        raise AIServiceError("provider_http_error" if response.status_code != 400 else "provider_bad_request")
    try:
        data = response.json()
    except ValueError:
        raise AIServiceError("provider_invalid_response")
    if not isinstance(data, dict):
        raise AIServiceError("provider_invalid_response")
    return data


class _Loop:
    """Shared bookkeeping for a tool loop: budget, rounds, progress events."""

    def __init__(self, tools: LedgerTools, emit: Callable[[dict[str, Any]], None]):
        self.tools = tools
        self.emit = emit
        self.started = time.monotonic()
        self.steps: list[dict[str, str]] = []

    def remaining(self) -> float:
        left = AGENT_TOTAL_TIMEOUT_SECONDS - (time.monotonic() - self.started)
        if left <= 5:
            raise AIServiceError("provider_unavailable")
        return min(left, max(AI_STREAM_IDLE_TIMEOUT_SECONDS, 90.0))

    def run_tool(self, name: str, arguments: Any) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            arguments = {}
        summary = _tool_summary(name, arguments, self.tools.label)
        self.emit({"type": "tool", "name": name, "summary": summary})
        result = self.tools.call(name, arguments)
        done = _result_summary(name, result)
        self.steps.append({"name": name, "summary": summary, "result": done})
        self.emit({"type": "tool_result", "name": name, "summary": done})
        return result


def _drive_openai(service: AIService, provider: Provider, system: str, turns: list[tuple[str, str]], loop: _Loop) -> str:
    endpoint = completion_endpoint(provider.base_url)
    headers = {"Authorization": "Bearer " + provider.api_key, "Content-Type": "application/json"}
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}] + [{"role": role, "content": text} for role, text in turns]
    tools = [{"type": "function", "function": {"name": tool["name"], "description": tool["description"], "parameters": tool["parameters"]}} for tool in TOOLS]
    payload = {
        "model": provider.model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": 0.2,
        "max_tokens": ANALYSIS_MAX_TOKENS,
        "stream": False,
        **reasoning_controls_for_provider(provider, "high"),
    }
    for _ in range(MAX_TOOL_ROUNDS + 1):
        data = _post_json(endpoint, headers, payload, loop.remaining())
        message = (data.get("choices") or [{}])[0].get("message") or {}
        calls = message.get("tool_calls") or []
        if not calls:
            content = message.get("content")
            if not isinstance(content, str) or not content.strip():
                raise AIServiceError("provider_invalid_response")
            return content.strip()
        assistant: dict[str, Any] = {"role": "assistant", "content": message.get("content"), "tool_calls": calls}
        if message.get("reasoning_content"):
            # DeepSeek's thinking mode needs its reasoning echoed back within a turn.
            assistant["reasoning_content"] = message["reasoning_content"]
        messages.append(assistant)
        for call in calls:
            function = call.get("function") or {}
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except ValueError:
                arguments = {}
            result = loop.run_tool(str(function.get("name")), arguments)
            messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": _bounded_json(result)})
    raise AIServiceError("provider_invalid_response")


def _drive_gemini(service: AIService, provider: Provider, system: str, turns: list[tuple[str, str]], loop: _Loop) -> str:
    endpoint = f"{_api_root(provider.base_url)}/v1beta/models/{quote(provider.model, safe='')}:generateContent"
    headers = {"x-goog-api-key": provider.api_key, "Content-Type": "application/json"}
    contents: list[dict[str, Any]] = [{"role": "model" if role == "assistant" else "user", "parts": [{"text": text}]} for role, text in turns]
    declarations = [{"name": tool["name"], "description": tool["description"], "parameters": _schema_without(tool["parameters"], keys=("additionalProperties",), null_enums=True)} for tool in TOOLS]
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "tools": [{"functionDeclarations": declarations}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": ANALYSIS_MAX_TOKENS, "thinkingConfig": {"thinkingLevel": "high"}},
    }
    for _ in range(MAX_TOOL_ROUNDS + 1):
        data = _post_json(endpoint, headers, {**body, "contents": contents}, loop.remaining())
        candidate = (data.get("candidates") or [{}])[0]
        content = candidate.get("content") or {}
        parts = content.get("parts") or []
        calls = [part["functionCall"] for part in parts if isinstance(part.get("functionCall"), dict)]
        if not calls:
            text = "".join(part.get("text", "") for part in parts if isinstance(part.get("text"), str) and not part.get("thought")).strip()
            if not text:
                raise AIServiceError("provider_invalid_response")
            return text
        # The model turn is echoed back verbatim (thought signatures included).
        contents.append({"role": "model", "parts": parts})
        responses = []
        for call in calls:
            result = loop.run_tool(str(call.get("name")), call.get("args") or {})
            payload = result if len(json.dumps(result, ensure_ascii=False)) <= MAX_TOOL_RESULT_CHARS else {"truncated": _bounded_json(result)}
            response: dict[str, Any] = {"name": call.get("name"), "response": {"result": payload}}
            if call.get("id"):
                # Gateways that assign call ids require them echoed on the response.
                response["id"] = call["id"]
            responses.append({"functionResponse": response})
        contents.append({"role": "user", "parts": responses})
    raise AIServiceError("provider_invalid_response")


def _drive_anthropic(service: AIService, provider: Provider, system: str, turns: list[tuple[str, str]], loop: _Loop) -> str:
    tools = [{"name": tool["name"], "description": tool["description"], "input_schema": _schema_without(tool["parameters"], keys=("minimum",))} for tool in TOOLS]
    messages: list[dict[str, Any]] = [{"role": role, "content": text} for role, text in turns]
    base: dict[str, Any] = {"model": provider.model, "max_tokens": ANALYSIS_MAX_TOKENS, "system": system, "messages": messages, "tools": tools}
    enhanced = {**base, "thinking": {"type": "adaptive"}, "output_config": {"effort": "max"}}
    params = enhanced
    with anthropic.Anthropic(
        api_key=provider.api_key,
        base_url=_api_root(provider.base_url),
        max_retries=0,
        timeout=anthropic.Timeout(loop.remaining(), connect=5.0),
    ) as client:
        for _ in range(MAX_TOOL_ROUNDS + 1):
            try:
                with client.messages.stream(**params) as stream:
                    message = stream.get_final_message()
            except anthropic.BadRequestError:
                if params is enhanced:
                    # Models without adaptive thinking/effort get the plain request.
                    params = base
                    continue
                raise AIServiceError("provider_http_error")
            except anthropic.APIStatusError:
                raise AIServiceError("provider_http_error")
            except anthropic.APIConnectionError:
                raise AIServiceError("provider_unavailable")
            if message.stop_reason == "refusal":
                raise AIServiceError("provider_refused")
            uses = [block for block in message.content if block.type == "tool_use"]
            if not uses:
                text = "".join(block.text for block in message.content if block.type == "text").strip()
                if not text:
                    raise AIServiceError("provider_invalid_response")
                return text
            # Echo the assistant turn unchanged (thinking blocks included).
            messages.append({"role": "assistant", "content": message.content})
            results = []
            for block in uses:
                result = loop.run_tool(block.name, block.input if isinstance(block.input, dict) else {})
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": _bounded_json(result)})
            messages.append({"role": "user", "content": results})
    raise AIServiceError("provider_invalid_response")


def run_ledger_agent(
    service: AIService,
    db: Session,
    user_id: int,
    text: str,
    conversation: list[dict[str, str]],
    intent: str,
    emit: Callable[[dict[str, Any]], None],
) -> AgentResult:
    """Answer a ledger question with tools; the model chooses what to query."""

    tools = LedgerTools(db, user_id)
    system = _system_prompt(db, user_id, intent)
    messages = [{"role": "system", "content": system}]
    for item in (conversation or [])[-MAX_CONVERSATION_MESSAGES:]:
        if item.get("role") in {"user", "assistant"} and isinstance(item.get("content"), str) and item["content"].strip():
            messages.append({"role": item["role"], "content": item["content"][:MAX_INPUT_CHARS]})
    messages.append({"role": "user", "content": text[:MAX_INPUT_CHARS]})
    _, turns = _conversation_turns(messages)
    providers = service.provider_chain_for_user(db, user_id)
    drivers = {"openai": _drive_openai, "anthropic": _drive_anthropic, "gemini": _drive_gemini}
    last_error: AIServiceError | None = None
    for index, provider in enumerate(providers):
        loop = _Loop(tools, emit)
        emit({"type": "provider", "name": provider.name, "model": provider.model})
        if not service.settings.ai_enabled or not provider.api_key:
            last_error = AIServiceError("not_configured")
        else:
            try:
                content = drivers.get(provider.api_format, _drive_openai)(service, provider, system, turns, loop)
                warning = "AI 主通道暂不可用，已切换备用通道。" if index > 0 else None
                return AgentResult(content, "model", warning, provider.model, loop.steps, tools.last_period, tools.proposals)
            except AIServiceError as exc:
                last_error = exc
                logger.warning("AI agent provider failed provider=%s model=%s format=%s code=%s", provider.name, provider.model, provider.api_format, exc.code)
        if index + 1 < len(providers):
            emit({"type": "status", "code": "provider_failed"})
    if last_error and last_error.code == "not_configured" and len(providers) == 1:
        warning = "未配置 AI 服务，已根据账本数据生成本地回答。"
    elif len(providers) > 1:
        warning = "AI 主通道和备用通道均不可用，已根据账本数据生成本地回答。"
    else:
        warning = "AI 服务暂不可用，已根据账本数据生成本地回答。"
    emit({"type": "status", "code": "local_fallback"})
    # Without a model, answer from the period the question names (else this month).
    spec = parse_period_text(text) or resolve_period("month")
    summary = summarize_period(db, user_id, spec)
    content = fallback_report(summary) if intent == "report" else fallback_answer(summary)
    return AgentResult(content, "fallback", warning, None, [], spec)
