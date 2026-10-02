from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.ai as ai_module
from app.ai import chat_about_finances, period_summary
from app.ai_insights import (
    detect_intent,
    fallback_answer,
    fallback_report,
    parse_period_text,
    previous_period,
    resolve_period,
    summarize_period,
)
from app.ai_schemas import AIChatRequest, AIConversationMessage
from app.ai_service import AIService
from app.config import Settings
from app.db import Base
from app.models import AIReport, Category, PaymentMethod, Transaction, User
from app.timezone import BUSINESS_TZ


TODAY = date(2026, 9, 18)


def _db() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return Session(engine)


def _beijing(day: date, hour: int = 12) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=BUSINESS_TZ).astimezone(timezone.utc)


def _fixtures(db: Session):
    user = User(username="insights", password_hash="hash")
    db.add(user)
    db.flush()
    food = Category(user_id=user.id, name="餐饮", direction="expense")
    rent = Category(user_id=user.id, name="房租", direction="expense")
    sales = Category(user_id=user.id, name="销售收入", direction="income")
    method = PaymentMethod(user_id=user.id, name="微信")
    db.add_all([food, rent, sales, method])
    db.flush()
    rows = [
        # This month (September 2026)
        Transaction(user_id=user.id, occurred_at=_beijing(date(2026, 9, 1)), kind="cashflow", direction="expense", amount_cents=200000, category_id=rent.id, payment_method_id=method.id, status="normal", notes="九月房租"),
        Transaction(user_id=user.id, occurred_at=_beijing(date(2026, 9, 2)), kind="cashflow", direction="expense", amount_cents=3500, category_id=food.id, payment_method_id=method.id, status="normal", notes="牛肉面"),
        Transaction(user_id=user.id, occurred_at=_beijing(date(2026, 9, 2), 20), kind="cashflow", direction="expense", amount_cents=6500, category_id=food.id, payment_method_id=method.id, status="normal"),
        Transaction(user_id=user.id, occurred_at=_beijing(date(2026, 9, 10)), kind="cashflow", direction="income", amount_cents=500000, category_id=sales.id, payment_method_id=method.id, status="normal", notes="客户货款"),
        # 00:30 Beijing on 9-11 is still 9-10 in UTC: must land in the 9-11 bucket.
        Transaction(user_id=user.id, occurred_at=_beijing(date(2026, 9, 11), 0) + timedelta(minutes=30), kind="cashflow", direction="expense", amount_cents=1000, category_id=food.id, payment_method_id=method.id, status="normal"),
        # Voided and transfer rows are ignored everywhere.
        Transaction(user_id=user.id, occurred_at=_beijing(date(2026, 9, 12)), kind="cashflow", direction="expense", amount_cents=99999, category_id=food.id, payment_method_id=method.id, status="voided"),
        Transaction(user_id=user.id, occurred_at=_beijing(date(2026, 9, 12)), kind="transfer", direction="expense", amount_cents=88888, category_id=None, payment_method_id=method.id, transfer_payment_method_id=method.id, status="normal"),
        # Last month
        Transaction(user_id=user.id, occurred_at=_beijing(date(2026, 8, 5)), kind="cashflow", direction="expense", amount_cents=150000, category_id=rent.id, payment_method_id=method.id, status="normal"),
        Transaction(user_id=user.id, occurred_at=_beijing(date(2026, 8, 20)), kind="cashflow", direction="income", amount_cents=300000, category_id=sales.id, payment_method_id=method.id, status="normal"),
        # Last year
        Transaction(user_id=user.id, occurred_at=_beijing(date(2025, 12, 31)), kind="cashflow", direction="income", amount_cents=100000, category_id=sales.id, payment_method_id=method.id, status="normal"),
    ]
    db.add_all(rows)
    db.commit()
    return user


def test_resolve_period_covers_month_year_and_all():
    month = resolve_period("month", today=TODAY)
    assert (month.start, month.end) == (date(2026, 9, 1), date(2026, 9, 30))
    assert month.label.startswith("本月")
    year = resolve_period("year", today=TODAY)
    assert (year.start, year.end) == (date(2026, 1, 1), date(2026, 12, 31))
    everything = resolve_period("all", today=TODAY)
    assert everything.start is None and everything.end == TODAY
    week = resolve_period("week", today=TODAY)
    assert week.start.weekday() == 0 and (week.end - week.start).days == 6
    with pytest.raises(ValueError):
        resolve_period("custom", date(2026, 9, 10), date(2026, 9, 1), today=TODAY)
    assert previous_period(month).start == date(2026, 8, 1)
    assert previous_period(year).end == date(2025, 12, 31)
    assert previous_period(everything) is None


