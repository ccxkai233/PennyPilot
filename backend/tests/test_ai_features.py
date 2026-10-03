from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from types import SimpleNamespace

import anthropic
import httpx2

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.ai import confirm_ai_draft, confirm_ai_drafts
from app.ai_schemas import AIBatchConfirmRequest, AIConfirmRequest, AIParsedTransaction
from app.ai_service import (
    AI_PARSE_MAX_TOKENS,
    AI_PARSE_RESPONSE_FORMAT,
    AIService,
    AIServiceError,
    Provider,
    _api_root,
    _conversation_turns,
    _parse_time,
    decrypt_api_key,
    encrypt_api_key,
    reasoning_controls_for_provider,
    response_format_for_provider,
)
from app.config import Settings
from app.db import Base
from app.models import AIConfig, AIConversation, AIConversationMessage, AIReport, Category, Partner, PartnerLedgerEntry, PaymentMethod, Transaction, User
from app.schemas import TransactionCreate, TransactionUpdate
import app.ai as ai_module
import app.accounting as accounting_module


def test_ai_relative_dates_use_beijing_business_day():
    # 16:30Z is already 00:30 on the next day in Beijing.  “昨天晚上八点”
    # must therefore resolve to the preceding Beijing date, not the preceding
    # UTC date.
    reference = datetime(2026, 8, 2, 16, 30, tzinfo=timezone.utc)
    parsed = _parse_time("昨天晚上八点", reference)

    assert parsed.astimezone(timezone.utc) == datetime(2026, 8, 2, 12, tzinfo=timezone.utc)


def _db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _fixtures(db: Session):
    user = User(username="ai-test", password_hash="hash")
    db.add(user)
    db.flush()
    category = Category(user_id=user.id, name="进货", direction="expense")
    method = PaymentMethod(user_id=user.id, name="微信")
    partner = Partner(user_id=user.id, type="supplier", name="供应商 A", credit_limit_cents=1000)
    db.add_all([category, method, partner])
    db.commit()
    return user, category, method, partner


def test_ai_key_is_encrypted_and_round_trips():
    settings = Settings(_env_file=None, secret_key="s" * 64)
    ciphertext = encrypt_api_key("sk-test-secret", settings)
    assert "sk-test-secret" not in ciphertext
    assert decrypt_api_key(ciphertext, settings) == "sk-test-secret"


def test_response_format_follows_model_family():
    deepseek = Provider("fallback", "https://api.deepseek.com", "sk-test", "deepseek-v4-flash")
    gpt = Provider("primary", "https://gateway.example", "sk-test", "gpt-5.6-luna")

    assert response_format_for_provider(deepseek, AI_PARSE_RESPONSE_FORMAT) == {"type": "json_object"}
    assert response_format_for_provider(gpt, AI_PARSE_RESPONSE_FORMAT) == AI_PARSE_RESPONSE_FORMAT
    assert response_format_for_provider(gpt, None) is None


def test_reasoning_is_disabled_for_supported_model_families():
    deepseek = Provider("primary", "https://api.deepseek.com", "sk-test", "deepseek-v4-flash")
    gpt = Provider("fallback", "https://gateway.example", "sk-test", "gpt-5.6-luna")
    legacy = Provider("primary", "https://gateway.example", "sk-test", "gpt-4o-mini")

    assert reasoning_controls_for_provider(deepseek) == {"thinking": {"type": "disabled"}}
    assert reasoning_controls_for_provider(gpt) == {"reasoning_effort": "none"}
    assert reasoning_controls_for_provider(legacy) == {}
    # GPT-6 cannot disable reasoning; "low" is the fastest level it accepts.
    gpt6 = Provider("primary", "https://gateway.example", "sk-test", "gpt-6-luna")
    assert reasoning_controls_for_provider(gpt6) == {"reasoning_effort": "low"}
    # Ledger questions and reports ask every family for its deepest reasoning.
    assert reasoning_controls_for_provider(gpt6, "high") == {"reasoning_effort": "high"}
    assert reasoning_controls_for_provider(gpt, "high") == {"reasoning_effort": "high"}
    assert reasoning_controls_for_provider(deepseek, "high") == {"thinking": {"type": "enabled"}}
    assert reasoning_controls_for_provider(legacy, "high") == {}


def test_deepseek_json_mode_retries_empty_content_and_sets_token_limit(monkeypatch):
    service = AIService(
        Settings(_env_file=None, secret_key="s" * 64, ai_api_key="sk-test", ai_timeout_seconds=2)
    )
    provider = Provider("fallback", "https://api.deepseek.com", "sk-test", "deepseek-v4-flash")
    captured_payloads = []

    class FakeResponse:
        status_code = 200

        def __init__(self, content):
            self.content = content

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def iter_bytes(self):
            return [json.dumps({"choices": [{"message": {"content": self.content}}]}).encode()]

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def stream(self, method, endpoint, *, headers, json):
            captured_payloads.append(json)
            return FakeResponse("" if len(captured_payloads) == 1 else '{"ok":true}')

    monkeypatch.setattr("app.ai_service.httpx.Client", FakeClient)
    content = service._chat(
        provider,
        [{"role": "system", "content": "Output valid json."}],
        max_tokens=AI_PARSE_MAX_TOKENS,
        response_format=AI_PARSE_RESPONSE_FORMAT,
    )

    assert content == '{"ok":true}'
    assert len(captured_payloads) == 2
    assert all(payload["response_format"] == {"type": "json_object"} for payload in captured_payloads)
    assert all(payload["max_tokens"] == AI_PARSE_MAX_TOKENS for payload in captured_payloads)
    assert all(payload["thinking"] == {"type": "disabled"} for payload in captured_payloads)
    assert all("reasoning_effort" not in payload for payload in captured_payloads)


def test_fallback_parse_does_not_write_a_transaction():
    db = _db()
    user, category, method, _ = _fixtures(db)
    service = AIService(Settings(_env_file=None, secret_key="s" * 64, ai_api_key=None))
    result = service.parse(db, user.id, "微信进货花了35元")
    assert result.source == "fallback"
    assert result.parsed.amount_cents == 3500
    assert result.parsed.category_id == category.id
    assert result.parsed.payment_method_id == method.id
    assert result.parsed.notes == "微信进货花了35元"
    assert db.query(Transaction).count() == 0


@pytest.mark.parametrize(
    ("text_value", "expected_notes"),
    [
        ("微信进货花了35元，备注招待客户", "招待客户"),
        ("微信进货花了35元，备注是招待客户", "招待客户"),
        ("微信进货花了35元，备注：招待客户。", "招待客户"),
    ],
)
def test_fallback_parse_extracts_explicit_notes(text_value, expected_notes):
    db = _db()
    user, _, _, _ = _fixtures(db)
    service = AIService(Settings(_env_file=None, secret_key="s" * 64, ai_api_key=None))
    result = service.parse(db, user.id, text_value)
    assert result.source == "fallback"
    assert result.parsed.notes == expected_notes


def test_model_parse_discards_untrusted_field_status_and_recomputes_missing(monkeypatch):
    db = _db()
    user, category, method, _ = _fixtures(db)
    service = AIService(
        Settings(_env_file=None, secret_key="s" * 64, ai_api_key="sk-test")
    )
    reference = datetime(2026, 8, 3, 9, 30, tzinfo=timezone.utc)
    captured = {}
    provider_result = {
        "status": "need_more_info",
        "parsed": {
            "occurred_at": None,
            "direction": "expense",
            "amount_cents": 3500,
            "category_name": "进货",
            "payment_method_name": "微信",
            "partner_name": None,
            "notes": "采购耗材",
            # OpenAI-compatible providers do not consistently follow the
            # requested enum.  These values must never force local fallback.
            "field_status": {
                "direction": "confirmed",
                "amount_cents": "known",
                "category": "present",
            },
        },
        "missing_fields": [
            "occurred_at",
            "category_name",
            "payment_method_name",
            "partner_name",
        ],
        "follow_up_question": "请补充时间、分类、支付方式和往来账户。",
        "brief_comment": "  这笔进货支出会更新微信账户余额，确认前请核对分类。  ",
    }

    def fake_chat(provider, messages, **kwargs):
        captured["system"] = messages[0]["content"]
        return json.dumps(provider_result, ensure_ascii=False)

    monkeypatch.setattr(service, "_chat", fake_chat)
    result = service.parse(
        db,
        user.id,
        "微信进货花了35元，备注采购耗材",
        reference_time=reference,
    )

    assert result.source == "model"
    assert result.status == "complete"
    assert result.missing_fields == []
    assert result.follow_up_question is None
    assert result.brief_comment == "这笔进货支出会更新微信账户余额，确认前请核对分类。"
    assert result.parsed.occurred_at == reference
    assert result.parsed.category_id == category.id
    assert result.parsed.payment_method_id == method.id
    assert result.parsed.field_status == {
        "occurred_at": "inferred",
        "direction": "explicit",
        "amount_cents": "explicit",
        "category": "explicit",
        "payment_method": "explicit",
        "partner": "inferred",
    }
    assert "reference_time=2026-08-03T09:30:00+00:00" in captured["system"]
    assert "confirmed、known、present" in captured["system"]
    assert "missing_fields 中仅允许" in captured["system"]
    assert "assistant 消息中的金额、日期、账户、分类或示例" in captured["system"]
    assert "brief_comment 必须" in captured["system"]
    assert "绝不执行入账" not in captured["system"]
    assert "不要求用户使用‘备注/说明/用途’等关键词" in captured["system"]
    assert "notes=null 不属于必填缺失字段" in captured["system"]
    assert "若 notes=null，必须在 brief_comment 中顺带礼貌询问" in captured["system"]
    assert "notes=‘两颗卤蛋’，不能只写‘卤蛋’" in captured["system"]


def test_model_parse_uses_bounded_multiturn_context_and_returns_one_comment(monkeypatch):
    db = _db()
    user, category, method, _ = _fixtures(db)
    service = AIService(
        Settings(_env_file=None, secret_key="s" * 64, ai_api_key="sk-test")
    )
    captured = {}
    provider_result = {
        "status": "complete",
        "parsed": {
            "occurred_at": None,
            "kind": "cashflow",
            "direction": "expense",
            "amount_cents": 4200,
            "category_name": "进货",
            "payment_method_name": "微信",
            "partner_name": None,
            "notes": "补库存",
            "field_status": {},
        },
        "missing_fields": [],
        "follow_up_question": None,
        "brief_comment": "这笔进货支出将从微信账户计入成本，备注已保留为补库存。",
    }

    def fake_chat(provider, messages, **kwargs):
        captured["messages"] = messages
        return json.dumps(provider_result, ensure_ascii=False)

    monkeypatch.setattr(service, "_chat", fake_chat)
    result = service.parse(
        db,
        user.id,
        "金额改成42元",
        conversation=[
            {"role": "user", "content": "今天进货花了35元，备注补库存"},
            {"role": "assistant", "content": "请补充支付账户，例如支付宝8000元。"},
            {"role": "user", "content": "用微信支付"},
        ],
        reference_time=datetime(2026, 8, 3, 9, 30, tzinfo=timezone.utc),
    )

    assert [message["role"] for message in captured["messages"]] == [
        "system", "user", "assistant", "user", "user"
    ]
    assert captured["messages"][-1]["content"] == "金额改成42元"
    assert result.parsed.amount_cents == 4200
    assert result.parsed.category_id == category.id
    assert result.parsed.payment_method_id == method.id
    assert result.brief_comment == provider_result["brief_comment"]


