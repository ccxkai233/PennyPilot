from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.ai import confirm_ai_draft
from app.ai_schemas import AIConfirmRequest, AIParsedTransaction
from app.ai_service import (
    AI_PARSE_MAX_TOKENS,
    AI_PARSE_RESPONSE_FORMAT,
    AIService,
    AIServiceError,
    Provider,
    _parse_time,
    decrypt_api_key,
    encrypt_api_key,
    reasoning_controls_for_provider,
    response_format_for_provider,
)
from app.config import Settings
from app.db import Base
from app.models import Category, Partner, PartnerLedgerEntry, PaymentMethod, Transaction, User
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