@pytest.mark.parametrize(
    ("text", "kind", "start"),
    [
        ("本月收支怎么样", "month", date(2026, 9, 1)),
        ("这个月花了多少", "month", date(2026, 9, 1)),
        ("上个月支出", "month", date(2026, 8, 1)),
        ("今年赚了多少", "year", date(2026, 1, 1)),
        ("去年总收入", "year", date(2025, 1, 1)),
        ("全部收支情况", "all", None),
        ("累计收入多少", "all", None),
        ("今天花了多少", "day", TODAY),
        ("昨天的支出", "day", TODAY - timedelta(days=1)),
        ("8月的收支报告", "month", date(2026, 8, 1)),
        ("八月份支出", "month", date(2026, 8, 1)),
        ("2026年7月收支", "month", date(2026, 7, 1)),
        ("最近7天支出", "custom", TODAY - timedelta(days=6)),
        ("近三个月收入", "custom", date(2026, 7, 1)),
        ("本周花销", "week", date(2026, 9, 14)),
    ],
)
def test_parse_period_text(text, kind, start):
    spec = parse_period_text(text, TODAY)
    assert spec is not None, text
    assert spec.kind == kind
    assert spec.start == start


def test_parse_period_text_ignores_plain_bookkeeping():
    assert parse_period_text("微信35元吃了碗牛肉面", TODAY) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("今天午餐花了 35 元，微信支付", "bookkeeping"),
        ("微信35元吃了碗牛肉面", "bookkeeping"),
        ("客户A支付宝转账一万", "bookkeeping"),
        ("上个月房租2000", "bookkeeping"),
        ("支付宝给供应商A充值1000元，目前未结算余额1000元", "bookkeeping"),
        ("本月收支情况", "query"),
        ("这个月花了多少钱？", "query"),
        ("今年赚了多少", "query"),
        ("全部收入是多少", "query"),
        ("支出最多的分类是什么", "query"),
        ("生成本月收支报告", "report"),
        ("帮我分析一下今年的花销", "report"),
        ("做一份全部收支的总结", "report"),
        ("8月收支报告", "report"),
    ],
)
def test_detect_intent(text, expected):
    assert detect_intent(text) == expected


def test_detect_intent_uses_chat_context_for_short_follow_ups():
    assert detect_intent("那本年呢", True) == "query"
    assert detect_intent("上个月", True) == "query"
    assert detect_intent("上个月", False) == "bookkeeping"


def test_summarize_month_reports_exact_totals_categories_and_buckets():
    db = _db()
    user = _fixtures(db)
    summary = summarize_period(db, user.id, resolve_period("month", today=TODAY))

    assert summary["transaction_count"] == 5
    assert summary["income_cents"] == 500000
    assert summary["expense_cents"] == 211000
    assert summary["net_cents"] == 289000
    assert summary["categories"]["餐饮"] == {"income_cents": 0, "expense_cents": 11000, "count": 3}
    assert summary["top_expense_categories"][0]["name"] == "房租"
    assert summary["top_expense_categories"][0]["share"] == pytest.approx(200000 / 211000, abs=1e-4)
    assert summary["top_income_categories"][0]["name"] == "销售收入"
    assert summary["daily"]["2026-09-02"] == {"income_cents": 0, "expense_cents": 10000, "count": 2}
    # Beijing 00:30 belongs to 9-11 even though the UTC instant is on 9-10.
    assert summary["daily"]["2026-09-11"]["expense_cents"] == 1000
    assert "monthly" not in summary
    assert summary["largest_expenses"][0] == {"date": "2026-09-01", "amount_cents": 200000, "category": "房租", "notes": "九月房租"}
    assert summary["previous"]["income_cents"] == 300000
    assert summary["change"] == {"income_cents": 200000, "expense_cents": 61000, "net_cents": 139000}
    assert summary["period"]["label"].startswith("本月")


def test_summarize_all_uses_first_transaction_and_monthly_buckets():
    db = _db()
    user = _fixtures(db)
    summary = summarize_period(db, user.id, resolve_period("all", today=TODAY))

    assert summary["period"]["start_date"] == "2025-12-31"
    assert summary["income_cents"] == 900000
    assert summary["expense_cents"] == 361000
    assert set(summary["monthly"]) == {"2025-12", "2026-08", "2026-09"}
    assert "daily" not in summary
    assert "previous" not in summary


def test_summarize_year_compares_with_previous_year():
    db = _db()
    user = _fixtures(db)
    summary = summarize_period(db, user.id, resolve_period("year", today=TODAY))

    assert summary["income_cents"] == 800000
    assert summary["previous"]["income_cents"] == 100000
    assert summary["monthly"]["2026-09"]["expense_cents"] == 211000