def test_model_parse_self_corrects_empty_customer_settlement_shorthand(monkeypatch):
    db = _db()
    user, _, _, _ = _fixtures(db)
    category = Category(user_id=user.id, name="其他收入", direction="income")
    method = PaymentMethod(user_id=user.id, name="支付宝")
    customer = Partner(user_id=user.id, type="customer", name="风雨", credit_used_cents=1_000_000)
    db.add_all([category, method, customer])
    db.commit()
    service = AIService(Settings(_env_file=None, secret_key="s" * 64, ai_api_key="sk-test"))
    responses = [
        {
            "status": "need_more_info",
            "parsed": {"occurred_at": None, "kind": "cashflow", "field_status": {}},
            "missing_fields": ["direction", "amount_cents", "category", "payment_method"],
            "follow_up_question": "请补充信息。",
            "brief_comment": "风雨通过支付宝转账一万元并已结清。",
        },
        {
            "status": "complete",
            "parsed": {
                "occurred_at": None,
                "kind": "cashflow",
                "direction": "income",
                "amount_cents": 1_000_000,
                "category_name": "其他收入",
                "payment_method_name": "支付宝",
                "partner_name": "风雨",
                "partner_ledger_type": "balance_check",
                "partner_ledger_amount_cents": 0,
                "partner_balance_after_cents": 0,
                "partner_balance_kind": "credit_used",
                "notes": "客户结算款",
                "field_status": {},
            },
            "missing_fields": [],
            "follow_up_question": None,
            "brief_comment": "这笔支付宝收款会同步结清风雨的未结算余额。",
        },
    ]
    captured_messages = []

    def fake_chat(provider, messages, **kwargs):
        captured_messages.append(messages)
        return json.dumps(responses[len(captured_messages) - 1], ensure_ascii=False)

    monkeypatch.setattr(service, "_chat", fake_chat)
    result = service.parse(db, user.id, "风雨支付宝转账一万，已结清", mode="combined")

    assert len(captured_messages) == 2
    assert "常用省略表达" in captured_messages[0][0]["content"]
    assert "余额为零" in captured_messages[1][-1]["content"]
    assert result.status == "complete"
    assert result.parsed.direction == "income"
    assert result.parsed.amount_cents == 1_000_000
    assert result.parsed.category_id == category.id
    assert result.parsed.payment_method_id == method.id
    assert result.parsed.partner_id == customer.id
    assert result.parsed.partner_ledger_type == "balance_check"
    assert result.parsed.partner_ledger_amount_cents == 0
    assert result.parsed.partner_balance_after_cents == 0
    assert result.parsed.partner_balance_kind == "credit_used"


def test_model_parse_normalizes_partner_type_aliases_in_combined_response(monkeypatch):
    db = _db()
    user, _, _, partner = _fixtures(db)
    service = AIService(
        Settings(_env_file=None, secret_key="s" * 64, ai_api_key="sk-test")
    )
    provider_result = {
        "status": "complete",
        "parsed": {
            "occurred_at": None,
            "kind": "cashflow",
            "direction": None,
            "amount_cents": None,
            "partner_id": partner.id,
            "partner_name": partner.name,
            # This is the malformed shape returned by the compatible gateway.
            "partner_ledger_type": "supplier",
            "partner_ledger_amount_cents": 0,
            "partner_balance_after_cents": 100000,
            "partner_balance_kind": "balance_check",
            "field_status": {},
        },
        "missing_fields": [],
        "follow_up_question": None,
    }
    monkeypatch.setattr(
        service,
        "_chat",
        lambda provider, messages, **kwargs: json.dumps(provider_result, ensure_ascii=False),
    )

    result = service.parse(
        db,
        user.id,
        "给供应商 A 充值1000元，目前未结算余额1000元",
        mode="combined",
    )

    assert result.status == "need_more_info"
    assert result.parsed.partner_ledger_type == "balance_check"
    assert result.parsed.partner_balance_kind == "prepaid_balance"


def test_model_parse_falls_back_to_secondary_provider(monkeypatch):
    db = _db()
    user, category, method, _ = _fixtures(db)
    service = AIService(
        Settings(
            _env_file=None,
            secret_key="s" * 64,
            ai_api_key="sk-primary",
            ai_fallback_base_url="https://backup.example",
            ai_fallback_api_key="sk-backup",
            ai_fallback_model="gpt-4o-mini",
            ai_local_fallback=False,
        )
    )
    calls = []
    provider_result = {
        "status": "complete",
        "parsed": {
            "occurred_at": None,
            "kind": "cashflow",
            "direction": "expense",
            "amount_cents": 3500,
            "category_name": "进货",
            "payment_method_name": "微信",
            "partner_name": None,
            "notes": "采购耗材",
            "field_status": {},
        },
        "missing_fields": [],
        "follow_up_question": None,
    }

    def fake_chat(provider, messages, **kwargs):
        calls.append(provider.name)
        if provider.name == "primary":
            raise AIServiceError("provider_http_error")
        return json.dumps(provider_result, ensure_ascii=False)

    monkeypatch.setattr(service, "_chat", fake_chat)
    result = service.parse(
        db,
        user.id,
        "微信进货花了35元，备注采购耗材",
        reference_time=datetime(2026, 8, 3, 9, 30, tzinfo=timezone.utc),
    )

    assert calls == ["primary", "fallback"]
    assert result.source == "model"
    assert result.warning and "备用通道" in result.warning
    assert result.parsed.category_id == category.id
    assert result.parsed.payment_method_id == method.id


def test_fallback_parse_supports_chinese_current_account_amounts():
    db = _db()
    user, _, _, partner = _fixtures(db)
    service = AIService(Settings(_env_file=None, secret_key="s" * 64, ai_api_key=None))
    result = service.parse(db, user.id, "给供应商 A 充了两万预存")
    assert result.source == "fallback"
    assert result.parsed.partner_id == partner.id
    assert result.parsed.amount_cents == 2_000_000
    assert result.parsed.partner_ledger_type == "prepaid_in"
    assert db.query(Transaction).count() == 0


def test_fallback_parse_maps_salary_to_income_category():
    db = _db()
    user, _, method, _ = _fixtures(db)
    salary = Category(user_id=user.id, name="工资收入", direction="income")
    db.add(salary)
    db.commit()
    service = AIService(Settings(_env_file=None, secret_key="s" * 64, ai_api_key=None))

    result = service.parse(db, user.id, "今天收到工资 8000 元，微信")

    assert result.source == "fallback"
    assert result.status == "complete"
    assert result.parsed.direction == "income"
    assert result.parsed.amount_cents == 800_000
    assert result.parsed.category_id == salary.id
    assert result.parsed.payment_method_id == method.id


def test_liability_cashflow_increases_debt_balance(monkeypatch):
    db = _db()
    user, category, _, _ = _fixtures(db)
    card = PaymentMethod(
        user_id=user.id,
        name="招商银行信用卡",
        account_role="liability",
        track_balance=True,
        current_balance_cents=0,
    )
    db.add(card)
    db.commit()
    monkeypatch.setattr(accounting_module, "_user", lambda request, session: user)

    response = accounting_module.create_transaction(
        TransactionCreate(
            direction="expense",
            amount_cents=20_000,
            category_id=category.id,
            payment_method_id=card.id,
            source="manual",
        ),
        None,
        db,
    )

    assert response["kind"] == "cashflow"
    assert db.get(PaymentMethod, card.id).current_balance_cents == 20_000


def test_fallback_parse_treats_jd_baitiao_debt_as_liability_cashflow():
    db = _db()
    user, _, _, _ = _fixtures(db)
    other = Category(user_id=user.id, name="其他支出", direction="expense")
    baitiao = PaymentMethod(
        user_id=user.id,
        name="京东白条",
        account_role="liability",
        track_balance=True,
        current_balance_cents=0,
    )
    db.add_all([other, baitiao])
    db.commit()
    service = AIService(Settings(_env_file=None, secret_key="s" * 64, ai_api_key=None))

    result = service.parse(db, user.id, "京东白条目前欠款11.47元，帮我入账")

    assert result.status == "complete"
    assert result.parsed.kind == "cashflow"
    assert result.parsed.direction == "expense"
    assert result.parsed.amount_cents == 1_147
    assert result.parsed.category_id == other.id
    assert result.parsed.payment_method_id == baitiao.id
    assert result.parsed.partner_id is None


def test_transfer_repayment_decreases_cash_and_liability_balances(monkeypatch):
    db = _db()
    user, _, _, _ = _fixtures(db)
    cash = PaymentMethod(
        user_id=user.id,
        name="支付宝",
        account_role="cash",
        track_balance=True,
        current_balance_cents=100_000,
    )
    card = PaymentMethod(
        user_id=user.id,
        name="上海银行信用卡",
        account_role="liability",
        track_balance=True,
        current_balance_cents=50_000,
    )
    db.add_all([cash, card])
    db.commit()
    monkeypatch.setattr(accounting_module, "_user", lambda request, session: user)

    response = accounting_module.create_transaction(
        TransactionCreate(
            kind="transfer",
            direction="expense",
            amount_cents=20_000,
            payment_method_id=cash.id,
            transfer_payment_method_id=card.id,
            source="manual",
        ),
        None,
        db,
    )

    assert response["kind"] == "transfer"
    assert response["category_id"] is None
    assert response["transfer_payment_method_id"] == card.id
    assert db.get(PaymentMethod, cash.id).current_balance_cents == 80_000
    assert db.get(PaymentMethod, card.id).current_balance_cents == 30_000


def test_fallback_parse_detects_credit_card_repayment_transfer():
    db = _db()
    user, _, _, _ = _fixtures(db)
    cash = PaymentMethod(user_id=user.id, name="支付宝", account_role="cash", track_balance=True)
    card = PaymentMethod(user_id=user.id, name="招商银行信用卡", account_role="liability", track_balance=True)
    db.add_all([cash, card])
    db.commit()
    service = AIService(Settings(_env_file=None, secret_key="s" * 64, ai_api_key=None))

    result = service.parse(db, user.id, "支付宝还招商银行信用卡 500 元")

    assert result.status == "complete"
    assert result.parsed.kind == "transfer"
    assert result.parsed.direction == "expense"
    assert result.parsed.amount_cents == 50_000
    assert result.parsed.category_id is None
    assert result.parsed.payment_method_id == cash.id
    assert result.parsed.transfer_payment_method_id == card.id


def test_fallback_parse_merges_user_follow_up_without_using_assistant_text():
    db = _db()
    user, category, method, _ = _fixtures(db)
    service = AIService(Settings(_env_file=None, secret_key="s" * 64, ai_api_key=None))
    first = service.parse(db, user.id, "今天进货花了35元，备注补库存")
    assert first.status == "need_more_info"
    second = service.parse(
        db,
        user.id,
        "用微信支付",
        conversation=[
            {"role": "user", "content": "今天进货花了35元，备注补库存"},
            # The assistant's example number must not be treated as a new
            # amount by the local fallback parser.
            {"role": "assistant", "content": "请补充支付方式（例如支付宝 8000 元）。"},
        ],
    )
    assert second.status == "complete"
    assert second.parsed.amount_cents == 3500
    assert second.parsed.category_id == category.id
    assert second.parsed.payment_method_id == method.id
    assert second.parsed.notes == "补库存"


def test_confirm_requires_literal_true():
    draft = AIParsedTransaction(direction="expense", amount_cents=100, category_id=1, payment_method_id=1)
    with pytest.raises(ValidationError):
        AIConfirmRequest(confirm=False, draft=draft)


def test_confirm_atomically_writes_transaction_and_partner_ledger(monkeypatch):
    db = _db()
    user, category, method, partner = _fixtures(db)
    service = AIService(Settings(_env_file=None, secret_key="s" * 64, ai_api_key=None))
    monkeypatch.setattr(ai_module, "service", service)
    monkeypatch.setattr(ai_module, "_user", lambda request, session: user)
    payload = AIConfirmRequest(
        confirm=True,
        draft=AIParsedTransaction(
            occurred_at=datetime.now(timezone.utc),
            direction="expense",
            amount_cents=500,
            category_id=category.id,
            payment_method_id=method.id,
            partner_id=partner.id,
            partner_ledger_type="prepaid_in",
            partner_ledger_amount_cents=500,
        ),
    )
    response = confirm_ai_draft(payload, None, db)
    assert response.transaction["source"] == "ai"
    assert response.partner_ledger["transaction_id"] == response.transaction["id"]
    assert db.query(Transaction).count() == 1
    assert db.query(PartnerLedgerEntry).count() == 1
    assert db.get(Partner, partner.id).prepaid_balance_cents == 500


