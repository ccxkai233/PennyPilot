<template>
  <AppLayout title="每日结算" subtitle="按自然日保存收支与往来账户快照" :notice="notice">
    <template #actions>
      <button class="outline-link" type="button" :disabled="!snapshots.length" @click="exportCsv">{{ isMobile ? '导出' : '导出 CSV' }}</button>
      <button v-if="!isMobile" class="secondary-link" type="button" @click="loadSnapshots">刷新</button>
    </template>

    <MobileSettlements v-if="isMobile" :calendar-month="calendarMonth" :month-label="monthLabel" :calendar-days="calendarDays" :today-iso="todayIso" :selected-date="selectedDate" :snapshots="snapshots" :snapshot-count="snapshotCount" :sorted-snapshots="sortedSnapshots" :selected-snapshot="selectedSnapshot" :accounts="accounts" :loading="loading" :detail-loading="detailLoading" :error-message="errorMessage" :detail-error="detailError" :run-loading="runLoading" :recalculate-open="recalculateOpen" :recalculate-loading="recalculateLoading" :recalculate-error="recalculateError" :recalc-date="recalcDate" :yesterday-iso="yesterdayIso" :month-change="changeMonth" :go-current-month="goCurrentMonth" :load-snapshots="loadSnapshots" :load-detail="loadDetail" :select-date="selectDate" :run-selected="runSelected" :open-recalculate="openRecalculate" :close-recalculate="closeRecalculate" :recalculate="recalculate" :set-recalc-date="setRecalcDate" :is-future="isFuture" :can-generate="canGenerate" :date-label="dateLabel" :short-date="shortDate" :weekday="weekday" :signed-money="signedMoney" />
    <template v-else>

    <section class="panel controls">
      <div class="control-copy"><h2>日结快照</h2><p>快照生成后不会覆盖原始流水；补录历史数据请使用“重算”。</p></div>
      <div class="control-row">
        <label>开始日期<input v-model="startDate" type="date" /></label>
        <label>结束日期<input v-model="endDate" type="date" /></label>
        <button class="primary" type="button" :disabled="loading" @click="loadSnapshots"><span v-if="loading" class="spinner"></span>{{ loading ? '加载中…' : '查询' }}</button>
        <button class="outline-button" type="button" :disabled="runLoading || !selectedDate || !canGenerate(selectedDate)" @click="runSelected"><span v-if="runLoading" class="spinner dark"></span>{{ runLoading ? '生成中…' : '生成选定日结' }}</button>
        <button class="outline-button" type="button" :disabled="recalculateLoading" @click="openRecalculate">重算历史日结</button>
      </div>
    </section>

    <div class="calendar-nav">
      <button class="month-button" type="button" aria-label="上个月" @click="changeMonth(-1)">‹</button>
      <strong>{{ monthLabel }}</strong>
      <button class="month-button" type="button" aria-label="下个月" @click="changeMonth(1)">›</button>
      <button class="today-button" type="button" @click="goCurrentMonth">本月</button>
    </div>

    <div class="content-grid">
      <section class="panel calendar-panel">
        <div class="panel-head"><div><h2>结算日历</h2><p>{{ snapshotCount ? `已生成 ${snapshotCount} 份快照${snapshots.some((item) => item.is_live) ? '，今日实时预览中' : ''}` : snapshots.some((item) => item.is_live) ? '今日实时预览中，日终后生成正式快照' : '点击日期查看或生成快照' }}</p></div></div>
        <div v-if="errorMessage" class="state error-state"><p>{{ errorMessage }}</p><button class="outline-button" type="button" @click="loadSnapshots">重试</button></div>
        <template v-else>
          <div class="weekday-row"><span v-for="day in weekdays" :key="day">{{ day }}</span></div>
          <div class="calendar-grid">
            <button v-for="cell in calendarDays" :key="cell.iso" class="calendar-cell" :class="{ outside: !cell.inMonth, selected: cell.iso === selectedDate, today: cell.iso === todayIso, settled: !!cell.snapshot && !cell.snapshot.is_live, live: cell.snapshot?.is_live }" type="button" @click="selectDate(cell.iso)">
              <span>{{ cell.day }}</span><i v-if="cell.snapshot" :aria-label="cell.snapshot.is_live ? '今日进行中' : '已结算'"></i>
              <em v-if="cell.snapshot" :class="cell.snapshot.net_cents >= 0 ? 'income-text' : 'expense-text'">{{ signedMoney(cell.snapshot.net_cents) }}</em>
            </button>
          </div>
          <div v-if="!loading && !snapshots.length" class="calendar-empty">当前范围还没有日结快照。</div>
        </template>
      </section>

      <section class="panel detail-panel">
        <div v-if="detailLoading" class="state"><span class="spinner dark"></span><p>正在加载详情…</p></div>
        <div v-else-if="detailError" class="state error-state"><p>{{ detailError }}</p><button class="outline-button" type="button" @click="loadDetail(selectedDate)">重试</button></div>
        <template v-else-if="selectedSnapshot">
          <div class="panel-head detail-head"><div><h2>{{ dateLabel(selectedSnapshot.settlement_date) }} {{ selectedSnapshot.is_live ? '实时收支' : '日结' }}</h2><p>{{ selectedSnapshot.is_live ? '今日数据会随流水变化，日终后自动生成正式快照' : `执行时间：${formatDateTime(selectedSnapshot.settled_at || selectedSnapshot.executed_at || selectedSnapshot.created_at)}` }}</p></div><span class="status-badge" :class="selectedSnapshot.is_live ? 'live' : selectedSnapshot.is_recalculated ? 'recalculated' : ''">{{ selectedSnapshot.is_live ? '实时预览' : selectedSnapshot.is_recalculated ? '已重算' : '已锁定' }}</span></div>
          <div class="metric-grid">
            <div class="metric"><span>当日收入</span><strong class="income-text">{{ formatMoney(selectedSnapshot.income_cents) }}</strong></div>
            <div class="metric"><span>当日支出</span><strong class="expense-text">{{ formatMoney(selectedSnapshot.expense_cents) }}</strong></div>
            <div class="metric"><span>净收支</span><strong :class="selectedSnapshot.net_cents >= 0 ? 'income-text' : 'expense-text'">{{ signedMoney(selectedSnapshot.net_cents) }}</strong></div>
            <div class="metric"><span>总资产口径</span><strong>{{ formatMoney(selectedSnapshot.total_assets_cents) }}</strong></div>
          </div>
          <div class="detail-body">
            <div class="section-title"><div><h3>往来账户快照</h3><p class="section-hint">当前未结算余额 · 当日结算金额</p></div><span>{{ accounts.length }} 个账户</span></div>
            <div v-if="!accounts.length" class="inline-empty">当日没有往来账户明细。</div>
            <div v-else class="account-table-wrap"><table class="account-table"><thead><tr><th>账户</th><th>当前未结算余额</th><th>当日结算金额</th></tr></thead><tbody><tr v-for="account in accounts" :key="account.key"><td data-label="账户"><span class="account-value account-name"><strong>{{ account.name }}</strong><small>{{ account.typeLabel }}</small></span></td><td data-label="当前未结算余额"><span class="account-value">{{ formatMoney(account.unsettled_cents) }}</span></td><td data-label="当日结算金额"><span class="account-value" :class="account.settlement_cents >= 0 ? 'income-text' : 'expense-text'">{{ signedMoney(account.settlement_cents) }}</span></td></tr></tbody></table></div>
          </div>
          <div v-if="selectedSnapshot.notes" class="snapshot-note">备注：{{ selectedSnapshot.notes }}</div>
        </template>
        <div v-else class="state"><div class="empty-icon">▣</div><h3>{{ selectedDate ? dateLabel(selectedDate) : '选择一个日期' }}</h3><p>{{ selectedDate ? (isFuture(selectedDate) ? '未来日期不能生成日结。' : selectedDate === todayIso ? '今日尚未结束，暂无正式日结。' : '该日期尚未生成快照，可点击上方按钮生成。') : '从左侧日历选择日期查看日结详情。' }}</p><button v-if="selectedDate && canGenerate(selectedDate)" class="primary" type="button" :disabled="runLoading" @click="runSelected">生成该日日结</button></div>
      </section>
    </div>

    <section class="panel list-panel">
      <div class="panel-head"><div><h2>快照列表</h2><p>按结算日期倒序排列，今日显示实时预览</p></div><span class="muted-count">{{ snapshotCount }} 份快照</span></div>
      <div v-if="loading" class="state compact"><span class="spinner dark"></span><p>正在加载…</p></div>
      <div v-else-if="!snapshots.length" class="state compact"><p>暂无日结记录。</p></div>
        <div v-else class="snapshot-list"><button v-for="snapshot in sortedSnapshots" :key="snapshot.id || snapshot.settlement_date" type="button" class="snapshot-row" :class="{ active: snapshot.settlement_date === selectedDate, live: snapshot.is_live }" @click="selectDate(snapshot.settlement_date)"><span class="snapshot-date"><strong>{{ shortDate(snapshot.settlement_date) }}</strong><small>{{ weekday(snapshot.settlement_date) }}</small></span><span><small>收入</small><b class="income-text">{{ formatMoney(snapshot.income_cents) }}</b></span><span><small>支出</small><b class="expense-text">{{ formatMoney(snapshot.expense_cents) }}</b></span><span><small>净收支</small><b :class="snapshot.net_cents >= 0 ? 'income-text' : 'expense-text'">{{ signedMoney(snapshot.net_cents) }}</b></span><span class="row-status">{{ snapshot.is_live ? '实时' : snapshot.is_recalculated ? '重算' : '已锁定' }}</span></button></div>
    </section>

    <div v-if="recalculateOpen" class="modal-backdrop" role="presentation" @click.self="closeRecalculate"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="recalculate-title"><div class="modal-head"><div><h2 id="recalculate-title">重算历史日结</h2><p>从选定日期开始，重新生成该日及之后的快照。</p></div><button class="modal-close" type="button" aria-label="关闭" @click="closeRecalculate">×</button></div><label class="modal-label">起始日期<input v-model="recalcDate" type="date" :max="yesterdayIso" /></label><p class="warning">重算会更新快照内容并保留重算标记，不会删除或修改原始收支流水。</p><p v-if="recalculateError" class="form-error">{{ recalculateError }}</p><div class="modal-actions"><button class="outline-button" type="button" :disabled="recalculateLoading" @click="closeRecalculate">取消</button><button class="primary" type="button" :disabled="recalculateLoading || !recalcDate" @click="recalculate"><span v-if="recalculateLoading" class="spinner"></span>{{ recalculateLoading ? '重算中…' : '确认重算' }}</button></div></section></div>
    </template>
  </AppLayout>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import AppLayout from '../components/AppLayout.vue'