def test_fallback_texts_use_real_numbers():
    db = _db()
    user = _fixtures(db)
    summary = summarize_period(db, user.id, resolve_period("month", today=TODAY))
    answer = fallback_answer(summary)
    assert "收入 5,000.00 元" in answer and "支出 2,110.00 元" in answer
    assert "房租" in answer
    report = fallback_report(summary)
    assert report.startswith("【本月")
    assert "收入结构" in report and "支出结构" in report and "九月房租" in report
    empty = fallback_answer({"period": {"label": "今天"}, "transaction_count": 0})
    assert "还没有" in empty


def test_chat_endpoint_returns_bookkeeping_for_transactions_without_model_call(monkeypatch):
    db = _db()
    user = _fixtures(db)
    service = AIService(Settings(_env_file=None, secret_key="s" * 64, ai_api_key="sk-test"))

    def fail_chat(*args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("bookkeeping text must not reach the model")

    monkeypatch.setattr(service, "_chat", fail_chat)
    monkeypatch.setattr(ai_module, "service", service)
    monkeypatch.setattr(ai_module, "_user", lambda request, session: user)
    response = chat_about_finances(AIChatRequest(text="今天午餐花了 35 元，微信支付"), None, db)
    assert response.intent == "bookkeeping"
    assert response.reply is None
    assert db.query(Transaction).count() == 10


def test_chat_endpoint_answers_query_from_aggregated_data(monkeypatch):
    db = _db()
    user = _fixtures(db)
    service = AIService(Settings(_env_file=None, secret_key="s" * 64, ai_api_key="sk-test"))
    captured = {}

    def fake_chat(provider, messages, **kwargs):
        captured["messages"] = messages
        return "本月收入 5,000.00 元，支出 2,110.00 元。"

    monkeypatch.setattr(service, "_chat", fake_chat)
    monkeypatch.setattr(ai_module, "service", service)
    monkeypatch.setattr(ai_module, "_user", lambda request, session: user)
    reference = datetime(2026, 9, 18, 3, tzinfo=timezone.utc)
    response = chat_about_finances(AIChatRequest(text="本月收支怎么样？", reference_time=reference), None, db)

    assert response.intent == "query"
    assert response.source == "model"
    assert response.period.kind == "month"
    assert response.period.start_date == date(2026, 9, 1)
    assert response.summary["income_cents"] == 500000
    assert response.report_id is None
    system = captured["messages"][0]["content"]
    assert "以“分”为单位" in system
    assert '"income_cents": 500000' in system
    assert captured["messages"][-1] == {"role": "user", "content": "本月收支怎么样？"}
    assert db.query(AIReport).count() == 0


def test_chat_endpoint_generates_report_saves_history_and_falls_back_offline(monkeypatch):
    db = _db()
    user = _fixtures(db)
    service = AIService(Settings(_env_file=None, secret_key="s" * 64, ai_api_key=None))
    monkeypatch.setattr(ai_module, "service", service)
    monkeypatch.setattr(ai_module, "_user", lambda request, session: user)
    reference = datetime(2026, 9, 18, 3, tzinfo=timezone.utc)
    response = chat_about_finances(AIChatRequest(text="生成今年的收支报告", reference_time=reference), None, db)

    assert response.intent == "report"
    assert response.source == "fallback"
    assert response.warning and "本地" in response.warning
    assert response.reply.startswith("【本年")
    assert response.report_id is not None
    saved = db.get(AIReport, response.report_id)
    assert saved.period == "year"
    assert saved.source == "fallback"
    assert json.loads(saved.request_summary)["income_cents"] == 800000


def test_chat_endpoint_reuses_period_from_earlier_user_turn(monkeypatch):
    db = _db()
    user = _fixtures(db)
    service = AIService(Settings(_env_file=None, secret_key="s" * 64, ai_api_key=None))
    monkeypatch.setattr(ai_module, "service", service)
    monkeypatch.setattr(ai_module, "_user", lambda request, session: user)
    reference = datetime(2026, 9, 18, 3, tzinfo=timezone.utc)
    conversation = [
        AIConversationMessage(role="user", content="上个月收支怎么样"),
        AIConversationMessage(role="assistant", content="上月收入 3,000.00 元。"),
    ]
    response = chat_about_finances(AIChatRequest(text="那支出最多的是什么？", conversation=conversation, reference_time=reference), None, db)
    assert response.intent == "query"
    assert response.period.start_date == date(2026, 8, 1)
    assert response.summary["expense_cents"] == 150000


def test_summary_endpoint_returns_month_figures_for_charts(monkeypatch):
    db = _db()
    user = _fixtures(db)
    monkeypatch.setattr(ai_module, "_user", lambda request, session: user)
    monkeypatch.setattr(ai_module, "business_today", lambda: TODAY)
    monkeypatch.setattr("app.ai_insights.business_today", lambda: TODAY)
    response = period_summary(None, db, period="month", start_date=None, end_date=None)
    assert response.period.kind == "month"
    assert response.summary["income_cents"] == 500000
    assert "daily" in response.summary