def test_ai_confirm_transfer_updates_both_financial_accounts(monkeypatch):
    db = _db()
    user, _, _, _ = _fixtures(db)
    cash = PaymentMethod(
        user_id=user.id,
        name="支付宝",
        account_role="cash",
        track_balance=True,
        current_balance_cents=100_000,
    )
    card = PaymentMethod(
        user_id=user.id,
        name="招商银行信用卡",
        account_role="liability",
        track_balance=True,
        current_balance_cents=60_000,
    )
    db.add_all([cash, card])
    db.commit()
    service = AIService(Settings(_env_file=None, secret_key="s" * 64, ai_api_key=None))
    monkeypatch.setattr(ai_module, "service", service)
    monkeypatch.setattr(ai_module, "_user", lambda request, session: user)

    payload = AIConfirmRequest(
        confirm=True,
        draft=AIParsedTransaction(
            kind="transfer",
            direction="expense",
            amount_cents=20_000,
            payment_method_id=cash.id,
            transfer_payment_method_id=card.id,
            notes="信用卡还款",
        ),
    )

    response = confirm_ai_draft(payload, None, db)

    assert response.transaction["kind"] == "transfer"
    assert response.transaction["transfer_payment_method_id"] == card.id
    assert response.partner_ledger is None
    assert db.get(PaymentMethod, cash.id).current_balance_cents == 80_000
    assert db.get(PaymentMethod, card.id).current_balance_cents == 40_000


def test_partner_mode_writes_only_ledger_and_reconciles_observed_unsettled_balance(monkeypatch):
    db = _db()
    user, _, _, _ = _fixtures(db)
    partner = Partner(user_id=user.id, type="customer", name="客户额度", credit_limit_cents=2000, credit_used_cents=1000)
    db.add(partner)
    db.commit()
    monkeypatch.setattr(ai_module, "_user", lambda request, session: user)
    payload = AIConfirmRequest(
        confirm=True,
        mode="partner",
        draft=AIParsedTransaction(
            partner_id=partner.id,
            partner_ledger_type="balance_check",
            partner_ledger_amount_cents=0,
            partner_balance_after_cents=1500,
            partner_balance_kind="credit_used",
        ),
        partner_ledger_type="balance_check",
        partner_ledger_amount_cents=0,
        observed_balance_cents=1500,
        observed_balance_kind="credit_used",
        apply_balance_reconciliation=True,
    )
    response = confirm_ai_draft(payload, None, db)
    assert response.mode == "partner"
    assert response.transaction is None
    assert response.partner_ledger["entry_type"] == "balance_check"
    assert response.balance_reconciliation["delta_cents"] == 500
    assert db.query(Transaction).count() == 0
    assert db.get(Partner, partner.id).credit_used_cents == 1500


def test_partner_parse_separates_current_balance_from_legacy_change_words():
    db = _db()
    user, _, _, partner = _fixtures(db)
    service = AIService(Settings(_env_file=None, secret_key="s" * 64, ai_api_key=None))
    result = service.parse(db, user.id, "给供应商 A 增加500元预存，目前余额1500元", mode="partner")
    assert result.mode == "partner"
    assert result.parsed.partner_ledger_type == "balance_check"
    assert result.parsed.partner_ledger_amount_cents == 0
    assert result.parsed.partner_balance_after_cents == 150000


def test_partner_parse_customer_credit_grant_keeps_post_balance_as_observation():
    db = _db()
    user, _, _, _ = _fixtures(db)
    customer = Partner(user_id=user.id, type="customer", name="客户 X", credit_limit_cents=10_000)
    db.add(customer)
    db.commit()
    service = AIService(Settings(_env_file=None, secret_key="s" * 64, ai_api_key=None))

    result = service.parse(
        db,
        user.id,
        "给客户 X 增加 5000 授信，目前余额 12000",
        mode="partner",
    )

    assert result.status == "complete"
    assert result.parsed.partner_id == customer.id
    assert result.parsed.partner_ledger_type == "balance_check"
    assert result.parsed.partner_ledger_amount_cents == 0
    assert result.parsed.partner_balance_after_cents == 1_200_000
    assert result.parsed.partner_balance_kind == "credit_used"
    assert result.parsed.direction is None
    assert result.parsed.category_id is None
    assert result.parsed.payment_method_id is None


def test_partner_parse_supplier_outstanding_balance_uses_credit_used():
    db = _db()
    user, _, _, partner = _fixtures(db)
    service = AIService(Settings(_env_file=None, secret_key="s" * 64, ai_api_key=None))

    result = service.parse(
        db,
        user.id,
        "供应商 A 未结算余额 10000",
        mode="partner",
    )

    assert result.status == "complete"
    assert result.parsed.partner_id == partner.id
    assert result.parsed.partner_ledger_type == "balance_check"
    assert result.parsed.partner_ledger_amount_cents == 0
    assert result.parsed.partner_balance_after_cents == 1_000_000
    assert result.parsed.partner_balance_kind == "prepaid_balance"


def test_partner_parse_balance_report_is_zero_movement():
    db = _db()
    user, _, _, partner = _fixtures(db)
    service = AIService(Settings(_env_file=None, secret_key="s" * 64, ai_api_key=None))

    result = service.parse(
        db,
        user.id,
        "供应商 A 网站现在余额 760 元，上次确认 1000 元",
        mode="partner",
    )

    assert result.status == "complete"
    assert result.parsed.partner_id == partner.id
    assert result.parsed.partner_ledger_type == "balance_check"
    assert result.parsed.partner_ledger_amount_cents == 0
    assert result.parsed.amount_cents is None
    assert result.parsed.partner_balance_after_cents == 76_000
    assert result.parsed.partner_balance_kind == "prepaid_balance"


def test_partner_balance_check_does_not_change_balance_and_can_be_reconciled(monkeypatch):
    db = _db()
    user, _, _, partner = _fixtures(db)
    monkeypatch.setattr(ai_module, "_user", lambda request, session: user)

    payload = AIConfirmRequest(
        confirm=True,
        mode="partner",
        draft={
            "occurred_at": datetime.now(timezone.utc),
            "partner_id": partner.id,
            "partner_ledger_type": "balance_check",
            "partner_ledger_amount_cents": 0,
            "partner_balance_after_cents": 76_000,
            "partner_balance_kind": "prepaid_balance",
        },
        partner_ledger_type="balance_check",
        partner_ledger_amount_cents=0,
        observed_balance_cents=76_000,
        observed_balance_kind="prepaid_balance",
        apply_balance_reconciliation=True,
    )

    response = confirm_ai_draft(payload, None, db)

    assert response.transaction is None
    assert response.partner_ledger["entry_type"] == "balance_check"
    assert response.balance_reconciliation["applied"] is True
    assert response.balance_reconciliation["delta_cents"] == 76_000
    assert db.query(Transaction).count() == 0
    assert db.get(Partner, partner.id).prepaid_balance_cents == 76_000
    assert db.query(PartnerLedgerEntry).count() == 2


def test_fallback_parse_infers_supplier_recharge_from_payment_and_balance():
    db = _db()
    user, _, method, partner = _fixtures(db)
    alipay = PaymentMethod(user_id=user.id, name="支付宝")
    db.add(alipay)
    db.commit()
    service = AIService(Settings(_env_file=None, secret_key="s" * 64, ai_api_key=None))

    result = service.parse(
        db,
        user.id,
        "支付宝扫了 500 元给供应商 A，目前余额 1200 元",
        mode="combined",
    )

    # Combined mode still needs a cash category; the supplier-side proposal is
    # complete enough to show the two confirmation rows while the UI asks for
    # that one remaining cash field.
    assert result.status == "need_more_info"
    assert "category" in result.missing_fields
    assert result.parsed.direction == "expense"
    assert result.parsed.amount_cents == 50_000
    assert result.parsed.payment_method_id == alipay.id
    assert result.parsed.partner_id == partner.id
    assert result.parsed.partner_ledger_type == "balance_check"
    assert result.parsed.partner_ledger_amount_cents == 0
    assert result.parsed.partner_balance_after_cents == 120_000
    assert result.warning and "本地规则" in result.warning


def test_partner_confirm_payload_shape_writes_no_cash_transaction(monkeypatch):
    db = _db()
    user, _, _, partner = _fixtures(db)
    monkeypatch.setattr(ai_module, "_user", lambda request, session: user)
    payload = AIConfirmRequest(
        confirm=True,
        mode="partner",
        draft={
            "occurred_at": datetime.now(timezone.utc),
            "partner_id": partner.id,
            "partner_ledger_type": "balance_check",
            "partner_ledger_amount_cents": 0,
            "partner_balance_after_cents": 50_000,
            "partner_balance_kind": "prepaid_balance",
            "notes": "供应商充值",
        },
        partner_ledger_type="balance_check",
        partner_ledger_amount_cents=0,
        observed_balance_cents=50_000,
        observed_balance_kind="prepaid_balance",
    )

    response = confirm_ai_draft(payload, None, db)

    assert response.mode == "partner"
    assert response.transaction is None
    assert response.partner_ledger["entry_type"] == "balance_check"
    assert response.balance_reconciliation["delta_cents"] == 50_000
    assert response.balance_reconciliation["applied"] is False
    assert db.query(Transaction).count() == 0


def test_combined_confirm_payload_writes_cash_and_linked_partner_entry(monkeypatch):
    db = _db()
    user, category, method, partner = _fixtures(db)
    monkeypatch.setattr(ai_module, "_user", lambda request, session: user)
    payload = AIConfirmRequest(
        confirm=True,
        mode="combined",
        draft={
            "occurred_at": datetime.now(timezone.utc),
            "direction": "expense",
            "amount_cents": 50_000,
            "category_id": category.id,
            "payment_method_id": method.id,
            "partner_id": partner.id,
            "partner_ledger_type": "prepaid_in",
            "partner_ledger_amount_cents": 50_000,
            "partner_balance_after_cents": 50_000,
            "partner_balance_kind": "prepaid_balance",
        },
        partner_ledger_type="prepaid_in",
        partner_ledger_amount_cents=50_000,
        observed_balance_cents=50_000,
        observed_balance_kind="prepaid_balance",
    )

    response = confirm_ai_draft(payload, None, db)

    assert response.mode == "combined"
    assert response.transaction["source"] == "ai"
    assert response.partner_ledger["transaction_id"] == response.transaction["id"]
    assert db.query(Transaction).count() == 1
    assert db.query(PartnerLedgerEntry).count() == 1


def test_linked_cash_transaction_can_change_category_when_protected_values_are_unchanged(monkeypatch):
    db = _db()
    user, category, method, partner = _fixtures(db)
    replacement = Category(user_id=user.id, name="其他支出", direction="expense")
    db.add(replacement)
    db.commit()
    monkeypatch.setattr(ai_module, "_user", lambda request, session: user)
    payload = AIConfirmRequest(
        confirm=True,
        mode="combined",
        draft={
            "occurred_at": datetime.now(timezone.utc),
            "direction": "expense",
            "amount_cents": 50_000,
            "category_id": category.id,
            "payment_method_id": method.id,
            "partner_id": partner.id,
            "partner_ledger_type": "balance_check",
            "partner_ledger_amount_cents": 0,
            "partner_balance_after_cents": 0,
            "partner_balance_kind": "prepaid_balance",
        },
        partner_ledger_type="balance_check",
        partner_ledger_amount_cents=0,
        observed_balance_cents=0,
        observed_balance_kind="prepaid_balance",
    )
    created = confirm_ai_draft(payload, None, db).transaction
    transaction = db.get(Transaction, created["id"])
    monkeypatch.setattr(accounting_module, "_user", lambda request, session: user)

    updated = accounting_module.update_transaction(
        transaction.id,
        TransactionUpdate(
            direction=transaction.direction,
            amount_cents=transaction.amount_cents,
            category_id=replacement.id,
            payment_method_id=transaction.payment_method_id,
            partner_id=transaction.partner_id,
            source=transaction.source,
        ),
        None,
        db,
    )

    assert updated["category_id"] == replacement.id
    assert db.get(Transaction, transaction.id).category_id == replacement.id
    assert db.query(PartnerLedgerEntry).filter_by(transaction_id=transaction.id).count() == 1

    with pytest.raises(HTTPException) as exc_info:
        accounting_module.update_transaction(
            transaction.id,
            TransactionUpdate(amount_cents=transaction.amount_cents + 1),
            None,
            db,
        )
    assert exc_info.value.status_code == 409


