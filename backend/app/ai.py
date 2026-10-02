"""Authenticated AI endpoints.

The parser and analyser are intentionally proposal/report APIs.  Only
``/confirm`` can create a transaction, and it requires a literal JSON
``confirm: true`` plus validated user-owned dictionary IDs.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta
import json
import logging
import queue
import threading

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .accounting import (
    _apply_transaction_balance,
    _owned_method_pair,
    _owned_optional_category,
    _transaction_payload,
    _validate_transaction_dictionaries,
)
from .ai_insights import (
    PeriodSpec,
    detect_intent,
    first_transaction_date,
    parse_period_text,
    resolve_period,
    summarize_period,
)
from .ai_schemas import (
    AIAnalyzeRequest,
    AIAnalyzeResponse,
    AIBatchConfirmRequest,
    AIBatchConfirmResponse,
    AIChatRequest,
    AIChatResponse,
    AIConfigRead,
    AIConfigUpdate,
    AIConfirmRequest,
    AIConfirmResponse,
    AIPeriodInfo,
    AIReportRead,
    AIReportSummary,
    AIParsedTransaction,
    AIParseRequest,
    AIParseResponse,
    AISummaryResponse,
)
from .ai_service import AIService, AIServiceError, _validated_base_url, decrypt_api_key, encrypt_api_key
from .auth import current_user
from .config import get_settings
from .db import SessionLocal, get_db
from .models import AIConfig, AIReport, Category, PaymentMethod, Transaction, User
from .partners import (
    _append_entry,
    _owned_partner,
    ledger_payload,
    resolve_partner_reference,
    validate_partner_ledger_type_for_partner,
    validate_partner_reference,
)
from .timezone import business_day_start_utc, business_today, now_utc, to_business, to_utc


router = APIRouter(prefix="/api/ai", tags=["ai"])
service = AIService()
logger = logging.getLogger(__name__)


def _user(request: Request, db: Session) -> User:
    return current_user(request, db)


def _config_response(db: Session, user_id: int) -> AIConfigRead:
    provider = service.provider_for_user(db, user_id)
    row = service._config_row_for_user(db, user_id)
    providers = service.provider_chain_for_user(db, user_id)
    fallback_provider = providers[1] if len(providers) > 1 else None
    user_api_key = decrypt_api_key(getattr(row, "encrypted_api_key", None), service.settings) if row else None
    fallback_api_key = decrypt_api_key(getattr(row, "encrypted_fallback_api_key", None), service.settings) if row else None
    if not user_api_key:
        user_api_key = service.settings.ai_api_key
    if not fallback_api_key:
        fallback_api_key = service.settings.ai_fallback_api_key or (fallback_provider.api_key if fallback_provider else None)
    return AIConfigRead(
        configured=provider.configured,
        base_url=provider.base_url,
        model=provider.model,
        api_key_set=provider.configured,
        api_key_hint=service.key_hint(user_api_key),
        fallback_configured=bool(fallback_api_key),
        fallback_base_url=getattr(row, "fallback_base_url", None) or service.settings.ai_fallback_base_url or (fallback_provider.base_url if fallback_provider else provider.base_url),
        fallback_model=getattr(row, "fallback_model", None) or service.settings.ai_fallback_model or (fallback_provider.model if fallback_provider else provider.model),
        fallback_api_key_set=bool(fallback_api_key),
        fallback_api_key_hint=service.key_hint(fallback_api_key),
    )


@router.get("/config", response_model=AIConfigRead)
def get_ai_config(request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    return _config_response(db, user.id)


@router.post("/config", response_model=AIConfigRead, include_in_schema=False)
@router.patch("/config", response_model=AIConfigRead, include_in_schema=False)
@router.put("/config", response_model=AIConfigRead)
def put_ai_config(payload: AIConfigUpdate, request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    values = payload.model_dump(exclude_unset=True)
    base_url = values.get("base_url")
    fallback_base_url = values.get("fallback_base_url")
    if base_url is not None:
        try:
            base_url = _validated_base_url(base_url)
        except AIServiceError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid AI base URL") from exc
        settings = get_settings()
        if settings.app_env == "production" and not base_url.startswith("https://"):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Production AI base URL must use HTTPS")
    if fallback_base_url is not None:
        try:
            fallback_base_url = _validated_base_url(fallback_base_url)
        except AIServiceError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid fallback AI base URL") from exc
        settings = get_settings()
        if settings.app_env == "production" and not fallback_base_url.startswith("https://"):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Production fallback AI base URL must use HTTPS")
    model = values.get("model")
    if model is not None and not model.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "AI model must not be blank")
    fallback_model = values.get("fallback_model")
    if fallback_model is not None and not fallback_model.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Fallback AI model must not be blank")
    if payload.clear_api_key and payload.api_key is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose an API key or clear it, not both")
    try:
        row = db.scalar(select(AIConfig).where(AIConfig.user_id == user.id))
    except SQLAlchemyError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI configuration storage is unavailable") from exc
    if row is None:
        row = AIConfig(user_id=user.id)
        db.add(row)
    if base_url is not None:
        row.base_url = base_url
    if model is not None:
        row.model = model.strip()
    if fallback_base_url is not None:
        row.fallback_base_url = fallback_base_url
    if fallback_model is not None:
        row.fallback_model = fallback_model.strip()
    if payload.clear_api_key:
        row.encrypted_api_key = None
    elif payload.api_key is not None:
        row.encrypted_api_key = encrypt_api_key(payload.api_key.strip(), service.settings)
    if payload.fallback_api_key is not None:
        row.encrypted_fallback_api_key = encrypt_api_key(payload.fallback_api_key.strip(), service.settings)
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI configuration could not be saved") from exc
    return _config_response(db, user.id)


@router.delete("/config", status_code=status.HTTP_204_NO_CONTENT)
def delete_ai_config(request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    try:
        row = db.scalar(select(AIConfig).where(AIConfig.user_id == user.id))
    except SQLAlchemyError:
        row = None
    if row:
        db.delete(row)
        db.commit()


@router.post("/natural-language", response_model=AIParseResponse, include_in_schema=False)
@router.post("/parse", response_model=AIParseResponse)
def parse_natural_language(payload: AIParseRequest, request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    try:
        return service.parse(
            db,
            user.id,
            payload.text,
            [item.model_dump() for item in payload.conversation],
            payload.reference_time,
            payload.mode,
        )
    except AIServiceError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, _ai_unavailable_message(exc)) from exc


def _ai_unavailable_message(exc: AIServiceError) -> str:
    # Production deliberately has no silent local-parser fallback. Keep
    # provider details out of the response while giving the UI a stable
    # status it can render as “AI unavailable”.
    return "AI 服务未配置，请先完成 AI 配置。" if exc.code == "not_configured" else "AI 服务暂不可用，请稍后重试。"


def _sse_events(run: Callable[[Callable[[dict], None]], AIParseResponse]) -> Iterator[str]:
    """Run a parse in a worker thread and yield its progress as SSE frames.

    The stream always ends with one ``result`` or ``error`` event.
    """

    events: queue.Queue = queue.Queue()

    def worker() -> None:
        try:
            result = run(events.put)
            events.put({"type": "result", "data": result.model_dump(mode="json")})
        except AIServiceError as exc:
            events.put({"type": "error", "status": 503, "detail": _ai_unavailable_message(exc)})
        except Exception:
            logger.exception("AI parse stream failed")
            events.put({"type": "error", "status": 500, "detail": "解析失败，请稍后重试。"})
        finally:
            events.put(None)

    threading.Thread(target=worker, daemon=True).start()
    while True:
        try:
            event = events.get(timeout=10)
        except queue.Empty:
            # A reasoning model can stay silent for a while; a comment frame
            # keeps proxies from treating the response as stalled.
            yield ": keep-alive\n\n"
            continue
        if event is None:
            return
        yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"


@router.post("/parse-stream")
def parse_natural_language_stream(payload: AIParseRequest, request: Request, db: Session = Depends(get_db)):
    """Parse like ``/parse`` while streaming the model's progress as SSE."""

    user_id = _user(request, db).id
    conversation = [item.model_dump() for item in payload.conversation]

    def run(emit: Callable[[dict], None]) -> AIParseResponse:
        # The request-scoped session may be closed before the stream ends.
        with SessionLocal() as session:
            return service.parse(session, user_id, payload.text, conversation, payload.reference_time, payload.mode, on_event=emit)

    return StreamingResponse(
        _sse_events(run),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _partner_exists(db: Session, user_id: int, partner_id: int) -> bool:
    try:
        return validate_partner_reference(db, user_id, partner_id) is not None
    except HTTPException:
        return False


def _cash_draft_dictionaries(
    db: Session, user_id: int, draft: AIParsedTransaction
) -> tuple[Category | None, PaymentMethod, PaymentMethod | None]:
    """Validate a cash/transfer draft against the user's own dictionaries."""

    draft_kind = draft.kind or "cashflow"
    if draft.direction is None or draft.amount_cents is None or draft.payment_method_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "AI draft is incomplete; parse and fill all required fields first")
    if draft_kind == "cashflow" and draft.category_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "AI cashflow draft requires a category")
    if draft_kind == "transfer" and draft.transfer_payment_method_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "AI transfer draft requires a target account")
    category = _owned_optional_category(db, user_id, draft.category_id)
    method, transfer_method = _owned_method_pair(
        db,
        user_id,
        draft.payment_method_id,
        draft.transfer_payment_method_id if draft_kind == "transfer" else None,
        lock=True,
    )
    _validate_transaction_dictionaries(
        kind=draft_kind,
        direction="expense" if draft_kind == "transfer" else draft.direction,
        category=category,
        method=method,
        transfer_method=transfer_method,
    )
    return category, method, transfer_method