import { useViewport } from '../composables/useViewport'
import MobileSettlements from './MobileSettlements.vue'
import { APP_TIME_ZONE, ApiError, beijingDateIso, formatDateTime, formatMoney, settlementsApi } from '../api'

const pad = (value) => String(value).padStart(2, '0')
// Settlement dates are Beijing calendar keys.  Date.UTC is used only as a
// timezone-neutral arithmetic representation for a YYYY-MM-DD key; all
// current-day decisions and labels are derived from the explicit Beijing
// timezone rather than the browser/host timezone.
const toIso = (date) => `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`
const parseDate = (value) => {
  const match = String(value || '').slice(0, 10).match(/^(\d{4})-(\d{2})-(\d{2})$/)
  return match ? new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]))) : null
}
const monthBounds = (date) => ({ start: toIso(new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), 1))), end: toIso(new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 0))) })
const today = new Date()
const todayIso = beijingDateIso(today)
const todayCalendarDate = parseDate(todayIso)
const yesterdayIso = todayCalendarDate ? toIso(new Date(todayCalendarDate.getTime() - 86400000)) : ''
const initialBounds = monthBounds(todayCalendarDate)
const startDate = ref(initialBounds.start)
const endDate = ref(initialBounds.end)
const calendarMonth = ref(todayIso.slice(0, 7))
const selectedDate = ref('')
const snapshots = ref([])
const selectedSnapshot = ref(null)
const loading = ref(false)
const detailLoading = ref(false)
const errorMessage = ref('')
const detailError = ref('')
const runLoading = ref(false)
const recalculateOpen = ref(false)
const recalculateLoading = ref(false)
const recalculateError = ref('')
const recalcDate = ref(initialBounds.start)
const notice = ref(null)
const weekdays = ['日', '一', '二', '三', '四', '五', '六']
const { isMobile } = useViewport()