def test_cash_confirm_ignores_virtual_fields_and_only_writes_transaction(monkeypatch):
    db = _db()
    user, category, method, partner = _fixtures(db)
    monkeypatch.setattr(ai_module, "_user", lambda request, session: user)
    payload = AIConfirmRequest(
        confirm=True,
        mode="cash",
        draft={
            "occurred_at": datetime.now(timezone.utc),
            "direction": "expense",
            "amount_cents": 1_000,
            "category_id": category.id,
            "payment_method_id": method.id,
            "partner_id": partner.id,
            "partner_ledger_type": "prepaid_in",
            "partner_ledger_amount_cents": 1_000,
        },
    )

    response = confirm_ai_draft(payload, None, db)

    assert response.mode == "cash"
    assert response.transaction["partner_id"] == partner.id
    assert response.partner_ledger is None
    assert db.query(Transaction).count() == 1
    assert db.query(PartnerLedgerEntry).count() == 0


def _record(**overrides):
    value = {
        "occurred_at": None,
        "kind": "cashflow",
        "direction": "expense",
        "amount_cents": None,
        "category_id": None,
        "category_name": None,
        "payment_method_id": None,
        "payment_method_name": None,
        "transfer_payment_method_id": None,
        "transfer_payment_method_name": None,
        "partner_id": None,
        "partner_name": None,
        "partner_ledger_type": None,
        "partner_ledger_amount_cents": None,
        "partner_balance_after_cents": None,
        "partner_balance_kind": None,
        "notes": None,
    }
    value.update(overrides)
    return value


def _multi_record_fixtures(db: Session):
    user, _, wechat, partner = _fixtures(db)
    dining = Category(user_id=user.id, name="餐饮", direction="expense")
    other_income = Category(user_id=user.id, name="其他收入", direction="income")
    savings = PaymentMethod(user_id=user.id, name="招行储蓄卡", account_role="cash", track_balance=True, current_balance_cents=500_000)
    card = PaymentMethod(user_id=user.id, name="招行信用卡", account_role="liability", track_balance=True, current_balance_cents=300_000)
    db.add_all([dining, other_income, savings, card])
    db.commit()
    return user, dining, other_income, wechat, savings, card, partner


def _parse_with_model(monkeypatch, db, user, provider_result, text_value, mode="combined"):
    service = AIService(Settings(_env_file=None, secret_key="s" * 64, ai_api_key="sk-test"))
    captured = {}

    def fake_chat(provider, messages, **kwargs):
        captured["system"] = messages[0]["content"]
        captured["response_format"] = kwargs.get("response_format")
        return json.dumps(provider_result, ensure_ascii=False)

    monkeypatch.setattr(service, "_chat", fake_chat)
    result = service.parse(db, user.id, text_value, reference_time=datetime(2026, 8, 3, 9, 30, tzinfo=timezone.utc), mode=mode)
    return result, captured


def test_model_parse_returns_every_record_of_a_spending_run(monkeypatch):
    db = _db()
    user, dining, _, wechat, savings, _, _ = _multi_record_fixtures(db)
    provider_result = {
        "status": "complete",
        "parsed": _record(amount_cents=1200, category_name="餐饮", payment_method_name="微信", notes="早餐"),
        "missing_fields": [],
        "follow_up_question": None,
        "brief_comment": "三笔消费已分别整理。",
        "extra_records": [
            _record(amount_cents=3500, category_name="餐饮", payment_method_name="招行储蓄卡", notes="午饭"),
            # The account is unknown, so only this record is incomplete.
            _record(amount_cents=2800, category_name="餐饮", notes="晚饭"),
        ],
    }

    result, captured = _parse_with_model(monkeypatch, db, user, provider_result, "早餐微信12，午饭储蓄卡35，晚饭28")

    assert [item.parsed.amount_cents for item in result.records] == [1200, 3500, 2800]
    assert [item.parsed.payment_method_id for item in result.records] == [wechat.id, savings.id, None]
    assert [item.status for item in result.records] == ["complete", "complete", "need_more_info"]
    assert all(item.parsed.category_id == dining.id for item in result.records)
    assert result.parsed == result.records[0].parsed
    assert result.status == "need_more_info"
    assert result.missing_fields == ["payment_method"]
    assert result.follow_up_question == "第 3 笔请补充：来源账户。"
    assert result.records[2].parsed.field_status["payment_method"] == "missing"
    assert result.warning is None
    assert "多笔记录规则" in captured["system"]
    assert '"extra_records":[]' in captured["system"]
    assert "extra_records" in captured["response_format"]["json_schema"]["schema"]["required"]


def test_model_parse_splits_repayment_and_coupon_into_two_records(monkeypatch):
    db = _db()
    user, _, other_income, _, savings, card, _ = _multi_record_fixtures(db)
    provider_result = {
        "status": "complete",
        "parsed": _record(kind="transfer", amount_cents=200_000, payment_method_name="招行储蓄卡", transfer_payment_method_name="招行信用卡", notes="信用卡还款"),
        "missing_fields": [],
        "follow_up_question": None,
        "brief_comment": None,
        "extra_records": [
            _record(direction="income", amount_cents=5000, category_name="其他收入", payment_method_name="招行储蓄卡", notes="还款券抵扣"),
        ],
    }

    result, captured = _parse_with_model(monkeypatch, db, user, provider_result, "招行储蓄卡还信用卡2000，用了一张50元还款券")

    transfer, coupon = (item.parsed for item in result.records)
    assert result.status == "complete"
    assert (transfer.kind, transfer.payment_method_id, transfer.transfer_payment_method_id, transfer.amount_cents) == ("transfer", savings.id, card.id, 200_000)
    assert (coupon.kind, coupon.direction, coupon.category_id, coupon.payment_method_id, coupon.amount_cents) == ("cashflow", "income", other_income.id, savings.id, 5000)
    assert result.brief_comment == "共整理出 2 笔记录，请逐笔核对后勾选需要入账的记录。"
    assert "抵扣规则" in captured["system"]


def test_model_parse_single_record_leaves_records_empty(monkeypatch):
    db = _db()
    user, dining, _, wechat, _, _, _ = _multi_record_fixtures(db)
    provider_result = {
        "status": "complete",
        "parsed": _record(amount_cents=1200, category_name="餐饮", payment_method_name="微信", notes="早餐"),
        "missing_fields": [],
        "follow_up_question": None,
        "brief_comment": "一笔早餐支出。",
        "extra_records": [],
    }

    result, _ = _parse_with_model(monkeypatch, db, user, provider_result, "早餐微信12")

    assert result.records == []
    assert result.status == "complete"
    assert (result.parsed.category_id, result.parsed.payment_method_id) == (dining.id, wechat.id)


def test_model_parse_batch_drops_partner_balances_with_a_warning(monkeypatch):
    db = _db()
    user, _, _, wechat, _, _, partner = _multi_record_fixtures(db)
    provider_result = {
        "status": "complete",
        "parsed": _record(amount_cents=1200, category_name="进货", payment_method_name="微信", partner_name="供应商 A", partner_ledger_type="balance_check", partner_ledger_amount_cents=0, partner_balance_after_cents=76_000, partner_balance_kind="prepaid_balance"),
        "missing_fields": [],
        "follow_up_question": None,
        "brief_comment": None,
        "extra_records": [
            _record(amount_cents=3500, category_name="进货", payment_method_name="微信"),
            # A balance-only record has no cash side and cannot join a batch.
            _record(direction=None, partner_name="供应商 A", partner_ledger_type="balance_check", partner_balance_after_cents=76_000),
        ],
    }

    result, _ = _parse_with_model(monkeypatch, db, user, provider_result, "微信进货12和35，供应商A余额760")

    assert [item.parsed.amount_cents for item in result.records] == [1200, 3500]
    assert all(item.parsed.partner_ledger_type is None and item.parsed.partner_balance_after_cents is None for item in result.records)
    assert result.records[0].parsed.partner_id == partner.id
    assert "往来未结算余额" in result.warning


def test_model_parse_partner_mode_ignores_extra_records(monkeypatch):
    db = _db()
    user, _, _, _, _, _, partner = _multi_record_fixtures(db)
    provider_result = {
        "status": "complete",
        "parsed": _record(direction=None, partner_name="供应商 A", partner_ledger_type="balance_check", partner_ledger_amount_cents=0, partner_balance_after_cents=76_000, partner_balance_kind="prepaid_balance"),
        "missing_fields": [],
        "follow_up_question": None,
        "brief_comment": None,
        "extra_records": [_record(amount_cents=3500, category_name="进货", payment_method_name="微信")],
    }

    result, _ = _parse_with_model(monkeypatch, db, user, provider_result, "供应商A余额760", mode="partner")

    assert result.records == []
    assert result.parsed.partner_id == partner.id
    assert result.parsed.partner_balance_after_cents == 76_000
    assert result.warning is None


def _batch_confirm_fixtures(monkeypatch):
    db = _db()
    user, dining, other_income, wechat, savings, card, _ = _multi_record_fixtures(db)
    monkeypatch.setattr(ai_module, "_user", lambda request, session: user)
    return db, dining, other_income, wechat, savings, card


def test_batch_confirm_writes_repayment_and_coupon_together(monkeypatch):
    db, _, other_income, _, savings, card = _batch_confirm_fixtures(monkeypatch)
    payload = AIBatchConfirmRequest(
        confirm=True,
        drafts=[
            AIParsedTransaction(kind="transfer", amount_cents=200_000, payment_method_id=savings.id, transfer_payment_method_id=card.id, notes="信用卡还款"),
            AIParsedTransaction(direction="income", amount_cents=5000, category_id=other_income.id, payment_method_id=savings.id, notes="还款券抵扣"),
        ],
    )

    response = confirm_ai_drafts(payload, None, db)

    assert [item["kind"] for item in response.transactions] == ["transfer", "cashflow"]
    assert [item["source"] for item in response.transactions] == ["ai", "ai"]
    assert db.query(Transaction).count() == 2
    # 2000 left the savings card and the 50 coupon came back to it.
    assert db.get(PaymentMethod, savings.id).current_balance_cents == 500_000 - 200_000 + 5000
    assert db.get(PaymentMethod, card.id).current_balance_cents == 300_000 - 200_000


def test_batch_confirm_is_all_or_nothing(monkeypatch):
    db, dining, _, wechat, savings, _ = _batch_confirm_fixtures(monkeypatch)
    payload = AIBatchConfirmRequest(
        confirm=True,
        drafts=[
            AIParsedTransaction(direction="expense", amount_cents=1200, category_id=dining.id, payment_method_id=savings.id),
            # Missing category: the whole batch must be rejected.
            AIParsedTransaction(direction="expense", amount_cents=3500, payment_method_id=wechat.id),
        ],
    )

    with pytest.raises(HTTPException) as error:
        confirm_ai_drafts(payload, None, db)

    assert error.value.status_code == 422
    assert error.value.detail.startswith("第 2 笔：")
    assert db.query(Transaction).count() == 0
    assert db.get(PaymentMethod, savings.id).current_balance_cents == 500_000


