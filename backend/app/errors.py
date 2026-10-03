"""Chinese wording for the error messages the API returns to the browser.

Handlers raise short English details (they double as log-friendly codes and
are asserted by tests); the exception handlers in ``main`` translate them on
the way out so the UI never shows English to the user.
"""

from __future__ import annotations

from typing import Any

MESSAGES_ZH: dict[str, str] = {
    "Not authenticated": "请先登录。",
    "Inactive user": "该账号已停用。",
    "Invalid username or password": "用户名或密码错误。",
    "Too many login attempts; try again later": "登录尝试过于频繁，请稍后再试。",
    "Username already exists": "用户名已被使用。",
    "Transaction not found": "找不到这笔流水。",
    "Transaction is already voided": "这笔流水已经作废。",
    "Voided transactions cannot be edited": "已作废的流水不能修改。",
    "Voided transactions cannot be linked": "已作废的流水不能关联往来单位。",
    "Transaction could not be saved": "流水保存失败，请稍后重试。",
    "Transactions could not be saved": "流水保存失败，请稍后重试。",
    "Transaction belongs to another partner": "这笔流水关联的是另一个往来单位。",
    "Transaction already has a partner ledger entry": "这笔流水已经有往来流水了。",
    "Invalid transaction source": "流水来源无效。",
    "Transfer target account is required": "转账需要选择转入/还款账户。",
    "Transfer requires two different accounts": "来源账户和转入/还款账户不能相同。",
    "Source account is inactive": "来源账户已停用。",
    "Target account is inactive": "转入/还款账户已停用。",
    "Payment method not found": "找不到这个资金账户。",
    "Payment method is inactive": "该资金账户已停用。",
    "Category not found": "找不到这个分类。",
    "Category is required": "请选择分类。",
    "Category is inactive": "该分类已停用。",
    "Category direction does not match transaction direction": "分类的收支方向和这笔流水不一致。",
    "Partner not found": "找不到这个往来单位。",
    "Partner is inactive": "该往来单位已停用。",
    "Partner name is ambiguous": "有多个往来单位匹配这个名称，请明确指定。",
    "A partner with this type and name already exists": "同类型下已存在同名的往来单位。",
    "Inactive partners cannot receive ledger entries": "已停用的往来单位不能记录往来流水。",
    "Partner ledger entry not found": "找不到这条往来流水。",
    "Ledger entry not found": "找不到这条往来流水。",
    "Ledger entry is not reversible": "这条往来流水不能冲销。",
    "Compensating ledger entries cannot be reversed again": "冲销流水不能再次冲销。",
    "Could not save partner ledger entry": "往来流水保存失败，请稍后重试。",
    "Invalid partner ledger type": "往来流水类型无效。",
    "Invalid partner ledger type for this account": "该往来单位不支持这种流水类型。",
    "Invalid partner ledger amount": "往来流水金额无效。",
    "Invalid ledger amount": "往来流水金额无效。",
    "Prepaid balance cannot be negative": "预存余额不能为负数。",
    "Credit used balance cannot be negative": "欠款余额不能为负数。",
    "Credit limit cannot be below credit used balance": "授信额度不能低于当前欠款。",
    "Credit use cannot exceed the credit limit": "授信使用不能超过额度。",
    "Customer accounts only support prepaid recharge, credit repayment, credit-limit adjustments, refunds, and balance checks": "客户账户只支持预存充值、授信还款、额度调整、退款和余额核对。",
    "Supplier accounts only support prepaid recharge, credit payment, and balance checks": "供应商账户只支持预存充值、授信付款和余额核对。",
    "Partner mode requires a partner and partner ledger movement": "记录往来余额需要选择往来单位。",
    "Transfer drafts cannot be combined with partner ledger movements": "转账不能同时记录往来余额。",
    "Settlement snapshot not found": "找不到这天的结算记录。",
    "Settlement date cannot be in the future or the current day": "只能结算今天之前的日期。",
    "Could not create settlement snapshot": "结算记录生成失败，请稍后重试。",
    "Recalculation range cannot exceed 10 years": "重算范围不能超过 10 年。",
    "end_date must be on or after start_date": "结束日期不能早于开始日期。",
    "Custom analysis requires a valid date range": "自定义周期需要有效的开始和结束日期。",
    "AI report not found": "找不到这份报告。",
    "Conversation not found": "找不到这个对话。",
    "Proposal not found": "找不到这条修改方案。",
    "AI 服务未配置，请先完成 AI 配置。": "AI 服务未配置，请先完成 AI 配置。",
    "AI configuration storage is unavailable": "AI 配置暂时无法读取，请稍后重试。",
    "AI configuration could not be saved": "AI 配置保存失败，请稍后重试。",
    "Invalid AI base URL": "AI 接口地址无效。",
    "Invalid fallback AI base URL": "备用通道的接口地址无效。",
    "Production AI base URL must use HTTPS": "AI 接口地址必须使用 HTTPS。",
    "Production fallback AI base URL must use HTTPS": "备用通道的接口地址必须使用 HTTPS。",
    "AI model must not be blank": "模型名称不能为空。",
    "Fallback AI model must not be blank": "备用通道的模型名称不能为空。",
    "Choose an API key or clear it, not both": "不能同时填写新的 API Key 和清除 Key。",
    "AI draft is incomplete; parse and fill all required fields first": "AI 草稿信息不完整，请先补齐必填项。",
    "AI cashflow draft requires a category": "请为这笔收支选择分类。",
    "AI transfer draft requires a target account": "转账需要选择转入/还款账户。",
}

