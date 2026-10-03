/**
 * Small, dependency-free API client used by the Vue views.
 *
 * The API is same-origin in production (Caddy proxies /api), while Vite can
 * be pointed at a separate backend with VITE_API_BASE_URL during development.
 */
const configuredBase = import.meta.env.VITE_API_BASE_URL || ''
export const API_BASE_URL = configuredBase.replace(/\/$/, '')

// PennyPilot is a Beijing-time application.  Timestamps are still sent to
// and received from the API as UTC instants, but every date-only value and
// every datetime-local control is interpreted in this zone.  Keeping the
// zone explicit avoids silently inheriting the browser/host timezone (which
// is often UTC in production and can differ from a user's device).
export const APP_TIME_ZONE = 'Asia/Shanghai'
export const BEIJING_UTC_OFFSET = '+08:00'

const RETRYABLE_HTTP_STATUSES = new Set([408, 425, 429, 500, 502, 503, 504])
const AI_API_PATH = /^\/api\/ai(?:\/|$)/

const LOCAL_DATE_TIME_PATTERN = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,3}))?)?$/
const NAIVE_TIMESTAMP_PATTERN = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?$/
const DATE_ONLY_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/
const beijingPartsFormatter = new Intl.DateTimeFormat('en-US', {
  timeZone: APP_TIME_ZONE,
  year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit',
  hourCycle: 'h23',
})

function validDate(value) {
  return value instanceof Date && !Number.isNaN(value.getTime()) ? value : null
}

function parseTimestamp(value) {
  if (value instanceof Date) return validDate(value)
  if (typeof value === 'number' && Number.isFinite(value)) return validDate(new Date(value))
  const text = String(value ?? '').trim()
  if (!text) return null

  // JavaScript treats a date-only string as UTC, which is exactly what we
  // need for parsing a calendar key (the caller can use the Beijing helpers
  // below when it means Beijing midnight instead).
  if (DATE_ONLY_PATTERN.test(text)) return validDate(new Date(`${text}T00:00:00.000Z`))

  // API responses from SQLite/legacy installations can contain a naive
  // datetime.  The backend timestamp contract is UTC, so make that intent
  // explicit instead of allowing Date.parse to use the browser timezone.
  const naiveMatch = text.match(NAIVE_TIMESTAMP_PATTERN)
  if (naiveMatch) {
    const fraction = naiveMatch[7] ? `.${naiveMatch[7].slice(0, 3).padEnd(3, '0')}` : ''
    const normalized = `${naiveMatch[1]}-${naiveMatch[2]}-${naiveMatch[3]}T${naiveMatch[4]}:${naiveMatch[5]}${naiveMatch[6] ? `:${naiveMatch[6]}` : ':00'}${fraction}Z`
    return validDate(new Date(normalized))
  }
  return validDate(new Date(text))
}

function partsForBeijing(value) {
  const date = parseTimestamp(value)
  if (!date) return null
  const parts = Object.fromEntries(beijingPartsFormatter.formatToParts(date).map(({ type, value: part }) => [type, part]))
  return {
    year: Number(parts.year), month: Number(parts.month), day: Number(parts.day),
    hour: Number(parts.hour), minute: Number(parts.minute), second: Number(parts.second),
  }
}

function pad(value) { return String(value).padStart(2, '0') }

/** Return the Beijing calendar date (YYYY-MM-DD) for an instant. */
export function beijingDateIso(value = new Date()) {
  const parts = partsForBeijing(value)
  return parts ? `${parts.year}-${pad(parts.month)}-${pad(parts.day)}` : ''
}