def test_batch_confirm_requires_literal_true_and_at_least_one_draft():
    draft = AIParsedTransaction(direction="expense", amount_cents=1200, category_id=1, payment_method_id=1)
    with pytest.raises(ValidationError):
        AIBatchConfirmRequest(confirm=False, drafts=[draft])
    with pytest.raises(ValidationError):
        AIBatchConfirmRequest(confirm=True, drafts=[])


class _FakeStreamResponse:
    status_code = 200

    def __init__(self, lines):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_lines(self):
        yield from self._lines


def _sse(delta):
    return "data: " + json.dumps({"choices": [{"delta": delta}]}, ensure_ascii=False)


def _stream_chat(monkeypatch, lines):
    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured["timeout"] = kwargs["timeout"]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def stream(self, method, url, headers, json):
            captured["payload"] = json
            return _FakeStreamResponse(lines)

    monkeypatch.setattr("app.ai_service.httpx.Client", FakeClient)
    service = AIService(Settings(_env_file=None, secret_key="s" * 64, ai_api_key="sk-test"))
    provider = Provider("primary", "https://gateway.example", "sk-test", "gpt-6-luna")
    deltas = []
    content = service._chat(provider, [{"role": "user", "content": "hi"}], on_delta=lambda kind, text: deltas.append((kind, text)))
    return content, deltas, captured


def test_chat_streams_reasoning_and_content_deltas(monkeypatch):
    lines = [
        _sse({"role": "assistant", "reasoning_content": "**Parsing**"}),
        "",
        _sse({"content": '{"status":'}),
        _sse({"content": '"complete"}'}),
        "data: [DONE]",
        _sse({"content": "ignored after DONE"}),
    ]

    content, deltas, captured = _stream_chat(monkeypatch, lines)

    assert content == '{"status":"complete"}'
    assert deltas == [("start", ""), ("reasoning", "**Parsing**"), ("content", '{"status":'), ("content", '"complete"}')]
    assert captured["payload"]["stream"] is True
    assert captured["payload"]["reasoning_effort"] == "low"
    # The read timeout bounds the gap between chunks, not the whole answer.
    assert captured["timeout"].read == 30.0


def test_chat_stream_accepts_a_gateway_that_answers_with_plain_json(monkeypatch):
    body = json.dumps({"choices": [{"message": {"content": "{\"status\": \"complete\"}"}}]})

    content, deltas, _ = _stream_chat(monkeypatch, [body])

    assert content == '{"status": "complete"}'
    assert deltas == [("start", "")]


def test_model_parse_reports_progress_events(monkeypatch):
    db = _db()
    user, _, _, _, _, _, _ = _multi_record_fixtures(db)
    service = AIService(Settings(_env_file=None, secret_key="s" * 64, ai_api_key="sk-test"))
    provider_result = {
        "status": "complete",
        "parsed": _record(amount_cents=1200, category_name="餐饮", payment_method_name="微信", notes="早餐"),
        "missing_fields": [],
        "follow_up_question": None,
        "brief_comment": "一笔早餐支出。",
        "extra_records": [],
    }

    def fake_chat(provider, messages, **kwargs):
        kwargs["on_delta"]("start", "")
        kwargs["on_delta"]("reasoning", "thinking")
        kwargs["on_delta"]("content", "{")
        return json.dumps(provider_result, ensure_ascii=False)

    monkeypatch.setattr(service, "_chat", fake_chat)
    events = []
    result = service.parse(db, user.id, "早餐微信12", on_event=events.append)

    assert result.status == "complete"
    assert events[0]["type"] == "provider" and events[0]["name"] == "primary"
    assert events[1:] == [
        {"type": "start", "text": ""},
        {"type": "reasoning", "text": "thinking"},
        {"type": "content", "text": "{"},
    ]


def _frames(run):
    return [json.loads(frame[len("data: "):]) for frame in ai_module._sse_events(run) if frame.startswith("data: ")]


def test_parse_stream_ends_with_the_result_event():
    result = AIService(Settings(_env_file=None, secret_key="s" * 64, ai_api_key=None)).deterministic_parse(
        "微信花了35元", [], [], [], datetime(2026, 8, 3, 9, 30, tzinfo=timezone.utc)
    )

    def run(emit):
        emit({"type": "reasoning", "text": "思考"})
        return result

    frames = _frames(run)

    assert frames[0] == {"type": "reasoning", "text": "思考"}
    assert frames[-1]["type"] == "result"
    assert frames[-1]["data"]["parsed"]["amount_cents"] == 3500
    assert len(frames) == 2


def test_parse_stream_reports_provider_failure_as_error_event():
    def run(emit):
        raise AIServiceError("provider_unavailable")

    assert _frames(run) == [{"type": "error", "status": 503, "detail": "AI 服务暂不可用，请稍后重试。"}]


def test_parse_stream_endpoint_streams_sse(monkeypatch):
    db = _db()
    user, _, _, _, _, _, _ = _multi_record_fixtures(db)
    service = AIService(Settings(_env_file=None, secret_key="s" * 64, ai_api_key=None))
    monkeypatch.setattr(ai_module, "service", service)
    monkeypatch.setattr(ai_module, "_user", lambda request, session: user)
    monkeypatch.setattr(ai_module, "SessionLocal", lambda: db)

    response = ai_module.parse_natural_language_stream(ai_module.AIParseRequest(text="微信花了35元"), None, db)

    assert response.media_type == "text/event-stream"

    async def collect():
        return [frame async for frame in response.body_iterator]

    frames = [json.loads(frame[len("data: "):]) for frame in asyncio.run(collect()) if frame.startswith("data: ")]
    assert [frame["type"] for frame in frames] == ["intent", "provider", "status", "result"]
    assert frames[0] == {"type": "intent", "intent": "bookkeeping"}
    assert frames[2] == {"type": "status", "code": "local_fallback"}
    assert frames[-1]["data"]["source"] == "fallback"


@pytest.mark.parametrize(
    "base_url",
    [
        "https://gateway.example",
        "https://gateway.example/",
        "https://gateway.example/v1",
        "https://gateway.example/v1/chat/completions",
        "https://gateway.example/v1/messages",
        "https://gateway.example/v1beta",
    ],
)
def test_api_root_drops_version_and_path_suffixes(base_url):
    assert _api_root(base_url) == "https://gateway.example"


def test_conversation_turns_merge_roles_and_start_with_the_user():
    system, turns = _conversation_turns(
        [
            {"role": "system", "content": "规则"},
            {"role": "assistant", "content": "上一轮遗留的追问"},
            {"role": "user", "content": "早餐12"},
            {"role": "assistant", "content": "请向下核对"},
            {"role": "assistant", "content": "请补充账户"},
            {"role": "user", "content": "微信"},
        ]
    )

    assert system == "规则"
    assert turns == [("user", "早餐12"), ("assistant", "请向下核对\n\n请补充账户"), ("user", "微信")]


def _format_service():
    return AIService(Settings(_env_file=None, secret_key="s" * 64, ai_api_key="sk-test"))


_FORMAT_MESSAGES = [
    {"role": "system", "content": "只输出 JSON"},
    {"role": "user", "content": "早餐微信12"},
]


def _gemini_chat(monkeypatch, responses, **kwargs):
    requests = []

    class FakeClient:
        def __init__(self, **options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def stream(self, method, url, headers, json):
            requests.append({"url": url, "headers": headers, "body": json})
            return responses[len(requests) - 1]

    monkeypatch.setattr("app.ai_service.httpx.Client", FakeClient)
    provider = Provider("primary", "https://gateway.example/v1", "sk-test", "gemini-3.8-flash-high", "gemini")
    deltas = []
    content = _format_service()._chat(provider, _FORMAT_MESSAGES, on_delta=lambda kind, text: deltas.append((kind, text)), **kwargs)
    return content, deltas, requests


def _gemini_line(*parts):
    return "data: " + json.dumps({"candidates": [{"content": {"role": "model", "parts": list(parts)}}]}, ensure_ascii=False)


def test_gemini_format_streams_thoughts_and_answer(monkeypatch):
    response = _FakeStreamResponse(
        [
            _gemini_line({"text": "先拆分记录", "thought": True}),
            _gemini_line({"text": '{"status":'}),
            _gemini_line({"text": '"complete"}'}, {"text": "", "thoughtSignature": "sig"}),
        ]
    )

    content, deltas, requests = _gemini_chat(monkeypatch, [response], max_tokens=AI_PARSE_MAX_TOKENS, response_format=AI_PARSE_RESPONSE_FORMAT)

    assert content == '{"status":"complete"}'
    assert deltas == [("start", ""), ("reasoning", "先拆分记录"), ("content", '{"status":'), ("content", '"complete"}')]
    request = requests[0]
    assert request["url"] == "https://gateway.example/v1beta/models/gemini-3.8-flash-high:streamGenerateContent?alt=sse"
    assert request["headers"]["x-goog-api-key"] == "sk-test"
    assert request["body"]["systemInstruction"] == {"parts": [{"text": "只输出 JSON"}]}
    assert request["body"]["contents"] == [{"role": "user", "parts": [{"text": "早餐微信12"}]}]
    generation = request["body"]["generationConfig"]
    assert generation["thinkingConfig"] == {"includeThoughts": True}
    assert generation["maxOutputTokens"] == AI_PARSE_MAX_TOKENS
    assert generation["responseMimeType"] == "application/json"
    # Gemini rejects null enum members; nullability stays in the type.
    direction = generation["responseJsonSchema"]["properties"]["parsed"]["properties"]["direction"]
    assert direction == {"type": ["string", "null"], "enum": ["income", "expense"]}


def test_gemini_format_retries_plain_when_the_channel_rejects_the_options(monkeypatch):
    rejected = _FakeStreamResponse([])
    rejected.status_code = 400
    accepted = _FakeStreamResponse([_gemini_line({"text": "好的"})])

    content, deltas, requests = _gemini_chat(monkeypatch, [rejected, accepted], response_format=AI_PARSE_RESPONSE_FORMAT)

    assert content == "好的"
    assert [kind for kind, _ in deltas] == ["start", "start", "content"]
    assert requests[1]["body"]["generationConfig"] == {"temperature": 0.2}


class _FakeAnthropicStream:
    def __init__(self, events, message):
        self._events, self._message = events, message

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def __iter__(self):
        return iter(self._events)

    def get_final_message(self):
        return self._message


def _anthropic_chat(monkeypatch, outcomes, **kwargs):
    captured = {"requests": []}

    class FakeAnthropic:
        def __init__(self, **options):
            captured["options"] = options
            self.messages = self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def stream(self, **params):
            captured["requests"].append(params)
            outcome = outcomes[len(captured["requests"]) - 1]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    monkeypatch.setattr("app.ai_service.anthropic.Anthropic", FakeAnthropic)
    provider = Provider("primary", "https://gateway.example/v1", "sk-test", "claude-sonnet-4-6", "anthropic")
    deltas = []
    content = _format_service()._chat(provider, _FORMAT_MESSAGES, on_delta=lambda kind, text: deltas.append((kind, text)), **kwargs)
    return content, deltas, captured


def _anthropic_delta(kind, **fields):
    return SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type=kind, **fields))


def _anthropic_answer(text, stop_reason="end_turn"):
    events = [
        SimpleNamespace(type="message_start"),
        _anthropic_delta("thinking_delta", thinking="先看金额"),
        _anthropic_delta("text_delta", text=text),
    ]
    message = SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text=text)])
    return _FakeAnthropicStream(events, message)