const sortedSnapshots = computed(() => snapshots.value.slice().sort((a, b) => String(b.settlement_date).localeCompare(String(a.settlement_date))))
const snapshotCount = computed(() => snapshots.value.filter((item) => !item.is_live).length)
const snapshotMap = computed(() => Object.fromEntries(snapshots.value.map((item) => [item.settlement_date, item])))
const monthLabel = computed(() => {
  const [year, month] = calendarMonth.value.split('-').map(Number)
  return `${year} 年 ${month} 月`
})
const calendarDays = computed(() => {
  const [year, month] = calendarMonth.value.split('-').map(Number)
  const first = new Date(Date.UTC(year, month - 1, 1))
  const last = new Date(Date.UTC(year, month, 0))
  const firstWeekday = first.getUTCDay()
  const count = Math.ceil((firstWeekday + last.getUTCDate()) / 7) * 7
  return Array.from({ length: count }, (_, index) => {
    const date = new Date(Date.UTC(year, month - 1, index - firstWeekday + 1))
    const iso = toIso(date)
    return { iso, day: date.getUTCDate(), inMonth: date.getUTCMonth() === month - 1, snapshot: snapshotMap.value[iso] }
  })
})
const accounts = computed(() => normalizeAccounts(selectedSnapshot.value))

function numeric(value) {
  if (value === null || value === undefined || value === '') return undefined
  const result = Number(value)
  return Number.isFinite(result) ? result : undefined
}
function firstNumber(object, keys, fallback = 0) {
  for (const key of keys) { const value = numeric(object?.[key]); if (value !== undefined) return value }
  return fallback
}
function toArray(value) {
  if (Array.isArray(value)) return value
  if (value && typeof value === 'object') {
    if (Array.isArray(value.items)) return value.items
    if (Array.isArray(value.results)) return value.results
    return Object.entries(value).map(([id, item]) => item && typeof item === 'object' ? { id, ...item } : { id, value: item })
  }
  return []
}
function normalizeSnapshot(raw = {}) {
  const date = String(raw.settlement_date || raw.settlementDate || raw.date || raw.day || '').slice(0, 10)
  return {
    ...raw,
    settlement_date: date,
    income_cents: firstNumber(raw, ['income_cents', 'income_amount_cents', 'income']),
    expense_cents: firstNumber(raw, ['expense_cents', 'expense_amount_cents', 'expense']),
    net_cents: firstNumber(raw, ['net_cents', 'net_amount_cents', 'net'], firstNumber(raw, ['income_cents', 'income']) - firstNumber(raw, ['expense_cents', 'expense'])),
    total_assets_cents: firstNumber(raw, ['total_assets_cents', 'total_asset_cents', 'total_assets', 'asset_total_cents']),
    account_balances: raw.account_balances || raw.accounts || raw.partner_balances || [],
    account_changes: raw.account_changes || raw.partner_changes || [],
  }
}
function normalizeAccounts(snapshot) {
  if (!snapshot) return []
  const balances = toArray(snapshot.account_balances)
  const changes = toArray(snapshot.account_changes)
  const changeMap = new Map()
  changes.forEach((change) => changeMap.set(String(change.partner_id ?? change.id ?? change.partnerId ?? change.name ?? ''), change))
  const rows = []
  const seen = new Set()
  balances.forEach((item) => {
    const key = String(item.partner_id ?? item.id ?? item.partnerId ?? item.name ?? rows.length)
    const change = changeMap.get(key) || changeMap.get(String(item.name || item.partner_name || '')) || {}
    rows.push(accountRow(item, change, key)); seen.add(key)
  })
  changes.forEach((item, index) => {
    const key = String(item.partner_id ?? item.id ?? item.partnerId ?? item.name ?? `change-${index}`)
    if (!seen.has(key)) rows.push(accountRow(item, item, key))
  })
  return rows.sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
}
function accountRow(item, change, key) {
  const limit = firstNumber(item, ['credit_limit_cents', 'credit_total_cents', 'limit_cents'], firstNumber(change, ['credit_limit_cents', 'credit_total_cents', 'limit_cents']))
  const used = firstNumber(item, ['credit_used_cents', 'used_credit_cents', 'credit_consumed_cents'], firstNumber(change, ['credit_used_cents', 'used_credit_cents', 'credit_consumed_cents']))
  const remaining = firstNumber(item, ['credit_remaining_cents', 'remaining_credit_cents', 'credit_available_cents'], limit - used)
  const partnerType = String(item.partner_type || item.type || change.partner_type || change.type || '').toLowerCase()
  const prepaid = firstNumber(item, ['prepaid_balance_cents', 'prepaid_cents', 'balance_cents'])
  const prepaidDelta = firstNumber(change, ['prepaid_delta_cents', 'prepaid_change_cents', 'prepaid_net_cents'])
  const creditDelta = firstNumber(change, ['credit_delta_cents', 'credit_used_delta_cents', 'credit_change_cents'])
  const unsettled = firstNumber(item, ['unsettled_balance_cents', 'unsettled_cents'], partnerType === 'customer' ? used : prepaid)
  const settlement = firstNumber(change, ['settlement_amount_cents', 'cash_settlement_cents', 'settled_amount_cents'], firstNumber(change, ['unsettled_delta_cents', 'unsettled_change_cents'], partnerType === 'customer' ? creditDelta : prepaidDelta))
  return { key, name: item.partner_name || item.name || change.partner_name || change.name || '未命名账户', typeLabel: ({ supplier: '供应商', customer: '客户' }[partnerType] || '往来单位'), unsettled_cents: unsettled, settlement_cents: settlement, delta_cents: settlement }
}
function dateLabel(value) {
  const date = parseDate(value)
  // Shift the neutral calendar representation to an instant that is safely
  // inside the same Beijing day, then format with the explicit app timezone.
  return date ? new Intl.DateTimeFormat('zh-CN', { timeZone: APP_TIME_ZONE, year: 'numeric', month: 'long', day: 'numeric' }).format(new Date(date.getTime() + 8 * 60 * 60 * 1000)) : '未知日期'
}
function shortDate(value) { const date = parseDate(value); return date ? `${date.getUTCMonth() + 1}月${date.getUTCDate()}日` : value }
function weekday(value) { const date = parseDate(value); return date ? `星期${weekdays[date.getUTCDay()]}` : '' }
function signedMoney(value) { const cents = numeric(value) || 0; return `${cents >= 0 ? '+' : '−'}${formatMoney(Math.abs(cents), '').trim()}` }
function isFuture(value) { return String(value || '') > todayIso }
function canGenerate(value) { return Boolean(value) && String(value) < todayIso }

