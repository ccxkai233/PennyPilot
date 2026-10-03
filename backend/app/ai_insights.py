"""Period resolution, cash-flow aggregation and intent detection for AI insights.

This module is deliberately free of any model call.  It turns a Beijing
calendar period (today, this week, this month, this year, everything, or a
custom range) into SQL-aggregated income/expense figures that both the
charts on the analysis page and the conversational AI assistant consume.
The deterministic answer/report builders below are the offline fallback
when no model is configured, so a user always gets real numbers.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Category, PaymentMethod, Transaction
from .partner_models import Partner
from .timezone import business_day_start_utc, business_today, to_business


PERIOD_KINDS = ("day", "week", "month", "year", "all", "custom")
# Bucketing happens in Python because the Beijing day boundary is a +08:00
# offset on UTC instants, which SQLite (used in tests) cannot express.  The
# scan is bounded so a very large ledger still answers quickly; totals and
# category figures are always exact because they are aggregated in SQL.
MAX_BUCKET_ROWS = 20_000
MAX_DAILY_SPAN_DAYS = 62
TOP_CATEGORIES = 8
TOP_TRANSACTIONS = 5
MAX_CATEGORY_ENTRIES = 30


@dataclass(frozen=True)
class PeriodSpec:
    kind: str
    start: date | None
    end: date
    label: str

    @property
    def span_days(self) -> int | None:
        if self.start is None:
            return None
        return (self.end - self.start).days + 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "start_date": self.start.isoformat() if self.start else None,
            "end_date": self.end.isoformat(),
        }


def _month_end(value: date) -> date:
    return value.replace(day=monthrange(value.year, value.month)[1])


def _shift_month(value: date, months: int) -> date:
    index = value.year * 12 + value.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def period_label(kind: str, start: date | None, end: date, today: date | None = None) -> str:
    today = today or business_today()
    if kind == "all":
        return "全部记录"
    if start is None:
        return f"截至 {end.isoformat()}"
    if kind == "day":
        if start == today:
            return f"今天（{start.isoformat()}）"
        if start == today - timedelta(days=1):
            return f"昨天（{start.isoformat()}）"
        return start.isoformat()
    if kind == "week":
        this_week = today - timedelta(days=today.weekday())
        prefix = "本周" if start == this_week else ("上周" if start == this_week - timedelta(days=7) else "该周")
        return f"{prefix}（{start.isoformat()} 至 {end.isoformat()}）"
    if kind == "month":
        if (start.year, start.month) == (today.year, today.month):
            prefix = "本月"
        elif (start.year, start.month) == (_shift_month(today, -1).year, _shift_month(today, -1).month):
            prefix = "上月"
        else:
            prefix = f"{start.year}年{start.month}月"
        return f"{prefix}（{start.isoformat()} 至 {end.isoformat()}）"
    if kind == "year":
        prefix = "本年" if start.year == today.year else ("去年" if start.year == today.year - 1 else f"{start.year}年")
        return f"{prefix}（{start.isoformat()} 至 {end.isoformat()}）"
    return f"{start.isoformat()} 至 {end.isoformat()}"


def resolve_period(
    kind: str,
    start_date: date | None = None,
    end_date: date | None = None,
    today: date | None = None,
) -> PeriodSpec:
    """Map a period kind plus optional anchor/range to Beijing calendar dates.

    ``start_date`` acts as an anchor for day/week/month/year (defaulting to
    today); ``custom`` requires both bounds.  ``all`` has an open lower bound
    that the summary later fills with the first transaction date.
    """

    today = today or business_today()
    if kind not in PERIOD_KINDS:
        raise ValueError("unsupported period")
    if kind == "custom":
        if start_date is None or end_date is None or end_date < start_date:
            raise ValueError("custom period requires a valid date range")
        return PeriodSpec("custom", start_date, end_date, period_label("custom", start_date, end_date, today))
    if kind == "all":
        return PeriodSpec("all", None, end_date or today, period_label("all", None, end_date or today, today))
    anchor = start_date or today
    if kind == "day":
        end = end_date or anchor
        if end < anchor:
            end = anchor
        label_kind = "day" if end == anchor else "custom"
        return PeriodSpec("day", anchor, end, period_label(label_kind, anchor, end, today))
    if kind == "week":
        start = anchor - timedelta(days=anchor.weekday())
        end = start + timedelta(days=6)
        return PeriodSpec("week", start, end, period_label("week", start, end, today))
    if kind == "month":
        start = anchor.replace(day=1)
        end = _month_end(anchor)
        return PeriodSpec("month", start, end, period_label("month", start, end, today))
    start = anchor.replace(month=1, day=1)
    end = anchor.replace(month=12, day=31)
    return PeriodSpec("year", start, end, period_label("year", start, end, today))


def previous_period(spec: PeriodSpec) -> PeriodSpec | None:
    """Return the comparable preceding period for a calendar-based spec."""

    if spec.start is None:
        return None
    if spec.kind == "day":
        length = (spec.end - spec.start).days + 1
        end = spec.start - timedelta(days=1)
        return PeriodSpec("day", end - timedelta(days=length - 1), end, period_label("day" if length == 1 else "custom", end - timedelta(days=length - 1), end))
    if spec.kind == "week":
        start = spec.start - timedelta(days=7)
        return PeriodSpec("week", start, start + timedelta(days=6), period_label("week", start, start + timedelta(days=6)))
    if spec.kind == "month":
        start = _shift_month(spec.start, -1)
        return PeriodSpec("month", start, _month_end(start), period_label("month", start, _month_end(start)))
    if spec.kind == "year":
        start = spec.start.replace(year=spec.start.year - 1)
        end = start.replace(month=12, day=31)
        return PeriodSpec("year", start, end, period_label("year", start, end))
    return None


# ---------------------------------------------------------------------------
# Natural-language period parsing (Chinese)
# ---------------------------------------------------------------------------

_CN_NUM = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _small_number(raw: str) -> int | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)
    if raw == "十":
        return 10
    if len(raw) == 2 and raw[0] == "十" and raw[1] in _CN_NUM:
        return 10 + _CN_NUM[raw[1]]
    if len(raw) == 2 and raw[1] == "十" and raw[0] in _CN_NUM:
        return _CN_NUM[raw[0]] * 10
    if len(raw) == 3 and raw[1] == "十" and raw[0] in _CN_NUM and raw[2] in _CN_NUM:
        return _CN_NUM[raw[0]] * 10 + _CN_NUM[raw[2]]
    if len(raw) == 1 and raw in _CN_NUM:
        return _CN_NUM[raw]
    return None


_NUM = r"(\d{1,2}|[一二两三四五六七八九十]{1,3})"


def parse_period_text(text: str, today: date | None = None) -> PeriodSpec | None:
    """Recognise a Chinese period expression, or return ``None``."""

    today = today or business_today()
    value = (text or "").strip()
    if not value:
        return None

    match = re.search(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]", value)
    if match:
        try:
            day = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
        return resolve_period("day", day, today=today)
    match = re.search(r"(20\d{2})\s*年\s*(\d{1,2})\s*月", value)
    if match:
        try:
            anchor = date(int(match.group(1)), int(match.group(2)), 1)
        except ValueError:
            return None
        return resolve_period("month", anchor, today=today)
    match = re.search(r"(20\d{2})\s*年(?!\s*[前后以来])", value)
    if match:
        return resolve_period("year", date(int(match.group(1)), 1, 1), today=today)

    if re.search(r"今天|今日|本日|当天", value):
        return resolve_period("day", today, today=today)
    if re.search(r"昨天|昨日", value):
        return resolve_period("day", today - timedelta(days=1), today=today)
    if "前天" in value:
        return resolve_period("day", today - timedelta(days=2), today=today)
    if re.search(r"本周|这周|这个星期|本星期|这一周|本礼拜|这个礼拜", value):
        return resolve_period("week", today, today=today)
    if re.search(r"上周|上星期|上个星期|上个礼拜|上礼拜", value):
        return resolve_period("week", today - timedelta(days=7), today=today)
    if re.search(r"本月|这个月|当月|这月|本月份|月初至今|本月以来", value):
        return resolve_period("month", today, today=today)
    if re.search(r"上月|上个月|上月份", value):
        return resolve_period("month", _shift_month(today, -1), today=today)
    if re.search(r"本年|今年|本年度|年初至今|今年以来|年度", value):
        return resolve_period("year", today, today=today)
    if re.search(r"去年|上一年|上年度|上年", value):
        return resolve_period("year", today.replace(year=today.year - 1, month=1, day=1), today=today)

    match = re.search(r"(?:最近|近|过去)\s*" + _NUM + r"\s*(天|日|周|个?星期|个月|年)", value)
    if match:
        amount = _small_number(match.group(1))
        unit = match.group(2)
        if amount:
            if unit in {"天", "日"}:
                start = today - timedelta(days=amount - 1)
            elif "周" in unit or "星期" in unit:
                start = today - timedelta(days=amount * 7 - 1)
            elif unit == "个月":
                start = _shift_month(today, -(amount - 1))
            else:
                start = today.replace(year=today.year - amount + 1, month=1, day=1)
            return resolve_period("custom", start, today, today=today)
    if re.search(r"最近一周|近一周|最近七天|近七天", value):
        return resolve_period("custom", today - timedelta(days=6), today, today=today)
    if re.search(r"最近一个月|近一个月|最近30天|近30天", value):
        return resolve_period("custom", today - timedelta(days=29), today, today=today)

    match = re.search(r"(?<![本上下个每年])" + _NUM + r"\s*月\s*(\d{1,2})\s*[日号]", value)
    if match:
        month = _small_number(match.group(1))
        day_number = int(match.group(2))
        if month and 1 <= month <= 12:
            year = today.year if month <= today.month else today.year - 1
            try:
                return resolve_period("day", date(year, month, day_number), today=today)
            except ValueError:
                return None
    match = re.search(r"(?<![本上下个每年\d])" + _NUM + r"\s*月份?(?![\d日号])", value)
    if match:
        month = _small_number(match.group(1))
        if month and 1 <= month <= 12:
            year = today.year if month <= today.month else today.year - 1
            return resolve_period("month", date(year, month, 1), today=today)

    if re.search(r"全部|所有|累计|总共|总计|至今|迄今|历史|一直以来|开账以来|总的|整体|总体|全年以来|从头", value):
        return resolve_period("all", today=today)
    return None


# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------

_AMOUNT_RE = re.compile(
    r"(?<![\d.])\d[\d,]*(?:\.\d+)?\s*(?:元|块|万|千|k|K)?(?!\s*(?:月|日|号|天|周|个月|年|笔|点|时|:|：|%))"
    r"|[一二两三四五六七八九零]+[十百千万][一二两三四五六七八九十百千万零]*\s*(?:元|块)?"
    r"|[一二两三四五六七八九十]+\s*(?:元|块)"
)
_RECORD_RE = re.compile(
    r"记一笔|记账|入账|记录一|补记|加一笔|记下|花了|花费了|买了|付了|付款|付给|支付|收到|收了|转账|转给|充值|充了|"
    r"还款|还了|消费了|扫了|打给|到账|预存|结清|欠款|余额是|余额为|吃了|加油|打车|报销"
)
_REPORT_RE = re.compile(
    r"报告|复盘|总结|汇总|盘点|概览|总览|财务分析|收支分析|经营分析|月度分析|年度分析|分析一下|分析下|分析一份|"
    r"做个分析|做一下分析|做份分析|生成.*分析|来个分析|帮我分析|统计一下|统计下|给我分析|分析报告|分析我的|分析本|分析今|分析上|分析这|分析全部|分析所有"
)
_QUERY_RE = re.compile(
    r"多少|几笔|多少笔|怎么样|怎样|如何|情况|哪些|哪个|哪几|什么|占比|最多|最大|最高|最少|趋势|对比|比较|超支|结余|盈亏|"
    r"赚了|亏了|净收|净支|剩多少|花在|平均|每天|日均|查一下|查下|看看|看一下|看下|告诉我|吗|呢|？|\?"
)
_TOPIC_RE = re.compile(
    r"收支|收入|支出|花销|开销|开支|花费|消费|花了多少|赚|盈利|利润|结余|净|流水|账单|账目|交易|分类|趋势|进账|出账|收益|亏损|余额|资产"
)


def detect_intent(text: str, has_chat_context: bool = False) -> str:
    """Classify a message as ``bookkeeping``, ``query`` or ``report``.

    Bookkeeping stays the default: a message with a money amount and a
    recording verb is always a transaction proposal.  Only an explicit
    question or report request about the ledger becomes a data conversation.
    """

    value = (text or "").strip()
    if not value:
        return "bookkeeping"
    has_amount = bool(_AMOUNT_RE.search(value))
    has_record = bool(_RECORD_RE.search(value))
    has_query = bool(_QUERY_RE.search(value))
    has_report = bool(_REPORT_RE.search(value))
    has_topic = bool(_TOPIC_RE.search(value))
    has_period = parse_period_text(value) is not None
    if has_amount and has_record and not has_query:
        return "bookkeeping"
    if has_report:
        return "report"
    if has_query and (has_topic or has_period or has_chat_context):
        return "query"
    if has_period and has_topic and not has_amount and not has_record:
        return "query"
    if has_chat_context and has_period and not has_amount and not has_record:
        return "query"
    return "bookkeeping"


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def first_transaction_date(db: Session, user_id: int) -> date | None:
    earliest = db.scalar(
        select(func.min(Transaction.occurred_at)).where(
            Transaction.user_id == user_id,
            Transaction.status == "normal",
            Transaction.kind == "cashflow",
        )
    )
    if earliest is None:
        return None
    if isinstance(earliest, str):
        try:
            earliest = datetime.fromisoformat(earliest)
        except ValueError:
            return None
    return to_business(earliest).date()


def _bounds(spec: PeriodSpec) -> tuple[datetime | None, datetime]:
    start = business_day_start_utc(spec.start) if spec.start else None
    end = business_day_start_utc(spec.end + timedelta(days=1))
    return start, end


# Optional narrowing of a summary to one account, category, partner or
# direction; the keys mirror the transaction list filters.
SCOPE_KEYS = ("payment_method_id", "category_id", "partner_id", "direction")


def _base_filter(user_id: int, start: datetime | None, end: datetime, scope: dict[str, Any] | None = None):
    conditions = [
        Transaction.user_id == user_id,
        Transaction.status == "normal",
        Transaction.kind == "cashflow",
        Transaction.occurred_at < end,
    ]
    if start is not None:
        conditions.append(Transaction.occurred_at >= start)
    for key in SCOPE_KEYS:
        if scope and scope.get(key) is not None:
            conditions.append(getattr(Transaction, key) == scope[key])
    return conditions


def scope_labels(db: Session, user_id: int, scope: dict[str, Any] | None) -> dict[str, str]:
    """Human-readable names of a scope, for the prompt and the answer card."""

    labels: dict[str, str] = {}
    if not scope:
        return labels
    lookups = (
        ("payment_method_id", PaymentMethod, "账户"),
        ("category_id", Category, "分类"),
        ("partner_id", Partner, "往来单位"),
    )
    for key, model, label in lookups:
        if scope.get(key) is not None:
            name = db.scalar(select(model.name).where(model.id == scope[key], model.user_id == user_id))
            if name:
                labels[label] = str(name)
    if scope.get("direction") in {"income", "expense"}:
        labels["类型"] = "仅收入" if scope["direction"] == "income" else "仅支出"
    return labels


def _totals(db: Session, user_id: int, start: datetime | None, end: datetime, scope: dict[str, Any] | None = None) -> dict[str, int]:
    rows = db.execute(
        select(
            Transaction.direction,
            func.count(Transaction.id),
            func.coalesce(func.sum(Transaction.amount_cents), 0),
        )
        .where(*_base_filter(user_id, start, end, scope))
        .group_by(Transaction.direction)
    ).all()
    totals = {direction: (int(count), int(amount)) for direction, count, amount in rows}
    income_count, income = totals.get("income", (0, 0))
    expense_count, expense = totals.get("expense", (0, 0))
    return {
        "transaction_count": income_count + expense_count,
        "income_count": income_count,
        "expense_count": expense_count,
        "income_cents": income,
        "expense_cents": expense,
        "net_cents": income - expense,
    }


def _tx_payload(tx: Transaction, category_name: str | None) -> dict[str, Any]:
    note = (tx.notes or "").strip()
    return {
        "date": to_business(tx.occurred_at).date().isoformat(),
        "amount_cents": int(tx.amount_cents),
        "category": category_name or "未分类",
        "notes": note[:40] or None,
    }


def summarize_period(db: Session, user_id: int, spec: PeriodSpec, *, compare: bool = True, scope: dict[str, Any] | None = None) -> dict[str, Any]:
    """Aggregate cash-flow transactions for a period, optionally within a scope.

    The result keeps the key names used by the existing analysis report
    (``transaction_count``, ``income_cents``, ``expense_cents``,
    ``net_cents``, ``categories``, ``daily``) and adds ranking, bucketing and
    comparison data the conversational assistant needs.
    """

    today = business_today()
    if spec.start is None:
        earliest = first_transaction_date(db, user_id)
        effective_start = earliest if earliest and earliest <= spec.end else None
    else:
        effective_start = spec.start
    start_utc, end_utc = _bounds(spec)
    summary: dict[str, Any] = {"period": spec.as_dict()}
    if effective_start is not None:
        summary["period"]["start_date"] = effective_start.isoformat()
    labels = scope_labels(db, user_id, scope)
    if labels:
        summary["scope"] = labels
    summary.update(_totals(db, user_id, start_utc, end_utc, scope))

    category_rows = db.execute(
        select(
            Category.name,
            Transaction.direction,
            func.count(Transaction.id),
            func.coalesce(func.sum(Transaction.amount_cents), 0),
        )
        .select_from(Transaction)
        .outerjoin(Category, Transaction.category_id == Category.id)
        .where(*_base_filter(user_id, start_utc, end_utc, scope))
        .group_by(Category.name, Transaction.direction)
    ).all()
    categories: dict[str, dict[str, int]] = {}
    for name, direction, count, amount in category_rows:
        bucket = categories.setdefault(name or "未分类", {"income_cents": 0, "expense_cents": 0, "count": 0})
        bucket["count"] += int(count)
        bucket["income_cents" if direction == "income" else "expense_cents"] += int(amount)
    ranked = sorted(categories.items(), key=lambda item: item[1]["income_cents"] + item[1]["expense_cents"], reverse=True)
    summary["categories"] = dict(ranked[:MAX_CATEGORY_ENTRIES])
    expense_total = summary["expense_cents"] or 0
    income_total = summary["income_cents"] or 0
    summary["top_expense_categories"] = [
        {
            "name": name,
            "amount_cents": data["expense_cents"],
            "count": data["count"],
            "share": round(data["expense_cents"] / expense_total, 4) if expense_total else 0,
        }
        for name, data in sorted(categories.items(), key=lambda item: item[1]["expense_cents"], reverse=True)
        if data["expense_cents"] > 0
    ][:TOP_CATEGORIES]
    summary["top_income_categories"] = [
        {
            "name": name,
            "amount_cents": data["income_cents"],
            "count": data["count"],
            "share": round(data["income_cents"] / income_total, 4) if income_total else 0,
        }
        for name, data in sorted(categories.items(), key=lambda item: item[1]["income_cents"], reverse=True)
        if data["income_cents"] > 0
    ][:TOP_CATEGORIES]

    bucket_rows = db.execute(
        select(Transaction.occurred_at, Transaction.direction, Transaction.amount_cents)
        .where(*_base_filter(user_id, start_utc, end_utc, scope))
        .order_by(Transaction.occurred_at.desc())
        .limit(MAX_BUCKET_ROWS + 1)
    ).all()
    truncated = len(bucket_rows) > MAX_BUCKET_ROWS
    daily: dict[str, dict[str, int]] = {}
    monthly: dict[str, dict[str, int]] = {}
    for occurred_at, direction, amount_cents in bucket_rows[:MAX_BUCKET_ROWS]:
        local_day = to_business(occurred_at).date()
        key = "income_cents" if direction == "income" else "expense_cents"
        day_bucket = daily.setdefault(local_day.isoformat(), {"income_cents": 0, "expense_cents": 0, "count": 0})
        day_bucket[key] += int(amount_cents)
        day_bucket["count"] += 1
        month_bucket = monthly.setdefault(local_day.strftime("%Y-%m"), {"income_cents": 0, "expense_cents": 0, "count": 0})
        month_bucket[key] += int(amount_cents)
        month_bucket["count"] += 1
    span_days = (spec.end - effective_start).days + 1 if effective_start else None
    if span_days is not None and span_days <= MAX_DAILY_SPAN_DAYS:
        summary["daily"] = dict(sorted(daily.items()))
    if span_days is None or span_days > 31 or spec.kind in {"year", "all"}:
        summary["monthly"] = dict(sorted(monthly.items()))
    if truncated:
        summary["buckets_truncated"] = True

    largest_expense_rows = db.execute(
        select(Transaction, Category.name)
        .outerjoin(Category, Transaction.category_id == Category.id)
        .where(*_base_filter(user_id, start_utc, end_utc, scope), Transaction.direction == "expense")
        .order_by(Transaction.amount_cents.desc(), Transaction.occurred_at.desc())
        .limit(TOP_TRANSACTIONS)
    ).all()
    largest_income_rows = db.execute(
        select(Transaction, Category.name)
        .outerjoin(Category, Transaction.category_id == Category.id)
        .where(*_base_filter(user_id, start_utc, end_utc, scope), Transaction.direction == "income")
        .order_by(Transaction.amount_cents.desc(), Transaction.occurred_at.desc())
        .limit(TOP_TRANSACTIONS)
    ).all()
    summary["largest_expenses"] = [_tx_payload(tx, name) for tx, name in largest_expense_rows]
    summary["largest_incomes"] = [_tx_payload(tx, name) for tx, name in largest_income_rows]

    if effective_start is not None:
        elapsed_end = min(spec.end, today)
        days_elapsed = max((elapsed_end - effective_start).days + 1, 0) if elapsed_end >= effective_start else 0
        summary["days_total"] = span_days
        summary["days_elapsed"] = days_elapsed
        if days_elapsed:
            summary["daily_average_expense_cents"] = round(expense_total / days_elapsed)
            summary["daily_average_income_cents"] = round(income_total / days_elapsed)

    previous = previous_period(spec) if compare else None
    if previous is not None:
        prev_start, prev_end = _bounds(previous)
        prev_totals = _totals(db, user_id, prev_start, prev_end, scope)
        summary["previous"] = {**previous.as_dict(), **prev_totals}
        summary["change"] = {
            "income_cents": summary["income_cents"] - prev_totals["income_cents"],
            "expense_cents": summary["expense_cents"] - prev_totals["expense_cents"],
            "net_cents": summary["net_cents"] - prev_totals["net_cents"],
        }
    return summary


# ---------------------------------------------------------------------------
# Deterministic answer/report text (offline fallback)
# ---------------------------------------------------------------------------


def _yuan(cents: int | None) -> str:
    value = (cents or 0) / 100
    return f"{value:,.2f} 元"


def _signed_yuan(cents: int) -> str:
    sign = "+" if cents > 0 else ("-" if cents < 0 else "")
    return f"{sign}{abs(cents) / 100:,.2f} 元"


def fallback_answer(summary: dict[str, Any]) -> str:
    """Short factual answer about a period, built only from the summary."""

    label = summary.get("period", {}).get("label", "该周期")
    count = summary.get("transaction_count", 0)
    if not count:
        return f"{label}还没有正常的收支记录。"
    lines = [
        f"{label}共 {count} 笔交易：收入 {_yuan(summary.get('income_cents'))}（{summary.get('income_count', 0)} 笔），"
        f"支出 {_yuan(summary.get('expense_cents'))}（{summary.get('expense_count', 0)} 笔），净收支 {_signed_yuan(summary.get('net_cents', 0))}。"
    ]
    top_expense = summary.get("top_expense_categories") or []
    if top_expense:
        lines.append("支出最多的分类：" + "、".join(f"{item['name']} {_yuan(item['amount_cents'])}（{item['share']:.0%}）" for item in top_expense[:3]) + "。")
    top_income = summary.get("top_income_categories") or []
    if top_income:
        lines.append("主要收入来源：" + "、".join(f"{item['name']} {_yuan(item['amount_cents'])}" for item in top_income[:3]) + "。")
    previous = summary.get("previous")
    change = summary.get("change")
    if previous and change and previous.get("transaction_count"):
        lines.append(
            f"与{previous.get('label', '上一周期')}相比：收入 {_signed_yuan(change['income_cents'])}，支出 {_signed_yuan(change['expense_cents'])}。"
        )
    return "\n".join(lines)


def fallback_report(summary: dict[str, Any]) -> str:
    """Structured plain-text income/expense report built from the summary."""

    period = summary.get("period", {})
    label = period.get("label", "该周期")
    lines = [f"【{label} 收支报告】"]
    count = summary.get("transaction_count", 0)
    if not count:
        lines.append("该周期暂无正常的收支记录，无法生成进一步分析。")
        return "\n".join(lines)
    lines.append("一、总览")
    lines.append(f"• 交易 {count} 笔，收入 {_yuan(summary.get('income_cents'))}，支出 {_yuan(summary.get('expense_cents'))}，净收支 {_signed_yuan(summary.get('net_cents', 0))}。")
    if summary.get("days_elapsed"):
        lines.append(f"• 已记录 {summary['days_elapsed']} 天，日均支出 {_yuan(summary.get('daily_average_expense_cents'))}，日均收入 {_yuan(summary.get('daily_average_income_cents'))}。")
    top_income = summary.get("top_income_categories") or []
    lines.append("二、收入结构")
    if top_income:
        for item in top_income[:5]:
            lines.append(f"• {item['name']}：{_yuan(item['amount_cents'])}，{item['count']} 笔，占比 {item['share']:.0%}")
    else:
        lines.append("• 该周期没有收入记录。")
    top_expense = summary.get("top_expense_categories") or []
    lines.append("三、支出结构")
    if top_expense:
        for item in top_expense[:5]:
            lines.append(f"• {item['name']}：{_yuan(item['amount_cents'])}，{item['count']} 笔，占比 {item['share']:.0%}")
    else:
        lines.append("• 该周期没有支出记录。")
    largest = summary.get("largest_expenses") or []
    if largest:
        lines.append("四、大额支出")
        for item in largest[:3]:
            note = f"，{item['notes']}" if item.get("notes") else ""
            lines.append(f"• {item['date']} {item['category']} {_yuan(item['amount_cents'])}{note}")
    previous = summary.get("previous")
    change = summary.get("change")
    if previous and change and previous.get("transaction_count"):
        lines.append("五、对比")
        lines.append(
            f"• 与{previous.get('label', '上一周期')}相比：收入 {_signed_yuan(change['income_cents'])}，支出 {_signed_yuan(change['expense_cents'])}，净收支 {_signed_yuan(change['net_cents'])}。"
        )
    lines.append("建议")
    net = summary.get("net_cents", 0)
    if net < 0:
        lines.append("• 该周期支出高于收入，建议检查大额支出并预留现金流。")
    elif top_expense and top_expense[0]["share"] >= 0.5:
        lines.append(f"• 支出集中在“{top_expense[0]['name']}”，占比超过一半，建议关注该分类的变化。")
    else:
        lines.append("• 收支结构较为均衡，继续按分类记录并定期核对账户余额。")
    return "\n".join(lines)