def test_anthropic_format_streams_thinking_and_answer(monkeypatch):
    content, deltas, captured = _anthropic_chat(monkeypatch, [_anthropic_answer('{"status":"complete"}')], max_tokens=AI_PARSE_MAX_TOKENS, response_format=AI_PARSE_RESPONSE_FORMAT)

    assert content == '{"status":"complete"}'
    assert deltas == [("start", ""), ("reasoning", "先看金额"), ("content", '{"status":"complete"}')]
    assert captured["options"]["base_url"] == "https://gateway.example"
    assert captured["options"]["api_key"] == "sk-test"
    assert captured["options"]["max_retries"] == 0
    request = captured["requests"][0]
    assert request["model"] == "claude-sonnet-4-6"
    assert request["system"] == "只输出 JSON"
    assert request["messages"] == [{"role": "user", "content": "早餐微信12"}]
    assert request["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert request["output_config"]["effort"] == "low"
    # Thinking shares max_tokens, so the parser's small cap is raised.
    assert request["max_tokens"] == 16_000
    schema = request["output_config"]["format"]["schema"]
    assert request["output_config"]["format"]["type"] == "json_schema"
    assert "minimum" not in schema["properties"]["parsed"]["properties"]["amount_cents"]
    assert "temperature" not in request


def test_anthropic_format_retries_plain_after_a_bad_request(monkeypatch):
    response = httpx2.Response(400, request=httpx2.Request("POST", "https://gateway.example/v1/messages"))
    rejected = anthropic.BadRequestError("unsupported option", response=response, body=None)

    content, deltas, captured = _anthropic_chat(monkeypatch, [rejected, _anthropic_answer("好的")])

    assert content == "好的"
    assert [kind for kind, _ in deltas] == ["start", "start", "reasoning", "content"]
    plain = captured["requests"][1]
    assert "thinking" not in plain and "output_config" not in plain


def test_anthropic_format_treats_a_refusal_as_a_provider_failure(monkeypatch):
    with pytest.raises(AIServiceError) as error:
        _anthropic_chat(monkeypatch, [_anthropic_answer("", stop_reason="refusal")])

    assert error.value.code == "provider_refused"


def test_ai_config_saves_and_reads_the_api_format(monkeypatch):
    db = _db()
    user, _, _, _ = _fixtures(db)
    service = _format_service()
    monkeypatch.setattr(ai_module, "service", service)
    monkeypatch.setattr(ai_module, "_user", lambda request, session: user)

    assert ai_module.get_ai_config(None, db).api_format == "openai"

    saved = ai_module.put_ai_config(
        ai_module.AIConfigUpdate(base_url="https://gateway.example", model="gemini-3.8-flash-high", api_format="gemini", fallback_model="claude-sonnet-4-6", fallback_api_format="anthropic"),
        None,
        db,
    )

    assert (saved.api_format, saved.fallback_api_format) == ("gemini", "anthropic")
    row = db.query(AIConfig).one()
    assert (row.api_format, row.fallback_api_format) == ("gemini", "anthropic")
    primary, fallback = service.provider_chain_for_user(db, user.id)
    assert (primary.model, primary.api_format) == ("gemini-3.8-flash-high", "gemini")
    assert (fallback.model, fallback.api_format) == ("claude-sonnet-4-6", "anthropic")
    with pytest.raises(ValidationError):
        ai_module.AIConfigUpdate(api_format="cohere")


def _server_channel_service(share: bool) -> AIService:
    return AIService(
        Settings(
            _env_file=None,
            secret_key="s" * 64,
            ai_base_url="https://owner-proxy.example",
            ai_model="owner-model",
            ai_api_key="sk-owner-1234",
            ai_api_format="gemini",
            ai_fallback_base_url="https://owner-fallback.example",
            ai_fallback_model="owner-fallback-model",
            ai_fallback_api_key="sk-owner-fallback-5678",
            ai_share_with_users=share,
            # As in production: no silent local parser when no channel answers.
            ai_local_fallback=False,
        )
    )


def test_server_ai_channel_is_shared_with_users_by_default():
    db = _db()
    user, _, _, _ = _fixtures(db)

    primary, fallback = _server_channel_service(True).provider_chain_for_user(db, user.id)

    assert (primary.base_url, primary.model, primary.api_key, primary.api_format) == ("https://owner-proxy.example", "owner-model", "sk-owner-1234", "gemini")
    assert (fallback.base_url, fallback.api_key) == ("https://owner-fallback.example", "sk-owner-fallback-5678")


def test_unshared_server_ai_channel_is_hidden_from_users_without_their_own(monkeypatch):
    db = _db()
    user, _, _, _ = _fixtures(db)
    service = _server_channel_service(False)
    monkeypatch.setattr(ai_module, "service", service)
    monkeypatch.setattr(ai_module, "_user", lambda request, session: user)

    providers = service.provider_chain_for_user(db, user.id)

    assert len(providers) == 1
    assert (providers[0].base_url, providers[0].model, providers[0].api_key, providers[0].api_format) == ("https://api.openai.com", "gpt-4o-mini", None, "openai")
    # Nothing about the owner's channel shows up in the settings form either.
    config = ai_module.get_ai_config(None, db)
    assert config.configured is False and config.fallback_configured is False
    assert config.api_key_hint is None and config.fallback_api_key_hint is None
    assert "owner" not in config.model_dump_json()
    # AI requests stop instead of spending the owner's quota.
    with pytest.raises(HTTPException) as error:
        ai_module.parse_natural_language(ai_module.AIParseRequest(text="午餐35元"), None, db)
    assert error.value.status_code == 503
    assert error.value.detail == "AI 服务未配置，请先完成 AI 配置。"


def test_unshared_server_ai_channel_never_fills_in_a_users_missing_fields(monkeypatch):
    db = _db()
    user, _, _, _ = _fixtures(db)
    service = _server_channel_service(False)
    monkeypatch.setattr(ai_module, "service", service)
    monkeypatch.setattr(ai_module, "_user", lambda request, session: user)

    # The user saves only a key and a model, leaving the address blank.
    ai_module.put_ai_config(ai_module.AIConfigUpdate(model="my-model", api_key="sk-mine-0000"), None, db)
    providers = service.provider_chain_for_user(db, user.id)

    assert (providers[0].base_url, providers[0].model, providers[0].api_key) == ("https://api.openai.com", "my-model", "sk-mine-0000")
    assert all("owner" not in (item.base_url + item.model + (item.api_key or "")) for item in providers)
    assert ai_module.get_ai_config(None, db).api_key_hint == "••••0000"


def test_swap_ai_channels_exchanges_both_channels_including_keys(monkeypatch):
    db = _db()
    user, _, _, _ = _fixtures(db)
    service = _server_channel_service(False)
    monkeypatch.setattr(ai_module, "service", service)
    monkeypatch.setattr(ai_module, "_user", lambda request, session: user)
    ai_module.put_ai_config(
        ai_module.AIConfigUpdate(base_url="https://one.example", model="model-one", api_key="sk-one-1111", api_format="gemini", fallback_base_url="https://two.example", fallback_model="model-two", fallback_api_key="sk-two-2222", fallback_api_format="openai"),
        None,
        db,
    )

    swapped = ai_module.swap_ai_channels(None, db)

    assert (swapped.base_url, swapped.model, swapped.api_format, swapped.api_key_hint) == ("https://two.example", "model-two", "openai", "••••2222")
    assert (swapped.fallback_base_url, swapped.fallback_model, swapped.fallback_api_format, swapped.fallback_api_key_hint) == ("https://one.example", "model-one", "gemini", "••••1111")
    primary, fallback = service.provider_chain_for_user(db, user.id)
    assert (primary.model, primary.api_key, fallback.model, fallback.api_key) == ("model-two", "sk-two-2222", "model-one", "sk-one-1111")
    # Swapping back restores the original configuration.
    restored = ai_module.swap_ai_channels(None, db)
    assert (restored.model, restored.fallback_model) == ("model-one", "model-two")


def test_swap_ai_channels_fills_inherited_fallback_fields_and_needs_a_fallback_model(monkeypatch):
    db = _db()
    user, _, _, _ = _fixtures(db)
    service = _server_channel_service(False)
    monkeypatch.setattr(ai_module, "service", service)
    monkeypatch.setattr(ai_module, "_user", lambda request, session: user)
    ai_module.put_ai_config(ai_module.AIConfigUpdate(base_url="https://one.example", model="model-one", api_key="sk-one-1111"), None, db)

    with pytest.raises(HTTPException) as error:
        ai_module.swap_ai_channels(None, db)
    assert error.value.status_code == 422

    # Only the fallback model is set: it shares the primary address and key.
    ai_module.put_ai_config(ai_module.AIConfigUpdate(fallback_model="model-two"), None, db)
    swapped = ai_module.swap_ai_channels(None, db)

    assert (swapped.base_url, swapped.model, swapped.api_key_hint) == ("https://one.example", "model-two", "••••1111")
    assert (swapped.fallback_base_url, swapped.fallback_model, swapped.fallback_api_key_hint) == ("https://one.example", "model-one", "••••1111")


def _calibration_fixtures(db: Session):
    user, _, wechat, _ = _fixtures(db)
    other_income = Category(user_id=user.id, name="其他收入", direction="income")
    other_expense = Category(user_id=user.id, name="其他支出", direction="expense")
    alipay = PaymentMethod(user_id=user.id, name="支付宝", account_role="cash", track_balance=True, current_balance_cents=100_000)
    card = PaymentMethod(user_id=user.id, name="招行信用卡", account_role="liability", track_balance=True, current_balance_cents=60_000)
    db.add_all([other_income, other_expense, alipay, card])
    db.commit()
    return user, other_income, other_expense, alipay, card


def test_model_parse_turns_a_balance_report_into_a_calibration_draft(monkeypatch):
    db = _db()
    user, _, _, alipay, _ = _calibration_fixtures(db)
    provider_result = {
        "status": "complete",
        "parsed": _record(kind="balance_check", direction=None, payment_method_name="支付宝", account_balance_cents=95_000),
        "missing_fields": [],
        "follow_up_question": None,
        "brief_comment": None,
        "extra_records": [],
    }

    result, captured = _parse_with_model(monkeypatch, db, user, provider_result, "支付宝现在余额950")

    parsed = result.parsed
    assert result.status == "complete" and result.missing_fields == []
    assert (parsed.kind, parsed.direction, parsed.amount_cents, parsed.category_id) == ("balance_check", None, None, None)
    assert (parsed.payment_method_id, parsed.account_balance_cents) == (alipay.id, 95_000)
    assert (parsed.account_balance_expected_cents, parsed.account_balance_delta_cents) == (100_000, -5_000)
    assert parsed.field_status == {"occurred_at": "inferred", "payment_method": "explicit", "account_balance_cents": "explicit"}
    assert "余额校准" in result.brief_comment
    assert "余额校准规则" in captured["system"]
    assert "按现金流入处理" not in captured["system"]
    assert "balance_check" in captured["response_format"]["json_schema"]["schema"]["properties"]["parsed"]["properties"]["kind"]["enum"]


def test_model_parse_reports_a_balance_check_without_an_amount_as_incomplete(monkeypatch):
    db = _db()
    user, _, _, _, _ = _calibration_fixtures(db)
    provider_result = {
        "status": "need_more_info",
        "parsed": _record(kind="balance_check", direction=None, payment_method_name="支付宝"),
        "missing_fields": ["account_balance_cents"],
        "follow_up_question": None,
        "brief_comment": None,
        "extra_records": [],
    }

    result, _ = _parse_with_model(monkeypatch, db, user, provider_result, "校准一下支付宝余额")

    assert result.status == "need_more_info"
    assert result.missing_fields == ["account_balance_cents"]
    assert result.follow_up_question == "请补充：账户当前余额。"


def _confirm_calibration(monkeypatch, db, user, **draft):
    service = AIService(Settings(_env_file=None, secret_key="s" * 64, ai_api_key=None))
    monkeypatch.setattr(ai_module, "service", service)
    monkeypatch.setattr(ai_module, "_user", lambda request, session: user)
    return confirm_ai_draft(AIConfirmRequest(confirm=True, draft=AIParsedTransaction(kind="balance_check", **draft)), None, db)


def test_confirming_a_calibration_books_the_difference_on_a_cash_account(monkeypatch):
    db = _db()
    user, _, other_expense, alipay, _ = _calibration_fixtures(db)

    response = _confirm_calibration(monkeypatch, db, user, payment_method_id=alipay.id, account_balance_cents=95_000)

    tx = response.transaction
    assert (tx["kind"], tx["direction"], tx["amount_cents"], tx["category_id"], tx["source"]) == ("cashflow", "expense", 5_000, other_expense.id, "ai")
    assert tx["notes"] == "余额校准：系统 1000.00 → 实际 950.00"
    assert db.get(PaymentMethod, alipay.id).current_balance_cents == 95_000


def test_confirming_a_calibration_on_a_liability_treats_more_debt_as_an_expense(monkeypatch):
    db = _db()
    user, other_income, other_expense, _, card = _calibration_fixtures(db)

    more_debt = _confirm_calibration(monkeypatch, db, user, payment_method_id=card.id, account_balance_cents=70_000)
    assert (more_debt.transaction["direction"], more_debt.transaction["amount_cents"], more_debt.transaction["category_id"]) == ("expense", 10_000, other_expense.id)
    assert db.get(PaymentMethod, card.id).current_balance_cents == 70_000

    less_debt = _confirm_calibration(monkeypatch, db, user, payment_method_id=card.id, account_balance_cents=65_000, notes="对账")
    assert (less_debt.transaction["direction"], less_debt.transaction["amount_cents"], less_debt.transaction["category_id"], less_debt.transaction["notes"]) == ("income", 5_000, other_income.id, "对账")
    assert db.get(PaymentMethod, card.id).current_balance_cents == 65_000


def test_confirming_a_calibration_rejects_an_unchanged_balance(monkeypatch):
    db = _db()
    user, _, _, alipay, _ = _calibration_fixtures(db)

    with pytest.raises(HTTPException) as error:
        _confirm_calibration(monkeypatch, db, user, payment_method_id=alipay.id, account_balance_cents=100_000)

    assert error.value.status_code == 422
    assert "一致" in error.value.detail
    assert db.query(Transaction).count() == 0


def test_batch_confirm_accepts_a_calibration_next_to_a_cashflow(monkeypatch):
    db = _db()
    user, _, other_expense, alipay, _ = _calibration_fixtures(db)
    monkeypatch.setattr(ai_module, "_user", lambda request, session: user)
    payload = AIBatchConfirmRequest(
        confirm=True,
        drafts=[
            AIParsedTransaction(direction="expense", amount_cents=1_200, category_id=other_expense.id, payment_method_id=alipay.id, notes="早餐"),
            AIParsedTransaction(kind="balance_check", payment_method_id=alipay.id, account_balance_cents=95_000),
        ],
    )

    response = confirm_ai_drafts(payload, None, db)

    assert [(item["direction"], item["amount_cents"]) for item in response.transactions] == [("expense", 1_200), ("expense", 3_800)]
    assert db.get(PaymentMethod, alipay.id).current_balance_cents == 95_000


def _scoped_ledger(db: Session):
    user, category, wechat, _ = _fixtures(db)
    alipay = PaymentMethod(user_id=user.id, name="支付宝")
    dining = Category(user_id=user.id, name="餐饮", direction="expense")
    db.add_all([alipay, dining])
    db.flush()
    when = datetime(2026, 8, 5, 4, 0, tzinfo=timezone.utc)
    db.add_all([
        Transaction(user_id=user.id, occurred_at=when, direction="expense", amount_cents=1_000, category_id=category.id, payment_method_id=wechat.id, status="normal"),
        Transaction(user_id=user.id, occurred_at=when, direction="expense", amount_cents=3_500, category_id=dining.id, payment_method_id=alipay.id, status="normal"),
        Transaction(user_id=user.id, occurred_at=when, direction="income", amount_cents=20_000, category_id=None, payment_method_id=alipay.id, status="normal"),
    ])
    db.commit()
    return user, category, dining, wechat, alipay


def test_period_summary_can_be_scoped_to_an_account_or_category():
    from app.ai_insights import resolve_period, summarize_period

    db = _db()
    user, category, dining, wechat, alipay = _scoped_ledger(db)
    spec = resolve_period("month", today=datetime(2026, 8, 20).date())

    everything = summarize_period(db, user.id, spec)
    by_account = summarize_period(db, user.id, spec, scope={"payment_method_id": alipay.id})
    by_category = summarize_period(db, user.id, spec, scope={"category_id": category.id, "direction": "expense"})

    assert (everything["income_cents"], everything["expense_cents"]) == (20_000, 4_500)
    assert "scope" not in everything
    assert (by_account["income_cents"], by_account["expense_cents"], by_account["scope"]) == (20_000, 3_500, {"账户": "支付宝"})
    assert list(by_account["categories"]) == ["未分类", "餐饮"] or set(by_account["categories"]) == {"未分类", "餐饮"}
    assert (by_category["income_cents"], by_category["expense_cents"], by_category["scope"]) == (0, 1_000, {"分类": "进货", "类型": "仅支出"})


def test_chat_endpoint_honours_an_explicit_intent_and_scope(monkeypatch):
    db = _db()
    user, _, _, _, alipay = _scoped_ledger(db)
    service = AIService(Settings(_env_file=None, secret_key="s" * 64, ai_api_key="sk-test"))
    captured = {}

    def fake_chat(provider, messages, **kwargs):
        captured["system"] = messages[0]["content"]
        captured["effort"] = kwargs.get("effort")
        captured["max_tokens"] = kwargs.get("max_tokens")
        return "支付宝本月支出 35.00 元。"

    monkeypatch.setattr(service, "_chat", fake_chat)
    monkeypatch.setattr(ai_module, "service", service)
    monkeypatch.setattr(ai_module, "_user", lambda request, session: user)
    # The sentence alone would be classified as bookkeeping ("花了…元").
    payload = ai_module.AIChatRequest(text="花了多少元", intent="query", period="custom", start_date=datetime(2026, 8, 1).date(), end_date=datetime(2026, 8, 31).date(), payment_method_id=alipay.id)

    response = ai_module.chat_about_finances(payload, None, db)

    assert response.intent == "query"
    assert response.scope == {"账户": "支付宝"}
    assert response.summary["expense_cents"] == 3_500
    assert "数据范围已限定为：账户=支付宝" in captured["system"]
    assert captured["effort"] == "high"
    assert captured["max_tokens"] == 16_000


def test_native_formats_request_deep_reasoning_for_analysis(monkeypatch):
    _, _, requests = _gemini_chat(monkeypatch, [_FakeStreamResponse([_gemini_line({"text": "好的"})])], effort="high")
    assert requests[0]["body"]["generationConfig"]["thinkingConfig"] == {"includeThoughts": True, "thinkingLevel": "high"}

    _, _, captured = _anthropic_chat(monkeypatch, [_anthropic_answer("好的")], effort="high")
    assert captured["requests"][0]["output_config"]["effort"] == "max"


# ---------------------------------------------------------------------------
# Tool-using ledger agent
# ---------------------------------------------------------------------------

from app import ai_agent


def _agent_db():
    db = _db()
    user, category, dining, wechat, alipay = _scoped_ledger(db)
    return db, user, category, dining, wechat, alipay


def test_ledger_tools_summarize_list_and_scope():
    db, user, category, dining, wechat, alipay = _agent_db()
    tools = ai_agent.LedgerTools(db, user.id)

    summary = tools.call("summarize_period", {"period": "custom", "start_date": "2026-08-01", "end_date": "2026-08-31", "payment_method_id": alipay.id})
    assert (summary["income_cents"], summary["expense_cents"], summary["scope"]) == (20_000, 3_500, {"账户": "支付宝"})

    rows = tools.call("list_transactions", {"start_date": "2026-08-05", "end_date": "2026-08-05", "direction": "expense", "limit": 10})
    assert rows["total"] == 2 and [item["amount_cents"] for item in rows["transactions"]] == [3_500, 1_000] or sorted(item["amount_cents"] for item in rows["transactions"]) == [1_000, 3_500]
    assert rows["transactions"][0]["account"] in {"支付宝", "微信"}

    accounts = tools.call("list_accounts", {})
    assert {item["name"] for item in accounts["accounts"]} == {"微信", "支付宝"}
    assert tools.call("summarize_period", {"period": "custom"}) == {"error": "custom 周期需要有效的 start_date 和 end_date（start_date 不晚于 end_date）"}
    assert tools.call("nope", {})["error"].startswith("未知工具")


def _agent_service(api_format: str, model: str) -> AIService:
    service = AIService(Settings(_env_file=None, secret_key="s" * 64, ai_api_key="sk-test", ai_base_url="https://gateway.example", ai_model=model, ai_api_format=api_format, ai_local_fallback=False))
    return service


def _run_agent(service, db, user, emit=None, text="支付宝 8 月花了多少？"):
    events = []
    result = ai_agent.run_ledger_agent(service, db, user.id, text, [], "query", events.append)
    return (result.content, result.source, result.warning, result.model, result.steps), events, result


def test_openai_agent_loop_calls_a_tool_then_answers(monkeypatch):
    db, user, _, _, _, alipay = _agent_db()
    user.alipay_id = alipay.id
    requests = []
    responses = [
        {"choices": [{"message": {"role": "assistant", "content": None, "reasoning_content": "先查汇总", "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "summarize_period", "arguments": json.dumps({"period": "custom", "start_date": "2026-08-01", "end_date": "2026-08-31", "payment_method_id": alipay.id})}}]}}]},
        {"choices": [{"message": {"role": "assistant", "content": "支付宝 8 月支出 35.00 元。"}}]},
    ]

    class FakeResponse:
        def __init__(self, data):
            self.status_code, self._data, self.text = 200, data, ""

        def json(self):
            return self._data

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers, json):
            requests.append({"url": url, "body": json})
            return FakeResponse(responses[len(requests) - 1])

    monkeypatch.setattr("app.ai_agent.httpx.Client", FakeClient)
    (content, source, warning, model, steps), events, result = _run_agent(_agent_service("openai", "gpt-6-luna"), db, user)

    assert (content, source, warning, model) == ("支付宝 8 月支出 35.00 元。", "model", None, "gpt-6-luna")
    assert (result.period.kind, result.period.start.isoformat(), result.period.end.isoformat()) == ("custom", "2026-08-01", "2026-08-31")
    assert steps == [{"name": "summarize_period", "summary": "统计自定义区间 2026-08-01 2026-08-31 · 账户=支付宝", "result": "2 笔，收入 200.00，支出 35.00"}]
    assert [event["type"] for event in events] == ["provider", "tool", "tool_result"]
    first, second = requests
    assert first["url"] == "https://gateway.example/v1/chat/completions"
    assert first["body"]["tool_choice"] == "auto" and first["body"]["reasoning_effort"] == "high"
    assert [tool["function"]["name"] for tool in first["body"]["tools"]] == ["summarize_period", "list_transactions", "propose_update", "propose_void", "propose_create", "list_accounts", "list_partners"]
    system = first["body"]["messages"][0]["content"]
    assert "【当前时间】" in system and "【工具调用方法】" in system and "【约束】" in system
    assert f"{alipay.id}=支付宝(现金)" in system and "视图" not in system
    # The second round carries the assistant turn (reasoning included) and the tool result.
    assert second["body"]["messages"][-2]["reasoning_content"] == "先查汇总"
    assert second["body"]["messages"][-1]["role"] == "tool" and '"expense_cents": 3500' in second["body"]["messages"][-1]["content"]


def test_gemini_agent_loop_echoes_the_model_turn(monkeypatch):
    db, user, _, _, _, alipay = _agent_db()
    user.alipay_id = alipay.id
    requests = []
    responses = [
        {"candidates": [{"content": {"role": "model", "parts": [{"functionCall": {"id": "fc_1", "name": "list_accounts", "args": {}}, "thoughtSignature": "sig"}]}}]},
        {"candidates": [{"content": {"role": "model", "parts": [{"text": "你有两个账户。"}]}}]},
    ]

    class FakeResponse:
        def __init__(self, data):
            self.status_code, self._data, self.text = 200, data, ""

        def json(self):
            return self._data

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers, json):
            requests.append({"url": url, "headers": headers, "body": json})
            return FakeResponse(responses[len(requests) - 1])

    monkeypatch.setattr("app.ai_agent.httpx.Client", FakeClient)
    (content, source, _, _, steps), _, _ = _run_agent(_agent_service("gemini", "gemini-3.8-flash-high"), db, user)

    assert (content, source) == ("你有两个账户。", "model")
    assert steps[0]["name"] == "list_accounts"
    first, second = requests
    assert first["url"] == "https://gateway.example/v1beta/models/gemini-3.8-flash-high:generateContent"
    assert first["headers"]["x-goog-api-key"] == "sk-test"
    assert first["body"]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "high"}
    declaration = first["body"]["tools"][0]["functionDeclarations"][0]
    assert declaration["name"] == "summarize_period" and "additionalProperties" not in declaration["parameters"]
    assert second["body"]["contents"][-2] == {"role": "model", "parts": [{"functionCall": {"id": "fc_1", "name": "list_accounts", "args": {}}, "thoughtSignature": "sig"}]}
    response = second["body"]["contents"][-1]["parts"][0]["functionResponse"]
    assert (response["name"], response["id"]) == ("list_accounts", "fc_1")


def test_anthropic_agent_loop_uses_tool_use_blocks(monkeypatch):
    db, user, _, _, _, alipay = _agent_db()
    user.alipay_id = alipay.id
    captured = {"requests": []}
    tool_turn = SimpleNamespace(stop_reason="tool_use", content=[SimpleNamespace(type="thinking", thinking="…"), SimpleNamespace(type="tool_use", id="toolu_1", name="summarize_period", input={"period": "month"})])
    final_turn = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="本月支出 35.00 元。")])
    outcomes = [_FakeAnthropicStream([], tool_turn), _FakeAnthropicStream([], final_turn)]

    class FakeAnthropic:
        def __init__(self, **options):
            captured["options"] = options
            self.messages = self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def stream(self, **params):
            captured["requests"].append(params)
            return outcomes[len(captured["requests"]) - 1]

    monkeypatch.setattr("app.ai_agent.anthropic.Anthropic", FakeAnthropic)
    (content, source, _, _, steps), _, _ = _run_agent(_agent_service("anthropic", "claude-sonnet-4-6"), db, user)

    assert (content, source) == ("本月支出 35.00 元。", "model")
    assert steps[0]["name"] == "summarize_period"
    first, second = captured["requests"]
    assert first["tools"][0]["name"] == "summarize_period" and first["thinking"] == {"type": "adaptive"} and first["output_config"] == {"effort": "max"}
    assert second["messages"][-2] == {"role": "assistant", "content": tool_turn.content}
    assert second["messages"][-1]["content"][0]["tool_use_id"] == "toolu_1"