# pydantic validation error types -> short Chinese reasons
_VALIDATION_ZH: dict[str, str] = {
    "missing": "缺少必填项",
    "string_too_short": "太短",
    "string_too_long": "太长",
    "too_short": "数量不足",
    "too_long": "数量超出上限",
    "int_parsing": "需要整数",
    "int_type": "需要整数",
    "float_parsing": "需要数字",
    "bool_parsing": "需要是/否",
    "greater_than": "数值过小",
    "greater_than_equal": "数值过小",
    "less_than": "数值过大",
    "less_than_equal": "数值过大",
    "literal_error": "取值不在允许范围内",
    "enum": "取值不在允许范围内",
    "date_from_datetime_parsing": "日期格式不正确",
    "date_parsing": "日期格式不正确",
    "datetime_parsing": "时间格式不正确",
    "json_invalid": "请求内容不是有效的 JSON",
    "extra_forbidden": "包含不支持的字段",
    "string_type": "需要文本",
    "url_parsing": "地址格式不正确",
}


def localize_detail(detail: Any) -> Any:
    """Translate a known English detail; unknown details pass through."""

    if not isinstance(detail, str):
        return detail
    if detail in MESSAGES_ZH:
        return MESSAGES_ZH[detail]
    # Batch confirmations prefix the failing item: "第 2 笔：<detail>".
    prefix, separator, rest = detail.partition("：")
    if separator and prefix.startswith("第 ") and rest in MESSAGES_ZH:
        return f"{prefix}：{MESSAGES_ZH[rest]}"
    return detail


def localize_validation_errors(errors: list[dict[str, Any]]) -> str:
    """One Chinese sentence for a request validation failure."""

    parts: list[str] = []
    for error in errors[:4]:
        location = "/".join(str(item) for item in error.get("loc", ()) if item not in ("body", "query", "path"))
        reason = _VALIDATION_ZH.get(str(error.get("type", "")))
        if reason is None:
            message = str(error.get("msg", ""))
            reason = message.removeprefix("Value error, ") if message.startswith("Value error, ") else "格式不正确"
        parts.append(f"{location}：{reason}" if location else reason)
    return "请求内容有误（" + "；".join(parts) + "）。" if parts else "请求内容有误。"