async function loadSnapshots() {
  if (!startDate.value || !endDate.value || startDate.value > endDate.value) { errorMessage.value = '请选择有效的日期范围。'; return }
  loading.value = true; errorMessage.value = ''; detailError.value = ''; notice.value = null
  try {
    const result = await settlementsApi.list({ start_date: startDate.value, end_date: endDate.value, page: 1, page_size: 100 })
    snapshots.value = (result.items || []).map(normalizeSnapshot).filter((item) => item.settlement_date)
    if (!selectedDate.value || !snapshotMap.value[selectedDate.value]) selectedDate.value = sortedSnapshots.value[0]?.settlement_date || ''
    if (selectedDate.value) await loadDetail(selectedDate.value, false)
    else { selectedSnapshot.value = null; detailError.value = '' }
  } catch (error) { errorMessage.value = error instanceof ApiError ? error.message : '日结快照加载失败。' }
  finally { loading.value = false }
}
async function loadDetail(date, showLoading = true) {
  if (!date) { selectedSnapshot.value = null; return }
  if (showLoading) detailLoading.value = true
  detailError.value = ''
  try { selectedSnapshot.value = normalizeSnapshot(await settlementsApi.get(date)) }
  catch (error) {
    // A list item is still useful when a compatible server has no detail route.
    const fallback = snapshotMap.value[date]
    if (fallback && error instanceof ApiError && [404, 405].includes(error.status)) selectedSnapshot.value = fallback
    else {
      // A missing snapshot is an expected state for an arbitrary calendar
      // date, not a transport failure.  Leave the detail pane in its empty
      // state so the user can generate that date directly.
      selectedSnapshot.value = null
      detailError.value = error instanceof ApiError && error.status === 404 ? '' : (error instanceof ApiError ? error.message : '日结详情加载失败。')
    }
  }
  finally { if (showLoading) detailLoading.value = false }
}
function selectDate(date) { selectedDate.value = date; loadDetail(date) }
function changeMonth(offset) {
  const [year, month] = calendarMonth.value.split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 1 + offset, 1))
  calendarMonth.value = `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}`
  const bounds = monthBounds(date); startDate.value = bounds.start; endDate.value = bounds.end; selectedDate.value = ''; selectedSnapshot.value = null; loadSnapshots()
}
function goCurrentMonth() { const bounds = monthBounds(todayCalendarDate); calendarMonth.value = todayIso.slice(0, 7); startDate.value = bounds.start; endDate.value = bounds.end; loadSnapshots() }
async function runSelected() {
  const date = selectedDate.value || yesterdayIso
  if (!canGenerate(date)) { notice.value = { type: 'error', message: date === todayIso ? '今日尚未结束，请先查看实时收支；正式日结将在明日生成。' : '未来日期不能生成日结。' }; return }
  runLoading.value = true; notice.value = null
  try { const result = await settlementsApi.run({ settlement_date: date }); const fresh = normalizeSnapshot(result); snapshots.value = [...snapshots.value.filter((item) => item.settlement_date !== fresh.settlement_date), fresh]; selectedDate.value = date; selectedSnapshot.value = fresh; notice.value = { type: 'success', message: `${dateLabel(date)}日结已生成。` } }
  catch (error) { notice.value = { type: 'error', message: error instanceof ApiError ? error.message : '日结生成失败。' } }
  finally { runLoading.value = false }
}
function openRecalculate() { recalcDate.value = startDate.value || yesterdayIso; recalculateError.value = ''; recalculateOpen.value = true }
function setRecalcDate(value) { recalcDate.value = value }
function closeRecalculate() { if (!recalculateLoading.value) recalculateOpen.value = false }
async function recalculate() {
  if (!recalcDate.value || !canGenerate(recalcDate.value)) { recalculateError.value = '请选择不晚于昨天的日期。'; return }
  recalculateLoading.value = true; recalculateError.value = ''; notice.value = null
  try { const result = await settlementsApi.recalculate({ from_date: recalcDate.value }); const returned = (result?.items || (Array.isArray(result) ? result : [])).map(normalizeSnapshot); if (returned.length) snapshots.value = [...snapshots.value.filter((item) => !returned.some((next) => next.settlement_date === item.settlement_date)), ...returned]; recalculateOpen.value = false; notice.value = { type: 'success', message: `已从 ${recalcDate.value} 起重算 ${result?.recalculated_count ?? returned.length} 份日结。` }; await loadSnapshots() }
  catch (error) { recalculateError.value = error instanceof ApiError ? error.message : '历史日结重算失败。' }
  finally { recalculateLoading.value = false }
}
function exportCsv() {
  if (!snapshots.value.length) return
  const rows = [['结算日期', '收入（元）', '支出（元）', '净收支（元）', '总资产（元）', '往来账户数', '状态']]
  sortedSnapshots.value.forEach((item) => rows.push([item.settlement_date, (item.income_cents / 100).toFixed(2), (item.expense_cents / 100).toFixed(2), (item.net_cents / 100).toFixed(2), (item.total_assets_cents / 100).toFixed(2), normalizeAccounts(item).length, item.is_live ? '实时预览' : item.is_recalculated ? '重算' : '已锁定']))
  const csv = '\ufeff' + rows.map((row) => row.map((cell) => `"${String(cell ?? '').replaceAll('"', '""')}"`).join(',')).join('\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' }); const url = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = `pennypilot-settlements-${startDate.value}-${endDate.value}.csv`; anchor.click(); URL.revokeObjectURL(url)
}