def test_agent_falls_back_to_local_answer_when_no_channel_answers(monkeypatch):
    db, user, _, _, _, alipay = _agent_db()
    user.alipay_id = alipay.id
    monkeypatch.setattr(ai_agent, "_post_json", lambda *args, **kwargs: (_ for _ in ()).throw(AIServiceError("provider_unavailable")))

    (content, source, warning, model, steps), events, result = _run_agent(_agent_service("openai", "gpt-6-luna"), db, user, text="8 月花了多少？")

    assert source == "fallback" and model is None and steps == []
    assert "本地回答" in warning and "45.00" in content
    assert events[-1] == {"type": "status", "code": "local_fallback"}
    assert result.period.kind == "month" and result.period.start.isoformat() == "2026-08-01"


def test_ask_endpoint_streams_tool_events_and_saves_a_report(monkeypatch):
    db, user, _, _, _, alipay = _agent_db()
    service = _agent_service("openai", "gpt-6-luna")
    monkeypatch.setattr(ai_module, "service", service)
    monkeypatch.setattr(ai_module, "_user", lambda request, session: user)
    monkeypatch.setattr(ai_module, "SessionLocal", lambda: db)

    from app.ai_insights import resolve_period

    def fake_agent(service_, session, user_id, text, conversation, intent, emit):
        emit({"type": "tool", "name": "summarize_period", "summary": "统计"})
        return ai_agent.AgentResult("【报告】支出 35.00 元。", "model", None, "gpt-6-luna", [{"name": "summarize_period", "summary": "统计", "result": "ok"}], resolve_period("custom", datetime(2026, 8, 1).date(), datetime(2026, 8, 31).date()))

    monkeypatch.setattr(ai_module, "run_ledger_agent", fake_agent)
    payload = ai_module.AIChatRequest(text="生成 2026-08-01 至 2026-08-31 的收支报告", intent="report")
    response = ai_module.ask_ledger(payload, None, db)

    async def collect():
        return [frame async for frame in response.body_iterator]

    frames = [json.loads(frame[len("data: "):]) for frame in asyncio.run(collect()) if frame.startswith("data: ")]
    assert [frame["type"] for frame in frames] == ["tool", "result"]
    result = frames[-1]["data"]
    assert result["reply"] == "【报告】支出 35.00 元。" and result["steps"][0]["name"] == "summarize_period"
    assert result["period"]["start_date"] == "2026-08-01" and result["period"]["end_date"] == "2026-08-31"
    assert result["report_id"] == db.query(AIReport).one().id