def _ai_transaction(
    user_id: int,
    draft: AIParsedTransaction,
    occurred_at: datetime,
    category: Category | None,
    method: PaymentMethod,
    transfer_method: PaymentMethod | None,
    partner,
) -> Transaction:
    """Build a confirmed AI transaction and apply it to the account balances."""

    draft_kind = draft.kind or "cashflow"
    tx = Transaction(
        user_id=user_id,
        occurred_at=occurred_at,
        kind=draft_kind,
        direction="expense" if draft_kind == "transfer" else draft.direction,
        amount_cents=draft.amount_cents,
        category_id=category.id if category else None,
        payment_method_id=method.id,
        transfer_payment_method_id=transfer_method.id if transfer_method else None,
        partner_id=partner.id if partner else None,
        notes=draft.notes,
        source="ai",
        status="normal",
    )
    _apply_transaction_balance(tx, method, transfer_method)
    return tx


@router.post("/confirm", response_model=AIConfirmResponse, status_code=status.HTTP_201_CREATED)
def confirm_ai_draft(payload: AIConfirmRequest, request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    draft = payload.draft
    mode = payload.mode or ("combined" if payload.partner_ledger_type or draft.partner_ledger_type else "cash")
    ledger_type = payload.partner_ledger_type or draft.partner_ledger_type
    ledger_amount = payload.partner_ledger_amount_cents
    if ledger_amount is None:
        ledger_amount = draft.partner_ledger_amount_cents
    if ledger_amount is None and mode in {"partner", "combined"}:
        ledger_amount = draft.amount_cents
    if mode == "cash":
        ledger_type = None
        ledger_amount = None
    draft_kind = draft.kind or "cashflow"
    if draft_kind == "transfer" and mode == "combined":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Transfer drafts cannot be combined with partner ledger movements")
    if mode in {"cash", "combined"}:
        category, method, transfer_method = _cash_draft_dictionaries(db, user.id, draft)
    else:
        category = method = transfer_method = None
    partner = resolve_partner_reference(
        db,
        user.id,
        draft.partner_id,
        draft.partner_name,
    ) if (mode in {"partner", "combined"} or draft.partner_id or draft.partner_name) else None
    if mode in {"partner", "combined"} and (partner is None or ledger_type is None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Partner mode requires a partner and partner ledger movement")
    if partner is not None and ledger_type is not None:
        validate_partner_ledger_type_for_partner(partner, ledger_type)
    if ledger_type is not None and (
        ledger_amount is None
        or (ledger_amount == 0 and ledger_type != "balance_check")
        or (ledger_type not in {"limit_adjust", "balance_check"} and ledger_amount < 0)
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid partner ledger amount")
    # AI parser values may carry the Beijing +08:00 offset; persist the same
    # instant in UTC just like the normal transaction endpoint.
    occurred_at = to_utc(draft.occurred_at) if draft.occurred_at else now_utc()
    tx = None
    if mode in {"cash", "combined"}:
        tx = _ai_transaction(user.id, draft, occurred_at, category, method, transfer_method, partner)
        db.add(tx)
    try:
        db.flush()
        ledger = None
        reconciliation = None
        if ledger_type is not None and partner is not None:
            # Lock order is transaction -> partner, matching the accounting
            # void path and keeping this combined operation deadlock-safe.
            locked_partner = _owned_partner(db, user.id, partner.id, lock=True)
            entry = _append_entry(
                db,
                locked_partner,
                user_id=user.id,
                entry_type=ledger_type,
                amount_cents=ledger_amount,
                # Partner-only confirmations do not create a Transaction.
                # Use the normalized proposal instant for both modes; referring
                # to ``tx.occurred_at`` here would raise AttributeError and
                # leave the session in a failed transaction for every
                # partner-only write.
                occurred_at=occurred_at,
                transaction_id=tx.id if tx else None,
                notes="AI 记账确认自动生成",
            )
            db.flush()
            ledger = ledger_payload(entry)
            observed = payload.observed_balance_cents
            observed_kind = payload.observed_balance_kind
            if observed is None:
                observed = draft.partner_balance_after_cents
            if observed_kind is None:
                observed_kind = draft.partner_balance_kind
            if observed_kind is None and partner is not None:
                observed_kind = "credit_used" if str(partner.type).lower() == "customer" else "prepaid_balance"
            if observed is not None:
                expected_by_kind = {
                    "prepaid_balance": int(locked_partner.prepaid_balance_cents or 0),
                    "credit_used": int(locked_partner.credit_used_cents or 0),
                }
                expected = expected_by_kind.get(observed_kind or "")
                if expected is not None:
                    delta = int(observed) - expected
                    reconciliation = {
                        "kind": observed_kind,
                        "observed_balance_cents": int(observed),
                        "expected_balance_cents": expected,
                        "delta_cents": delta,
                        "applied": False,
                    }
                    # Reconciliation is opt-in so a discrepancy is never
                    # silently mislabeled as customer usage. When requested,
                    # append a second auditable movement in the same commit.
                    if payload.apply_balance_reconciliation and delta:
                        if observed_kind == "prepaid_balance":
                            correction_type = "prepaid_in" if delta > 0 else "prepaid_out"
                        else:
                            correction_type = "credit_use" if delta > 0 else "credit_repay"
                        correction = _append_entry(
                            db, locked_partner, user_id=user.id,
                            entry_type=correction_type, amount_cents=delta if correction_type == "limit_adjust" else abs(delta),
                            occurred_at=occurred_at, transaction_id=tx.id if tx else None,
                            notes="AI 余额盘点校准",
                        )
                        db.flush()
                        reconciliation["applied"] = True
                        reconciliation["correction_ledger"] = ledger_payload(correction)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Transaction could not be saved") from exc
    if tx is not None:
        db.refresh(tx)
    warning = None
    return AIConfirmResponse(
        mode=mode,
        transaction=_transaction_payload(
            tx,
            category.name if category else None,
            method.name,
            transfer_method.name if transfer_method else None,
            partner.name if partner else None,
        )
        if tx
        else None,
        partner_ledger=ledger,
        balance_reconciliation=reconciliation,
        warning=warning,
    )


@router.post("/confirm-batch", response_model=AIBatchConfirmResponse, status_code=status.HTTP_201_CREATED)
def confirm_ai_drafts(payload: AIBatchConfirmRequest, request: Request, db: Session = Depends(get_db)):
    """Write several confirmed cash/transfer drafts in one commit.

    Either every draft is recorded or none is.  Partner ledger movements are
    not part of a batch; they keep using the single ``/confirm`` contract.
    """

    user = _user(request, db)
    # Lock every involved account once, in id order, so drafts that share an
    # account cannot deadlock against a concurrent write.
    method_ids = {
        item_id
        for draft in payload.drafts
        for item_id in (draft.payment_method_id, draft.transfer_payment_method_id)
        if item_id is not None
    }
    saved = []
    try:
        if method_ids:
            db.scalars(
                select(PaymentMethod)
                .where(PaymentMethod.user_id == user.id, PaymentMethod.id.in_(method_ids))
                .order_by(PaymentMethod.id)
                .with_for_update()
            ).all()
        for index, draft in enumerate(payload.drafts, start=1):
            try:
                category, method, transfer_method = _cash_draft_dictionaries(db, user.id, draft)
                partner = resolve_partner_reference(db, user.id, draft.partner_id, draft.partner_name) if (draft.partner_id or draft.partner_name) else None
            except HTTPException as exc:
                raise HTTPException(exc.status_code, f"第 {index} 笔：{exc.detail}") from exc
            occurred_at = to_utc(draft.occurred_at) if draft.occurred_at else now_utc()
            tx = _ai_transaction(user.id, draft, occurred_at, category, method, transfer_method, partner)
            db.add(tx)
            saved.append((tx, category, method, transfer_method, partner))
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Transactions could not be saved") from exc
    transactions = []
    for tx, category, method, transfer_method, partner in saved:
        db.refresh(tx)
        transactions.append(
            _transaction_payload(
                tx,
                category.name if category else None,
                method.name,
                transfer_method.name if transfer_method else None,
                partner.name if partner else None,
            )
        )
    return AIBatchConfirmResponse(transactions=transactions)


def _resolve_period_or_422(kind: str, start_date: date | None, end_date: date | None) -> PeriodSpec:
    try:
        return resolve_period(kind, start_date, end_date)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Custom analysis requires a valid date range") from exc


def _period_bounds(payload: AIAnalyzeRequest, db: Session, user_id: int) -> tuple[date, date, str]:
    spec = _resolve_period_or_422(payload.period, payload.start_date, payload.end_date)
    start = spec.start
    if start is None:
        # "all" has an open lower bound; anchor the report on the first
        # transaction so the stored history row keeps a real date range.
        start = first_transaction_date(db, user_id) or spec.end
    return start, spec.end, spec.kind


def _period_info(spec: PeriodSpec, summary: dict) -> AIPeriodInfo:
    period = summary.get("period") or spec.as_dict()
    return AIPeriodInfo(
        kind=spec.kind,
        label=period.get("label") or spec.label,
        start_date=date.fromisoformat(period["start_date"]) if period.get("start_date") else None,
        end_date=spec.end,
    )


@router.get("/summary", response_model=AISummaryResponse)
def period_summary(
    request: Request,
    db: Session = Depends(get_db),
    period: str = Query(default="month", pattern="^(day|week|month|year|all|custom)$"),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
):
    """Aggregated income/expense figures for charts; never calls a model."""

    user = _user(request, db)
    spec = _resolve_period_or_422(period, start_date, end_date)
    summary = summarize_period(db, user.id, spec)
    return AISummaryResponse(period=_period_info(spec, summary), summary=summary)


@router.post("/chat", response_model=AIChatResponse)
def chat_about_finances(payload: AIChatRequest, request: Request, db: Session = Depends(get_db)):
    """Answer ledger questions or write a report from aggregated data.

    A bookkeeping sentence returns ``intent=bookkeeping`` without touching the
    model so the client can continue with the parse/confirm flow.  Nothing in
    this endpoint writes a transaction.
    """

    user = _user(request, db)
    conversation = [item.model_dump() for item in payload.conversation]
    has_context = any(item["role"] == "assistant" for item in conversation)
    intent = detect_intent(payload.text, has_context)
    if payload.period is not None and intent == "bookkeeping":
        # An explicit period from a quick action always means a question.
        intent = "query"
    if intent == "bookkeeping":
        return AIChatResponse(intent="bookkeeping")
    if payload.period is not None:
        spec = _resolve_period_or_422(payload.period, payload.start_date, payload.end_date)
    else:
        today = to_business(payload.reference_time).date() if payload.reference_time else business_today()
        spec = parse_period_text(payload.text, today)
        if spec is None:
            # Look back at the user's own recent turns so “那支出呢？”
            # keeps the period established earlier in the conversation.
            for item in reversed(conversation):
                if item["role"] == "user":
                    spec = parse_period_text(item["content"], today)
                    if spec is not None:
                        break
        if spec is None:
            spec = resolve_period("month", today=today)
    summary = summarize_period(db, user.id, spec)
    try:
        content, source, warning, model_name = service.chat_reply(db, user.id, payload.text, conversation, summary, intent)
    except AIServiceError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI 服务暂不可用，请稍后重试。") from exc
    content = content[:100_000]
    report_id: int | None = None
    if intent == "report" and payload.save_history:
        start = spec.start or first_transaction_date(db, user.id) or spec.end
        report = AIReport(
            user_id=user.id,
            period=spec.kind,
            start_date=_date_start(start),
            end_date=_date_start(spec.end),
            request_summary=json.dumps(summary, ensure_ascii=False)[:200_000],
            response_text=content,
            source=source,
            model=model_name if source == "model" else None,
        )
        db.add(report)
        try:
            db.commit()
            db.refresh(report)
            report_id = report.id
        except SQLAlchemyError:
            db.rollback()
            warning = warning or "报告已生成，但历史记录暂不可用。"
    return AIChatResponse(
        intent=intent,
        reply=content,
        period=_period_info(spec, summary),
        summary=summary,
        report_id=report_id,
        source=source,
        model=model_name if source == "model" else None,
        warning=warning,
    )


def _date_start(value: date) -> datetime:
    # Analysis periods are Beijing calendar dates, while the aggregate query
    # still receives UTC boundaries for efficient indexed comparisons.
    return business_day_start_utc(value)


@router.post("/analyze", response_model=AIAnalyzeResponse)
def analyze_finances(payload: AIAnalyzeRequest, request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    start_date, end_date, period = _period_bounds(payload, db, user.id)
    summary = service.aggregate(db, user.id, _date_start(start_date), _date_start(end_date + timedelta(days=1)))
    content, source, warning, model_name = service.analyze_text(db, user.id, summary, start_date, end_date)
    content = content[:100_000]
    report_id: int | None = None
    if payload.save_history:
        report = AIReport(user_id=user.id, period=period, start_date=_date_start(start_date), end_date=_date_start(end_date), request_summary=json.dumps(summary, ensure_ascii=False)[:200_000], response_text=content, source=source, model=model_name if source == "model" else None)
        db.add(report)
        try:
            db.commit()
            db.refresh(report)
            report_id = report.id
        except SQLAlchemyError:
            db.rollback()
            warning = warning or "分析已生成，但历史记录暂不可用。"
    return AIAnalyzeResponse(report_id=report_id, period=period, start_date=start_date, end_date=end_date, source=source, model=model_name if source == "model" else None, content=content, data_summary=summary, warning=warning, generated_at=now_utc())


def _report_to_read(report: AIReport) -> AIReportRead:
    try:
        summary = json.loads(report.request_summary)
    except (TypeError, json.JSONDecodeError):
        summary = {}
    return AIReportRead(report_id=report.id, period=report.period, start_date=to_business(report.start_date).date(), end_date=to_business(report.end_date).date(), source=report.source if report.source in {"model", "fallback"} else "fallback", model=report.model, content=report.response_text, data_summary=summary, warning=None, generated_at=report.created_at)


@router.get("/reports", response_model=list[AIReportSummary])
@router.get("/history", response_model=list[AIReportSummary], include_in_schema=False)
def list_ai_reports(request: Request, db: Session = Depends(get_db), limit: int = Query(default=20, ge=1, le=100)):
    user = _user(request, db)
    try:
        rows = db.scalars(select(AIReport).where(AIReport.user_id == user.id).order_by(AIReport.created_at.desc(), AIReport.id.desc()).limit(limit)).all()
    except SQLAlchemyError:
        rows = []
    return [AIReportSummary(id=row.id, period=row.period, start_date=to_business(row.start_date).date(), end_date=to_business(row.end_date).date(), source=row.source if row.source in {"model", "fallback"} else "fallback", model=row.model, created_at=row.created_at) for row in rows]


@router.get("/reports/{report_id}", response_model=AIReportRead)
@router.get("/history/{report_id}", response_model=AIReportRead, include_in_schema=False)
def get_ai_report(report_id: int, request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    row = db.scalar(select(AIReport).where(AIReport.id == report_id, AIReport.user_id == user.id))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "AI report not found")
    return _report_to_read(row)