onMounted(loadSnapshots)
</script>

<style scoped>
.calendar-cell.live i{background:#2563eb}.status-badge.live{color:#2563eb;background:#edf4ff}.snapshot-row.live{background:#f7fbff}.snapshot-row.live .row-status{color:#2563eb}.section-hint{margin:4px 0 0;color:#9aa6b5;font-size:10px}.account-table{min-width:430px}
.panel{background:#fff;border-radius:13px;box-shadow:0 2px 8px #243b5a0d}.controls{margin-top:28px;padding:20px 24px;display:flex;align-items:flex-end;justify-content:space-between;gap:20px}.control-copy h2,.panel-head h2{margin:0;color:#34435b;font-size:17px}.control-copy p,.panel-head p{margin:6px 0 0;color:#8a97aa;font-size:12px}.control-row{display:flex;align-items:flex-end;gap:9px;flex-wrap:wrap}.control-row label{color:#7b8aa0;font-size:11px}.control-row input{display:block;margin-top:5px;height:37px;border:1px solid #dbe2ee;border-radius:8px;padding:0 9px;color:#44536a;background:#fff;font:inherit;font-size:12px}.primary,.outline-button,.outline-link,.secondary-link{font-size:12px;white-space:nowrap;cursor:pointer;text-decoration:none}.primary{border:0;border-radius:8px;background:#2563eb;color:#fff;padding:10px 15px;font-weight:600}.primary:hover{background:#1d4ed8}.primary:disabled,.outline-button:disabled,.outline-link:disabled{opacity:.6;cursor:wait}.outline-button{border:1px solid #d6dfec;border-radius:8px;background:#fff;color:#52617a;padding:9px 13px}.outline-button:hover,.outline-link:hover{border-color:#3b82f6;color:#2563eb}.outline-link{border:1px solid #d6dfec;border-radius:8px;background:#fff;color:#2563eb;padding:8px 11px}.secondary-link{border:0;background:transparent;color:#2563eb;font-weight:600;padding:9px 2px}.calendar-nav{display:flex;align-items:center;justify-content:center;gap:14px;margin:20px 0 12px;color:#34435b}.calendar-nav strong{min-width:112px;text-align:center;font-size:17px}.month-button,.today-button{border:1px solid #dbe2ee;border-radius:7px;background:#fff;color:#52617a;cursor:pointer}.month-button{width:31px;height:31px;font-size:22px;line-height:20px}.today-button{padding:6px 10px;font-size:11px}.content-grid{display:grid;grid-template-columns:minmax(350px,.9fr) minmax(480px,1.35fr);gap:18px}.calendar-panel,.detail-panel,.list-panel{overflow:hidden}.panel-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;padding:20px 23px;border-bottom:1px solid #edf0f5}.weekday-row,.calendar-grid{display:grid;grid-template-columns:repeat(7,1fr);padding:0 18px}.weekday-row{padding-top:14px;padding-bottom:6px}.weekday-row span{text-align:center;color:#a0aaba;font-size:10px}.calendar-cell{position:relative;min-height:62px;border:0;border-radius:9px;background:transparent;color:#52617a;cursor:pointer;margin:2px;padding:7px 4px;text-align:center}.calendar-cell:hover{background:#f1f6ff}.calendar-cell.outside{color:#c5ccd6}.calendar-cell.selected{background:#e8f1ff;box-shadow:inset 0 0 0 1px #7daaf1}.calendar-cell.today>span{display:inline-grid;place-items:center;width:23px;height:23px;border-radius:50%;background:#2563eb;color:#fff}.calendar-cell i{display:block;width:5px;height:5px;border-radius:50%;background:#23a374;margin:3px auto 0}.calendar-cell em{display:block;font-size:9px;font-style:normal;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px}.calendar-empty{color:#9aa6b5;text-align:center;font-size:12px;padding:13px 18px 20px}.detail-panel{min-height:385px}.detail-head{align-items:center}.status-badge{border-radius:99px;color:#17825d;background:#e8f8f0;font-size:10px;padding:5px 8px}.status-badge.recalculated{color:#8058a8;background:#f2eafd}.metric-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;padding:18px 23px}.metric{border:1px solid #e8eef7;border-radius:9px;padding:12px 11px;min-width:0}.metric span{display:block;color:#8c99ab;font-size:10px}.metric strong{display:block;color:#34435b;font-size:16px;margin-top:7px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.income-text{color:#128a63!important}.expense-text{color:#d25b62!important}.detail-body{padding:0 23px 20px}.section-title{display:flex;align-items:center;justify-content:space-between;margin:2px 0 10px}.section-title h3{margin:0;color:#52617a;font-size:14px}.section-title span,.muted-count{color:#98a4b4;font-size:11px}.account-table-wrap{border:1px solid #edf0f5;border-radius:9px;overflow:auto}.account-table{width:100%;min-width:530px;border-collapse:collapse}.account-table th{background:#fafbfd;color:#8996a9;font-size:10px;font-weight:600;text-align:left;padding:10px 11px;white-space:nowrap}.account-table td{border-top:1px solid #edf0f5;color:#59677d;font-size:11px;padding:10px 11px;white-space:nowrap}.account-table td:first-child{white-space:normal;min-width:135px}.account-table strong,.account-table small{display:block}.account-table small{color:#99a5b4;font-size:10px;margin-top:3px}.muted{color:#9aa6b5}.inline-empty{border:1px dashed #dce5f0;border-radius:9px;color:#9aa6b5;text-align:center;padding:24px;font-size:12px}.snapshot-note{border-top:1px solid #edf0f5;margin:0 23px;padding:13px 0 18px;color:#7c899c;font-size:11px}.state{min-height:260px;display:grid;place-content:center;justify-items:center;text-align:center;color:#8b98aa;padding:25px}.state h3{color:#52617a;margin:11px 0 6px;font-size:16px}.state p{font-size:12px;margin:0 0 15px}.error-state p{color:#b64952}.empty-icon{font-size:32px;color:#a7b8d0}.spinner{width:14px;height:14px;border:2px solid #ffffff66;border-top-color:#fff;border-radius:50%;animation:spin .7s linear infinite;display:inline-block;vertical-align:-3px;margin-right:5px}.spinner.dark{border-color:#dce7f8;border-top-color:#2563eb;margin-bottom:4px}@keyframes spin{to{transform:rotate(360deg)}}.list-panel{margin-top:18px;margin-bottom:26px}.snapshot-list{padding:0 23px}.snapshot-row{display:grid;grid-template-columns:1.2fr repeat(3,1fr) 55px;align-items:center;gap:11px;width:100%;border:0;border-bottom:1px solid #edf0f5;background:#fff;text-align:left;padding:13px 2px;cursor:pointer;color:#52617a}.snapshot-row:hover,.snapshot-row.active{background:#f7faff}.snapshot-row small{display:block;color:#9aa6b5;font-size:10px;margin-bottom:4px}.snapshot-row b{font-size:12px}.snapshot-date strong{display:block;color:#34435b;font-size:13px}.snapshot-date small{margin-top:3px}.row-status{color:#8b98aa;font-size:10px;text-align:right}.modal-backdrop{position:fixed;inset:0;z-index:100;display:grid;place-items:center;padding:18px;background:#10213c66}.modal{width:min(500px,100%);background:#fff;border-radius:15px;padding:24px;box-shadow:0 24px 80px #0c1c3560}.modal-head{display:flex;justify-content:space-between;gap:10px}.modal-head h2{margin:0;color:#1e2a3d;font-size:20px}.modal-head p{margin:6px 0 0;color:#8996a9;font-size:12px}.modal-close{border:0;background:transparent;color:#8b98aa;font-size:25px;cursor:pointer}.modal-label{display:block;margin-top:22px;color:#59677d;font-size:13px}.modal-label input{display:block;width:100%;height:39px;margin-top:7px;border:1px solid #dbe2ee;border-radius:8px;padding:0 10px;font:inherit;color:#44536a}.warning{margin:14px 0 0;padding:11px;border-radius:8px;background:#fff8e8;color:#936b1b;font-size:12px;line-height:1.6}.form-error{margin-top:13px;padding:10px;border-radius:8px;background:#fff0f0;color:#a83232;font-size:12px}.modal-actions{display:flex;justify-content:flex-end;gap:9px;margin-top:22px}@media(max-width:980px){.controls{display:block}.control-row{margin-top:15px}.content-grid{grid-template-columns:1fr}.detail-panel{min-height:0}}@media(max-width:600px){.controls{margin-top:20px;padding:17px 16px}.control-row label{flex:1 1 calc(50% - 5px)}.control-row .primary,.control-row .outline-button{flex:1 1 100%}.panel-head,.detail-body{padding-left:16px;padding-right:16px}.metric-grid{grid-template-columns:repeat(2,1fr);padding:15px 16px}.weekday-row,.calendar-grid{padding-left:10px;padding-right:10px}.calendar-cell{min-height:53px}.calendar-cell em{font-size:8px}.snapshot-list{padding:0 16px}.snapshot-row{grid-template-columns:1.1fr repeat(3,1fr);gap:5px}.row-status{display:none}.header-actions{gap:5px}.outline-link{font-size:11px;padding:7px 8px}}
/* Mobile interaction layer: keep the desktop grid intact while making
   dates, account rows, and actions comfortable on narrow touch screens. */
@media(max-width:600px){
  .controls{margin-top:20px;padding:17px 16px;overflow:hidden}
  .control-copy h2{font-size:16px}.control-copy p{line-height:1.55}
  .control-row{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px;margin-top:15px}
  .control-row label{display:block;min-width:0;flex:none}.control-row input{width:100%;min-width:0;min-height:44px;height:44px;font-size:16px}
  .control-row .primary,.control-row .outline-button{grid-column:1/-1;min-height:44px;padding:10px 12px}
  .panel-head,.detail-body{padding-left:16px;padding-right:16px}.panel-head{gap:8px}
  .metric-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;padding:15px 16px}.metric{min-height:70px;padding:11px 10px}.metric strong{font-size:15px}
  .calendar-nav{gap:10px;margin:16px 0 11px}.calendar-nav strong{min-width:100px;font-size:16px}.month-button{width:44px;height:44px;font-size:25px}.today-button{min-height:44px;padding:8px 11px}
  .weekday-row,.calendar-grid{padding-left:7px;padding-right:7px}.weekday-row{padding-top:11px}.calendar-cell{min-height:52px;margin:1px;padding:6px 2px;border-radius:8px}.calendar-cell>span{font-size:12px}.calendar-cell em{font-size:8px;line-height:1.2}.calendar-cell i{margin-top:2px}
  .account-table-wrap{border:0;overflow:visible}.account-table,.account-table thead,.account-table tbody,.account-table tr,.account-table th,.account-table td{display:block}.account-table{min-width:0}.account-table thead{display:none}.account-table tbody{display:grid;gap:8px}.account-table tr{border:1px solid #e7edf5;border-radius:10px;padding:7px 11px;background:#fff}.account-table td{display:flex;align-items:baseline;justify-content:space-between;gap:12px;min-height:44px;padding:7px 0;border:0;border-top:1px solid #edf0f5;text-align:right;white-space:normal;overflow-wrap:anywhere}.account-table td:first-child{min-width:0;border-top:0}.account-table td::before{content:attr(data-label);flex:0 0 auto;color:#96a2b2;font-size:10px;text-align:left}.account-table td>strong,.account-table td>small{max-width:65%;overflow-wrap:anywhere}.account-table td>strong{font-size:12px}.account-table td>small{font-size:10px}.account-table td:nth-child(3) .muted{white-space:normal}
  .snapshot-list{padding:0 16px 8px}.snapshot-row{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin:8px 0;padding:10px;border:1px solid #e7edf5;border-radius:10px}.snapshot-row:hover,.snapshot-row.active{background:#f7faff}.snapshot-row .snapshot-date{grid-column:1/-1;display:flex;align-items:baseline;justify-content:space-between;gap:8px;padding-bottom:2px}.snapshot-row>span:not(.snapshot-date):not(.row-status){min-width:0;padding:7px 8px;border-radius:7px;background:#f8faff}.snapshot-row small{font-size:10px}.snapshot-row b{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px}.snapshot-date strong{font-size:13px}.snapshot-date small{margin:0}.row-status{display:none}
  .snapshot-note{margin:0 16px}.modal-backdrop{align-items:end;padding:8px 8px max(8px,env(safe-area-inset-bottom))}.modal{width:100%;max-height:calc(100dvh - 16px);border-radius:16px 16px 10px 10px;padding:21px 17px;overflow:auto}.modal-head{gap:8px}.modal-head h2{font-size:18px}.modal-label input{min-height:44px;height:44px;font-size:16px}.modal-close{min-width:44px;min-height:44px;padding:8px}.modal-actions{gap:8px}.modal-actions>*{min-height:44px;flex:1}.modal-actions .primary{min-width:0}.outline-link,.secondary-link{min-height:44px;display:inline-flex;align-items:center;justify-content:center}.primary,.outline-button{min-height:44px}
  :deep(.header-actions){gap:5px;max-width:52vw;flex-wrap:wrap;justify-content:flex-end}.outline-link{font-size:11px;padding:7px 8px}
}
@media(max-width:380px){.controls{padding-left:12px;padding-right:12px}.calendar-cell em{display:none}.metric strong{font-size:13px}.snapshot-row>span:not(.snapshot-date):not(.row-status){padding-left:6px;padding-right:6px}.detail-body,.panel-head,.metric-grid{padding-left:12px;padding-right:12px}}
</style>