/** Add whole calendar days to a Beijing YYYY-MM-DD key. */
export function beijingDateAddDays(value, amount) {
  const text = String(value ?? '').trim()
  const match = text.match(DATE_ONLY_PATTERN)
  const days = Number(amount)
  if (!match || !Number.isInteger(days)) return ''
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])))
  date.setUTCDate(date.getUTCDate() + days)
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`
}

/** Return a UTC epoch value for sorting API timestamps consistently. */
export function timestampValue(value) {
  const date = parseTimestamp(value)
  return date ? date.getTime() : NaN
}

/** Current instant in the explicit UTC representation used by the API. */
export function utcNowIso() { return new Date().toISOString() }

export class ApiError extends Error {
  constructor(message, status, details = null, meta = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.details = details
    this.kind = meta.kind || 'unknown'
    this.retryable = Boolean(meta.retryable)
    this.path = meta.path || ''
    this.attempts = Number.isInteger(meta.attempts) ? meta.attempts : 1
    this.cause = meta.cause || null
  }
}

function errorMessage(payload, fallback) {
  if (!payload) return fallback
  if (typeof payload === 'string') return payload
  if (typeof payload.detail === 'string') return payload.detail
  if (Array.isArray(payload.detail)) {
    return payload.detail.map((item) => item.msg || item.message || String(item)).join('；')
  }
  if (typeof payload.message === 'string') return payload.message
  return fallback
}

function payloadText(payload) {
  if (typeof payload === 'string') return payload
  if (typeof payload?.detail === 'string') return payload.detail
  if (Array.isArray(payload?.detail)) return payload.detail.map((item) => item?.msg || item?.message || String(item)).join('；')
  if (typeof payload?.message === 'string') return payload.message
  return ''
}

function classifyApiFailure(path, status, payload, cause, timedOut = false) {
  const isAi = AI_API_PATH.test(path)
  const detail = payloadText(payload)
  if (timedOut || (status === 0 && cause?.name === 'AbortError')) {
    return {
      kind: 'timeout',
      retryable: true,
      message: isAi ? 'AI 请求响应超时，AI 服务可能正在繁忙，请稍后重试。' : '请求响应超时，请稍后重试。',
    }
  }
  if (status === 0) {
    return {
      kind: 'backend_unreachable',
      retryable: true,
      message: '无法连接后端服务，请检查网络或后端服务是否运行。',
    }
  }
  // A proxy can also emit a bare 503 for an unavailable backend.  An AI 503
  // is only classified as an AI failure when the backend supplied a detail
  // message; this prevents Caddy/nginx outages from being mislabeled as AI.
  if (status === 502 || status === 504 || (status === 503 && (!isAi || !detail))) {
    return {
      kind: 'backend_unreachable',
      retryable: true,
      message: '后端服务暂时不可用，请稍后重试。',
    }
  }
  if (isAi && status >= 500) {
    return {
      kind: status === 503 ? 'ai_unavailable' : 'ai_error',
      retryable: true,
      message: detail && /ai|AI|模型|服务/.test(detail) ? detail : 'AI 服务暂时不可用，请稍后重试。',
    }
  }
  if (status >= 500) {
    return {
      kind: 'backend_error',
      retryable: true,
      message: '后端服务发生异常，请稍后重试。',
    }
  }
  if (status === 429) {
    return { kind: 'rate_limited', retryable: true, message: detail || '请求过于频繁，请稍后重试。' }
  }
  return { kind: 'business_error', retryable: false, message: detail || '' }
}

function createTimeoutSignal(signal, timeoutMs) {
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    return { signal, timedOut: () => false, cleanup: () => {} }
  }
  const controller = new AbortController()
  let timedOut = false
  const timer = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeoutMs)
  const abortFromCaller = () => controller.abort(signal?.reason)
  if (signal) {
    if (signal.aborted) abortFromCaller()
    else signal.addEventListener('abort', abortFromCaller, { once: true })
  }
  return {
    signal: controller.signal,
    timedOut: () => timedOut,
    cleanup: () => {
      clearTimeout(timer)
      signal?.removeEventListener('abort', abortFromCaller)
    },
  }
}

function shouldRetry(error, attempt, maxRetries) {
  return error instanceof ApiError && error.retryable && attempt < maxRetries
}

function retryDelay(delayMs, attempt) {
  const base = Number.isFinite(delayMs) && delayMs >= 0 ? delayMs : 450
  return Math.min(4_000, base * (2 ** attempt))
}

export async function apiFetch(path, options = {}) {
  const {
    body,
    headers = {},
    retry = 0,
    retryDelayMs = 450,
    timeoutMs = 0,
    onRetry,
    ...rest
  } = options
  const requestHeaders = { Accept: 'application/json', ...headers }
  let requestBody = body
  if (body !== undefined && body !== null && !(body instanceof FormData)) {
    requestHeaders['Content-Type'] = 'application/json'
    requestBody = JSON.stringify(body)
  }
  const maxRetries = Math.max(0, Number.isInteger(retry) ? retry : 0)
  for (let attempt = 0; attempt <= maxRetries; attempt += 1) {
    const requestSignal = createTimeoutSignal(rest.signal, timeoutMs)
    let response
    try {
      response = await fetch(`${API_BASE_URL}${path}`, {
        ...rest,
        body: requestBody,
        headers: requestHeaders,
        credentials: 'include',
        signal: requestSignal.signal,
      })
    } catch (cause) {
      const failure = classifyApiFailure(path, 0, null, cause, requestSignal.timedOut())
      const error = new ApiError(failure.message, 0, cause, {
        kind: failure.kind,
        retryable: failure.retryable,
        path,
        attempts: attempt + 1,
        cause,
      })
      requestSignal.cleanup()
      if (shouldRetry(error, attempt, maxRetries)) {
        try { await onRetry?.({ error, attempt: attempt + 1, nextAttempt: attempt + 2, maxRetries }) } catch { /* UI callbacks must not break retry */ }
        await new Promise((resolve) => setTimeout(resolve, retryDelay(retryDelayMs, attempt)))
        continue
      }
      throw error
    }
    const contentType = response.headers.get('content-type') || ''
    let payload = null
    try {
      if (response.status !== 204) {
        try {
          payload = contentType.includes('application/json')
            ? await response.json()
            : await response.text()
        } catch {
          payload = null
        }
      }
    } finally {
      // Keep the timeout active while the response body is being consumed;
      // fetch() may resolve before response.json()/response.text() finishes.
      requestSignal.cleanup()
    }
    if (!response.ok) {
      if (response.status === 401 && typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('pennypilot:unauthorized'))
      }
      const failure = classifyApiFailure(path, response.status, payload, null)
      const error = new ApiError(
        failure.message || errorMessage(payload, `请求失败（${response.status}）`),
        response.status,
        payload,
        { kind: failure.kind, retryable: failure.retryable, path, attempts: attempt + 1 },
      )
      if (shouldRetry(error, attempt, maxRetries)) {
        try { await onRetry?.({ error, attempt: attempt + 1, nextAttempt: attempt + 2, maxRetries }) } catch { /* UI callbacks must not break retry */ }
        await new Promise((resolve) => setTimeout(resolve, retryDelay(retryDelayMs, attempt)))
        continue
      }
      throw error
    }
    return payload
  }
  throw new ApiError('请求失败，请稍后重试。', 0, null, { kind: 'unknown', retryable: true, path })
}

export function listPayload(payload) {
  if (Array.isArray(payload)) return payload
  if (Array.isArray(payload?.items)) return payload.items
  if (Array.isArray(payload?.results)) return payload.results
  if (Array.isArray(payload?.data)) return payload.data
  return []
}

export function amountToCents(value) {
  if (typeof value === 'number' && Number.isInteger(value)) return value
  const text = String(value ?? '').trim().replace(/,/g, '')
  if (!text || !/^\d+(\.\d{0,2})?$/.test(text)) return NaN
  const [yuan, fraction = ''] = text.split('.')
  return Number(yuan) * 100 + Number((fraction + '00').slice(0, 2))
}

export function centsToAmount(cents) {
  const value = Number(cents ?? 0)
  return Number.isFinite(value) ? (value / 100).toFixed(2) : '0.00'
}

export function formatMoney(cents, currency = '¥') {
  const value = Number(cents ?? 0)
  if (!Number.isFinite(value)) return `${currency} 0.00`
  return `${currency} ${new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value / 100)}`
}

/**
 * Convert an API timestamp (a UTC instant) into a datetime-local string in
 * Beijing time.  datetime-local has no timezone information by design, so
 * this function is the single boundary where that wall-clock value is made.
 */
export function localDateTimeValue(value = new Date()) {
  const text = typeof value === 'string' ? value.trim() : ''
  // A date-only payload represents a business calendar date, not an instant;
  // expose it as Beijing midnight in the editing control.
  if (DATE_ONLY_PATTERN.test(text)) return `${text}T00:00`
  const parts = partsForBeijing(value)
  if (!parts) return ''
  return `${parts.year}-${pad(parts.month)}-${pad(parts.day)}T${pad(parts.hour)}:${pad(parts.minute)}`
}

/**
 * Convert a datetime-local value entered as Beijing wall-clock time to a UTC
 * ISO timestamp for the API.  Values that already carry an explicit offset
 * are respected, which keeps this helper safe for programmatic callers too.
 */
export function beijingDateTimeToUtcIso(value) {
  if (value instanceof Date) return validDate(value)?.toISOString() || ''
  const text = String(value ?? '').trim()
  if (!text) return ''

  const explicitZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(text)
  if (explicitZone) return parseTimestamp(text)?.toISOString() || ''

  const dateOnly = text.match(DATE_ONLY_PATTERN)
  const match = text.match(LOCAL_DATE_TIME_PATTERN)
  const year = Number(dateOnly?.[1] || match?.[1])
  const month = Number(dateOnly?.[2] || match?.[2])
  const day = Number(dateOnly?.[3] || match?.[3])
  const hour = Number(match?.[4] || 0)
  const minute = Number(match?.[5] || 0)
  const second = Number(match?.[6] || 0)
  const milliseconds = Number(String(match?.[7] || '').padEnd(3, '0') || 0)
  if (![year, month, day, hour, minute, second, milliseconds].every(Number.isFinite)) return ''

  // Date.UTC's month/day normalization is useful for arithmetic but would
  // hide malformed form values.  Validate the wall-clock ranges first.
  if (month < 1 || month > 12 || day < 1 || day > 31 || hour > 23 || minute > 59 || second > 59 || milliseconds > 999) return ''
  const date = new Date(Date.UTC(year, month - 1, day, hour - 8, minute, second, milliseconds))
  if (!validDate(date)) return ''
  const roundTrip = partsForBeijing(date)
  if (!roundTrip || roundTrip.year !== year || roundTrip.month !== month || roundTrip.day !== day || roundTrip.hour !== hour || roundTrip.minute !== minute || roundTrip.second !== second) return ''
  return date.toISOString()
}

// A descriptive alias for call sites that want to make the direction clear.
export const datetimeLocalToUtcIso = beijingDateTimeToUtcIso

/** Convert a Beijing date-only value to a UTC instant at its start/end. */
export function beijingDateBoundary(value, endOfDay = false) {
  const text = String(value ?? '').trim()
  if (!DATE_ONLY_PATTERN.test(text)) return ''
  return beijingDateTimeToUtcIso(`${text}T${endOfDay ? '23:59:59.999' : '00:00:00.000'}`)
}

export function formatDateTime(value) {
  if (!value) return '—'
  const parts = partsForBeijing(value)
  if (!parts) return String(value)
  return `${parts.year}-${pad(parts.month)}-${pad(parts.day)} ${pad(parts.hour)}:${pad(parts.minute)}`
}

export const authApi = {
  me: () => apiFetch('/api/auth/me'),
  login: (credentials) => apiFetch('/api/auth/login', { method: 'POST', body: credentials }),
  register: (credentials) => apiFetch('/api/auth/register', { method: 'POST', body: credentials }),
  logout: () => apiFetch('/api/auth/logout', { method: 'POST' }),
}

export const categoriesApi = {
  list: () => apiFetch('/api/categories').then(listPayload),
  create: (data) => apiFetch('/api/categories', { method: 'POST', body: data }),
  update: (id, data) => apiFetch(`/api/categories/${id}`, { method: 'PATCH', body: data }),
  remove: (id) => apiFetch(`/api/categories/${id}`, { method: 'DELETE' }),
}

export const paymentMethodsApi = {
  list: (filters = {}) => apiFetch(`/api/payment-methods${queryString(filters)}`).then(listPayload),
  create: (data) => apiFetch('/api/payment-methods', { method: 'POST', body: data }),
  update: (id, data) => apiFetch(`/api/payment-methods/${id}`, { method: 'PATCH', body: data }),
  remove: (id) => apiFetch(`/api/payment-methods/${id}`, { method: 'DELETE' }),
}

export const transactionsApi = {
  list: (filters = {}) => {
    const query = new URLSearchParams()
    // Keep the shorter from/to names convenient for views. During the v0.2
    // transition both date-only and datetime filter names are sent; FastAPI
    // ignores the unused pair, so this remains compatible with both API forms.
    const aliases = { from: 'occurred_from', to: 'occurred_to' }
    Object.entries(filters).forEach(([key, value]) => {
      if (value === undefined || value === null || value === '') return
      let queryValue = value
      if ((key === 'from' || key === 'to') && /^\d{4}-\d{2}-\d{2}$/.test(String(value))) {
        // Keep the friendly date-only parameters for the API's canonical
        // calendar filtering, and also expose explicit UTC bounds for older
        // or alternate endpoints.  Both are derived from Beijing midnight,
        // never from the browser's local timezone.
        // `occurred_to` is a half-open upper bound in compatible APIs, so
        // use the next Beijing midnight instead of an end-of-day millisecond.
        queryValue = beijingDateBoundary(key === 'to' ? beijingDateAddDays(value, 1) : value)
        query.set(key === 'from' ? 'start_date' : 'end_date', String(value))
      }
      query.set(aliases[key] || key, queryValue)
    })
    const suffix = query.toString() ? `?${query.toString()}` : ''
    return apiFetch(`/api/transactions${suffix}`).then(listPayload)
  },
  summary: () => apiFetch('/api/transactions/summary'),
  create: (data) => apiFetch('/api/transactions', { method: 'POST', body: data }),
  update: (id, data) => apiFetch(`/api/transactions/${id}`, { method: 'PATCH', body: data }),
  voidTransaction: (id, reason = null) => apiFetch(`/api/transactions/${id}/void`, {
    method: 'POST',
    body: reason ? { reason } : {},
  }),
  remove: (id) => apiFetch(`/api/transactions/${id}`, { method: 'DELETE' }),
}

/**
 * Build a query string while keeping view code readable.  Empty values are
 * omitted and arrays are emitted as repeated keys, which is understood by
 * FastAPI as well as most compatible REST implementations.
 */
export function queryString(params = {}) {
  const query = new URLSearchParams()
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    if (Array.isArray(value)) {
      value.forEach((item) => {
        if (item !== undefined && item !== null && item !== '') query.append(key, String(item))
      })
      return
    }
    query.set(key, String(value))
  })
  const encoded = query.toString()
  return encoded ? `?${encoded}` : ''
}

/**
 * Counterparty accounts (customers and suppliers).  The server may return a
 * bare array or a paginated {items} envelope; listPayload normalises both.
 */
export const partnersApi = {
  list: (filters = {}) => apiFetch(`/api/partners${queryString(filters)}`).then(listPayload),
  get: (id) => apiFetch(`/api/partners/${id}`),
  create: (data) => apiFetch('/api/partners', { method: 'POST', body: data }),
  update: (id, data) => apiFetch(`/api/partners/${id}`, { method: 'PATCH', body: data }),
  remove: (id) => apiFetch(`/api/partners/${id}`, { method: 'DELETE' }),
  ledger: (id, filters = {}) => apiFetch(`/api/partners/${id}/ledger${queryString(filters)}`).then(listPayload),
  addLedgerEntry: (id, data) => apiFetch(`/api/partners/${id}/ledger`, { method: 'POST', body: data }),
  reverseLedger: (id, entryId, reason = null) => apiFetch(`/api/partners/${id}/ledger/${entryId}/reverse`, { method: 'POST', body: reason ? { reason } : {} }),
  balance: (id) => apiFetch(`/api/partners/${id}/balance`),
}

/** AI natural-language bookkeeping and financial analysis endpoints. */
export const aiApi = {
  parse: (data, requestOptions = {}) => apiFetch('/api/ai/parse', {
    method: 'POST',
    body: data,
    retry: 1,
    timeoutMs: 75_000,
    ...requestOptions,
  }),
  /**
   * Parse a bookkeeping request in an explicit sub-ledger mode.
   *
   * Newer backends accept ``mode`` on the common parse endpoint.  During a
   * rolling deployment an older backend still rejects that extra field, so a
   * read-only parse can safely retry the legacy body once.  Keeping this
   * compatibility boundary here lets the views use one clear mode contract.
   */
  parseMode: (mode, data = {}, requestOptions = {}) => {
    const body = { ...data, mode }
    const request = {
      method: 'POST',
      body,
      retry: 1,
      timeoutMs: 75_000,
      ...requestOptions,
    }
    return apiFetch('/api/ai/parse', request).catch((error) => {
      if (error instanceof ApiError && [400, 404, 405, 422].includes(error.status)) {
        return apiFetch('/api/ai/parse', { ...request, body: data })
      }
      throw error
    })
  },
  /**
   * Parse a bookkeeping request while the model's progress streams in.
   *
   * ``onEvent`` receives the provider/reasoning/content/status events and
   * the promise resolves with the same payload as ``parseMode``.  A backend
   * without the streaming route is asked through ``parseMode`` instead.
   */
  parseStream: (mode, data = {}, options = {}) => readAiStream('/api/ai/parse-stream', { ...data, mode }, options, (requestOptions) => aiApi.parseMode(mode, data, requestOptions)),
  /**
   * Ask the tool-using ledger assistant.  Progress (provider, tool calls) is
   * reported through ``onEvent``; the promise resolves with the answer.
   */
  askStream: (data = {}, options = {}) => readAiStream('/api/ai/ask', data, options, (requestOptions) => aiApi.chat(data, requestOptions)),
  conversations: (limit = 30) => apiFetch(`/api/ai/conversations?limit=${limit}`),
  conversation: (id) => apiFetch(`/api/ai/conversations/${id}`),
  deleteConversation: (id) => apiFetch(`/api/ai/conversations/${id}`, { method: 'DELETE' }),
  setProposalStatus: (conversationId, messageId, index, status, detail = null) => apiFetch(`/api/ai/conversations/${conversationId}/messages/${messageId}/proposals/${index}`, { method: 'POST', body: detail ? { status, detail } : { status } }),
  confirm: (data) => apiFetch('/api/ai/confirm', { method: 'POST', body: data }),
  /**
   * Confirm a proposal while preserving its cash/current-account mode.
   * Cash confirmation can fall back to the pre-mode endpoint.  Partner mode
   * deliberately does not fall back to a cash write; callers can then use the
   * explicit partner-ledger endpoint without accidentally creating a bogus
   * transaction.
   */
  confirmMode: (mode, data = {}) => {
    const body = { ...data, mode }
    return apiFetch('/api/ai/confirm', { method: 'POST', body }).catch((error) => {
      if (mode !== 'partner' && error instanceof ApiError && [400, 404, 405, 422].includes(error.status)) {
        // Older confirmation schemas know the original partner ledger fields
        // but not the mode/observed-balance reconciliation metadata.
        const legacy = { ...data }
        delete legacy.mode
        delete legacy.observed_balance_cents
        delete legacy.partner_balance_after_cents
        delete legacy.observed_balance_kind
        delete legacy.expected_balance_cents
        delete legacy.balance_delta_cents
        return apiFetch('/api/ai/confirm', { method: 'POST', body: legacy })
      }
      throw error
    })
  },
  /**
   * Confirm several cash/transfer drafts from one parse.  The backend writes
   * them in a single commit, so a rejected draft leaves the ledger untouched.
   */
  confirmBatch: (drafts) => apiFetch('/api/ai/confirm-batch', { method: 'POST', body: { confirm: true, drafts } }),
  history: (filters = {}) => apiFetch(`/api/ai/reports${queryString(filters)}`).then(listPayload).catch((error) => {
    // Keep compatibility with the initial API proposal while the reports
    // resource is rolled out.  Only a missing route is retried.
    if (error instanceof ApiError && [404, 405].includes(error.status)) return apiFetch(`/api/ai/history${queryString(filters)}`).then(listPayload)
    throw error
  }),
  report: (id) => apiFetch(`/api/ai/reports/${id}`),
  /** Aggregated income/expense figures for a period; never calls a model. */
  summary: (filters = { period: 'month' }) => apiFetch(`/api/ai/summary${queryString(filters)}`),
  /**
   * Conversational ledger question or report request.  A bookkeeping
   * sentence comes back as ``intent: "bookkeeping"`` so the caller continues
   * with the parse/confirm flow; the endpoint itself never writes anything.
   */
  chat: (data, requestOptions = {}) => apiFetch('/api/ai/chat', {
    method: 'POST',
    body: data,
    retry: 1,
    // Answers run at full reasoning depth, which can take a while.
    timeoutMs: 150_000,
    ...requestOptions,
  }),
  analyze: (data = {}, requestOptions = {}) => apiFetch('/api/ai/analyze', {
    method: 'POST',
    body: data,
    retry: 1,
    timeoutMs: 50_000,
    ...requestOptions,
  }),
  config: () => apiFetch('/api/ai/config'),
  saveConfig: (data) => apiFetch('/api/ai/config', { method: 'PUT', body: data }).catch((error) => {
    if (error instanceof ApiError && [404, 405].includes(error.status)) return apiFetch('/api/ai/config', { method: 'PATCH', body: data })
    throw error
  }),
  /** Swap the primary and fallback channels server-side; keys stay encrypted. */
  swapConfig: () => apiFetch('/api/ai/config/swap', { method: 'POST' }),
  clearConfig: () => apiFetch('/api/ai/config', { method: 'DELETE' }).catch((error) => {
    if (error instanceof ApiError && [404, 405].includes(error.status)) return apiFetch('/api/ai/config', { method: 'PATCH', body: { clear_api_key: true } })
    throw error
  }),
}

/**
 * Daily settlement snapshots.  A list call deliberately keeps the response
 * envelope (rather than returning only an array) because the API also
 * returns pagination metadata.  The view still accepts a bare array for
 * compatibility with the first single-user implementation.
 */
export const settlementsApi = {
  list: (filters = {}) => apiFetch(`/api/settlements${queryString(filters)}`).then((payload) => {
    if (Array.isArray(payload)) return { items: payload, total: payload.length }
    return { ...(payload || {}), items: listPayload(payload), total: payload?.total ?? listPayload(payload).length }
  }),
  get: (settlementDate) => apiFetch(`/api/settlements/${encodeURIComponent(settlementDate)}`),
  run: (data = {}) => apiFetch('/api/settlements/run', { method: 'POST', body: data }),
  recalculate: (data) => apiFetch('/api/settlements/recalculate', { method: 'POST', body: data }),
}

/** User-submitted feedback: append-only, scoped to the current user. */
export const feedbackApi = {
  list: (filters = {}) => apiFetch(`/api/feedback${queryString(filters)}`).then(listPayload),
  create: (data) => apiFetch('/api/feedback', { method: 'POST', body: data }),
}

/**
 * Read a server-sent event stream from an AI endpoint.  Events are passed to
 * ``onEvent`` until the final ``result``/``error`` event resolves or rejects
 * the promise; a backend without the route is asked through ``legacy``.
 */
async function readAiStream(path, body, { onEvent, timeoutMs = 200_000, ...requestOptions } = {}, legacy) {
    const requestSignal = createTimeoutSignal(requestOptions.signal, timeoutMs)
  const failure = (status, payload, cause) => {
    const info = classifyApiFailure(path, status, payload, cause, requestSignal.timedOut())
    return new ApiError(info.message || errorMessage(payload, `请求失败（${status}）`), status, payload, { kind: info.kind, retryable: info.retryable, path, cause })
  }
  try {
    let response
    try {
      response = await fetch(`${API_BASE_URL}${path}`, {
        method: 'POST',
        body: JSON.stringify(body),
        headers: { Accept: 'text/event-stream', 'Content-Type': 'application/json' },
        credentials: 'include',
        signal: requestSignal.signal,
      })
    } catch (cause) {
      throw failure(0, null, cause)
    }
    if ([404, 405].includes(response.status) || (response.ok && !response.body)) return await legacy(requestOptions)
    if (!response.ok) {
      if (response.status === 401 && typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('pennypilot:unauthorized'))
      throw failure(response.status, await response.json().catch(() => null), null)
    }
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    for (;;) {
      let chunk
      try {
        chunk = await reader.read()
      } catch (cause) {
        throw failure(0, null, cause)
      }
      if (chunk.done) break
      buffer += decoder.decode(chunk.value, { stream: true })
      let boundary
      while ((boundary = buffer.indexOf('\n\n')) >= 0) {
        const line = buffer.slice(0, boundary).split('\n').find((item) => item.startsWith('data:'))
        buffer = buffer.slice(boundary + 2)
        if (!line) continue
        let event
        try { event = JSON.parse(line.slice(5)) } catch { continue }
        if (event.type === 'result') return event.data
        if (event.type === 'error') throw failure(event.status || 503, { detail: event.detail }, null)
        try { onEvent?.(event) } catch { /* UI callbacks must not break the stream */ }
      }
    }
    // The stream closed without its final result/error event.
    throw failure(502, null, null)
  } finally {
    requestSignal.cleanup()
  }
}