def test_api_errors_reach_the_client_in_chinese():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    unauthenticated = client.get("/api/transactions")
    assert (unauthenticated.status_code, unauthenticated.json()["detail"]) == (401, "请先登录。")
    invalid = client.post("/api/auth/login", json={"username": "x"})
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "请求内容有误（password：缺少必填项）。"
    from app.errors import localize_detail

    assert localize_detail("第 2 笔：Category is required") == "第 2 笔：请选择分类。"
    assert localize_detail("自定义文案") == "自定义文案"


def test_ask_endpoint_passes_only_the_question_to_the_agent(monkeypatch):
    db, user, _, _, _, alipay = _agent_db()
    service = _agent_service("openai", "gpt-6-luna")
    monkeypatch.setattr(ai_module, "service", service)
    monkeypatch.setattr(ai_module, "_user", lambda request, session: user)
    monkeypatch.setattr(ai_module, "SessionLocal", lambda: db)
    seen = {}

    def fake_agent(service_, session, user_id, text, conversation, intent, emit):
        seen.update(text=text, intent=intent)
        return ai_agent.AgentResult("好的", "model", None, "gpt-6-luna", [], None)

    monkeypatch.setattr(ai_module, "run_ledger_agent", fake_agent)
    # Page filters (even an unusable date range) are ignored by the assistant.
    payload = ai_module.AIChatRequest(text="花了多少", intent="query", period="custom", start_date=datetime(2026, 8, 31).date(), end_date=datetime(2026, 8, 1).date(), payment_method_id=alipay.id)
    response = ai_module.ask_ledger(payload, None, db)

    async def collect():
        return [frame async for frame in response.body_iterator]

    frames = [json.loads(frame[len("data: "):]) for frame in asyncio.run(collect()) if frame.startswith("data: ")]
    assert frames[-1]["type"] == "result" and frames[-1]["data"]["reply"] == "好的"
    assert seen == {"text": "花了多少", "intent": "query"}


def test_proposal_tools_only_plan_changes():
    db, user, category, dining, wechat, alipay = _agent_db()
    tools = ai_agent.LedgerTools(db, user.id)
    target = db.scalar(select(Transaction).where(Transaction.amount_cents == 3_500))
    before_count = db.query(Transaction).count()

    update = tools.call("propose_update", {"transaction_id": target.id, "amount_cents": 3_600, "payment_method_id": wechat.id, "occurred_at": "2026-08-06 09:30", "reason": "记错了"})
    void = tools.call("propose_void", {"transaction_id": target.id, "reason": "重复"})
    create = tools.call("propose_create", {"kind": "cashflow", "direction": "expense", "amount_cents": 1_200, "category_id": dining.id, "payment_method_id": alipay.id, "occurred_at": "2026-08-07", "notes": "早餐"})
    bad = tools.call("propose_update", {"transaction_id": 99_999, "amount_cents": 1})

    assert update["proposal"]["before"]["amount_cents"] == 3_500 and update["proposal"]["after"]["amount_cents"] == 3_600
    assert update["proposal"]["after"]["account"] == "微信" and update["proposal"]["after"]["occurred_at"] == "2026-08-06 09:30"
    assert update["proposal"]["changes"]["occurred_at"] == "2026-08-06T01:30:00+00:00"
    assert void["proposal"]["type"] == "void" and void["proposal"]["before"]["id"] == target.id
    assert create["proposal"]["draft"]["occurred_at"] == "2026-08-06T16:00:00+00:00" and create["proposal"]["after"]["category"] == "餐饮"
    assert bad == {"error": "找不到这笔流水，请先用 list_transactions 确认 id"}
    assert [item["status"] for item in tools.proposals] == ["pending", "pending", "pending"]
    # Nothing was written.
    assert db.query(Transaction).count() == before_count and db.get(Transaction, target.id).amount_cents == 3_500


def test_ask_endpoint_stores_the_thread_and_history_endpoints_serve_it(monkeypatch):
    db, user, _, _, _, alipay = _agent_db()
    service = _agent_service("openai", "gpt-6-luna")
    monkeypatch.setattr(ai_module, "service", service)
    monkeypatch.setattr(ai_module, "_user", lambda request, session: user)
    # The endpoint opens its own session per question, as in production.
    monkeypatch.setattr(ai_module, "SessionLocal", lambda: Session(db.get_bind(), expire_on_commit=False))
    seen = []

    def fake_agent(service_, session, user_id, text, conversation, intent, emit):
        seen.append([item["content"] for item in conversation])
        proposal = {"type": "void", "transaction_id": 1, "before": {"id": 1}, "index": 0, "status": "pending"}
        return ai_agent.AgentResult(f"回答：{text}", "model", None, "gpt-6-luna", [{"name": "list_accounts", "summary": "查", "result": "ok"}], None, [proposal])

    monkeypatch.setattr(ai_module, "run_ledger_agent", fake_agent)

    def ask(text, conversation_id=None):
        response = ai_module.ask_ledger(ai_module.AIChatRequest(text=text, intent="query", conversation_id=conversation_id), None, db)

        async def collect():
            return [frame async for frame in response.body_iterator]

        return [json.loads(frame[len("data: "):]) for frame in asyncio.run(collect()) if frame.startswith("data: ")][-1]["data"]

    first = ask("第一个问题")
    second = ask("第二个问题", first["conversation_id"])

    assert first["conversation_id"] == second["conversation_id"] and first["message_id"] != second["message_id"]
    assert first["proposals"][0]["type"] == "void"
    # The second question saw the stored first turn as context.
    assert seen == [[], ["第一个问题", "回答：第一个问题"]]
    threads = ai_module.list_conversations(None, db, limit=30)
    assert [(item.title, item.message_count) for item in threads] == [("第一个问题", 4)]
    detail = ai_module.get_conversation(first["conversation_id"], None, db)
    assert [item["role"] for item in detail.messages] == ["user", "assistant", "user", "assistant"]
    assert detail.messages[1]["steps"][0]["name"] == "list_accounts" and detail.messages[1]["proposals"][0]["status"] == "pending"

    marked = ai_module.set_proposal_status(first["conversation_id"], first["message_id"], 0, ai_module.AIProposalStatus(status="applied"), None, db)
    assert marked["proposals"][0]["status"] == "applied"
    assert ai_module.get_conversation(first["conversation_id"], None, db).messages[1]["proposals"][0]["status"] == "applied"
    with pytest.raises(HTTPException):
        ai_module.set_proposal_status(first["conversation_id"], first["message_id"], 5, ai_module.AIProposalStatus(status="ignored"), None, db)

    ai_module.delete_conversation(first["conversation_id"], None, db)
    assert ai_module.list_conversations(None, db, limit=30) == [] and db.query(AIConversationMessage).count() == 0
