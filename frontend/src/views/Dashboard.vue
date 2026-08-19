<template>
  <AppLayout title="概览" :subtitle="todayLabel" :notice="notice">
    <template v-if="!isMobile" #actions><router-link class="primary quick-link" to="/ai">＋ 记一笔</router-link></template>
    <MobileDashboard v-if="isMobile" :summary="summary" :today-summary="todaySummary" :recent="recent" :loading="loading" :error-message="errorMessage" :account-balances="accountBalances" :account-balance-groups="accountBalanceGroups" :category-name="categoryName" :payment-method-name="paymentMethodName" :transaction-note="transactionNote" :transaction-full-note="transactionFullNote" :cents="cents" :is-voided="isVoided" @retry="load" />
    <template v-else>
    <div class="summary-groups">
      <div class="cards">
        <div class="card"><span>本月收入</span><strong class="income-text">{{ formatMoney(summary.income) }}</strong><em class="up">{{ summary.incomeCount }} 笔收入</em></div>
        <div class="card"><span>本月支出</span><strong class="expense-text">{{ formatMoney(summary.expense) }}</strong><em class="down">{{ summary.expenseCount }} 笔支出</em></div>
        <div class="card"><span>本月净收支</span><strong :class="summary.net >= 0 ? 'income-text' : 'expense-text'">{{ summary.net >= 0 ? '+' : '' }}{{ formatMoney(summary.net) }}</strong><em>收入 − 支出</em></div>
      </div>
      <div class="cards today-cards">
        <div class="card"><span>本日收入</span><strong class="income-text">{{ formatMoney(todaySummary.income) }}</strong><em class="up">{{ todaySummary.incomeCount }} 笔收入</em></div>
        <div class="card"><span>本日支出</span><strong class="expense-text">{{ formatMoney(todaySummary.expense) }}</strong><em class="down">{{ todaySummary.expenseCount }} 笔支出</em></div>
        <div class="card"><span>本日净收支</span><strong :class="todaySummary.net >= 0 ? 'income-text' : 'expense-text'">{{ todaySummary.net >= 0 ? '+' : '' }}{{ formatMoney(todaySummary.net) }}</strong><em>北京时间今日 00:00 至当前</em></div>
      </div>
    </div>
    <section class="panel recent-panel">
      <div class="panel-head"><div><h2>近期交易</h2><p>本月最新记录</p></div><router-link to="/transactions">查看全部 →</router-link></div>
      <div v-if="loading" class="state"><span class="spinner"></span><p>正在加载…</p></div>
      <div v-else-if="errorMessage" class="state error-state"><p>{{ errorMessage }}</p><button class="outline-button" type="button" @click="load">重试</button></div>
      <div v-else-if="recent.length === 0" class="empty"><div>📒</div><h3>暂无交易记录</h3><p>开始记录您的第一笔收支吧</p><router-link class="primary small" to="/ai">＋ 记一笔</router-link></div>
      <div v-else class="recent-list">
        <div v-for="transaction in recent" :key="transaction.id" class="recent-row" :class="{ voided: isVoided(transaction) }">
          <div class="recent-icon" :class="transaction.direction === 'income' ? 'income-bg' : 'expense-bg'">{{ transaction.direction === 'income' ? '↓' : '↑' }}</div>
          <div class="recent-info"><strong>{{ categoryName(transaction) }}</strong><span>{{ formatDateTime(transaction.occurred_at || transaction.occurred_time) }} · {{ paymentMethodName(transaction) }}</span><small v-if="transactionNote(transaction)" class="recent-note" :title="transactionFullNote(transaction)">备注：{{ transactionNote(transaction) }}</small></div>
          <div class="recent-amount" :class="transaction.direction === 'income' ? 'income-text' : 'expense-text'">{{ transaction.direction === 'income' ? '+' : '−' }}{{ formatMoney(cents(transaction), '') }}</div>
          <span v-if="isVoided(transaction)" class="voided-label">已作废</span>
        </div>
      </div>
    </section>
    <section class="panel balance-panel" aria-labelledby="balance-panel-title">
      <div class="panel-head"><div><h2 id="balance-panel-title">资金账户余额</h2><p>现金、投资、负债账户的当前余额</p></div><router-link to="/settings">管理账户 →</router-link></div>
      <div v-if="loading && !accountBalances.length" class="state balance-state"><span class="spinner"></span><p>正在加载账户余额…</p></div>
      <div v-else-if="!accountBalances.length" class="empty balance-empty"><div>◌</div><h3>还没有资金账户</h3><p>在设置中添加现金、信用卡或投资账户。</p><router-link class="primary small" to="/settings">去设置</router-link></div>
      <div v-else class="balance-table-wrap">
        <table class="balance-table"><thead><tr><th>账户</th><th>账户性质</th><th>当前余额</th></tr></thead>
          <tbody v-for="group in accountBalanceGroups" :key="group.role">
            <tr class="account-group-row" :class="`group-${group.role}`"><td colspan="2"><span class="account-group-title"><span>{{ group.icon }}</span><strong>{{ group.label }}</strong><small>{{ group.items.length }} 个</small></span></td><td><strong class="account-group-total" :class="groupBalanceClass(group)">{{ groupBalanceLabel(group) }}</strong></td></tr>
            <tr v-for="account in group.items" :key="account.id"><td data-label="账户"><span class="account-name"><span class="account-icon">{{ account.icon || accountRoleIcon(account.account_role) }}</span><strong>{{ account.name }}</strong></span></td><td data-label="账户性质"><span class="role-badge" :class="`role-${account.account_role}`">{{ accountRoleLabel(account.account_role) }}</span></td><td data-label="当前余额"><strong class="balance-value" :class="accountBalanceClass(account)">{{ accountBalanceLabel(account) }}</strong></td></tr>
          </tbody>
        </table>
      </div>
    </section>
    </template>
  </AppLayout>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import AppLayout from '../components/AppLayout.vue'
import { useViewport } from '../composables/useViewport'
import MobileDashboard from './MobileDashboard.vue'
import { groupAccounts } from '../accountRoles'
import { ApiError, beijingDateIso, categoriesApi, formatDateTime, formatMoney, paymentMethodsApi, timestampValue, transactionsApi, APP_TIME_ZONE } from '../api'

const loading = ref(false)
const errorMessage = ref('')
const monthTransactions = ref([])
const categories = ref([])
const paymentMethods = ref([])
const notice = ref(null)
const summaryAsOf = ref(Date.now())
const pad = (value) => String(value).padStart(2, '0')
const now = new Date()
const todayIso = beijingDateIso(now)
const [todayYear, todayMonth] = todayIso.split('-').map(Number)
const monthStart = `${todayYear}-${pad(todayMonth)}-01`
const monthEnd = todayIso
const todayLabel = new Intl.DateTimeFormat('zh-CN', { timeZone: APP_TIME_ZONE, weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' }).format(now)

const { isMobile } = useViewport()

const cashflowTransactions = computed(() => monthTransactions.value.filter((item) => !isTransfer(item)))
const recent = computed(() => cashflowTransactions.value.slice().sort((a, b) => (timestampValue(b.occurred_at || b.occurred_time) || 0) - (timestampValue(a.occurred_at || a.occurred_time) || 0)).slice(0, 6))
const accountBalances = computed(() => paymentMethods.value.filter((item) => item.is_active !== false).map((item) => {
  const rawBalance = item.effective_balance_cents ?? item.current_balance_cents
  return { ...item, balance_cents: rawBalance === null || rawBalance === undefined || rawBalance === '' ? null : Number(rawBalance) }
}))
const accountBalanceGroups = computed(() => groupAccounts(accountBalances.value).map((group) => ({
  ...group,
  total_cents: group.items.reduce((total, account) => total + (Number.isFinite(account.balance_cents) ? account.balance_cents : 0), 0),
})))
function summarizeTransactions(items) {
  const active = items.filter((item) => !isVoided(item))
  const incomeItems = active.filter((item) => item.direction === 'income')
  const expenseItems = active.filter((item) => item.direction === 'expense')
  const income = incomeItems.reduce((sum, item) => sum + cents(item), 0)
  const expense = expenseItems.reduce((sum, item) => sum + cents(item), 0)
  return { income, expense, net: income - expense, incomeCount: incomeItems.length, expenseCount: expenseItems.length }
}
const summary = computed(() => summarizeTransactions(cashflowTransactions.value))
const todaySummary = computed(() => summarizeTransactions(cashflowTransactions.value.filter((item) => {
  const occurredAt = item.occurred_at || item.occurred_time
  const occurredTimestamp = timestampValue(occurredAt)
  return beijingDateIso(occurredAt) === todayIso && (!Number.isFinite(occurredTimestamp) || occurredTimestamp <= summaryAsOf.value)
})))
function cents(item) { return Number(item.amount_cents ?? item.amount ?? 0) || 0 }
function isVoided(item) { return item.status === 'voided' || item.status === 'void' || item.is_voided === true }
function isTransfer(item) { return String(item?.kind || '').toLowerCase() === 'transfer' }
function transactionFullNote(transaction) { return String(transaction?.notes ?? transaction?.note ?? '').trim() }
function transactionNote(transaction, limit = 24) {
  const note = transactionFullNote(transaction)
  return note.length > limit ? `${note.slice(0, limit)}…` : note
}

async function loadMonthTransactions() {
  const pageSize = 200
  const result = []
  for (let page = 1; ; page += 1) {
    const rows = await transactionsApi.list({ from: monthStart, to: monthEnd, include_voided: true, page, page_size: pageSize })
    result.push(...rows)
    if (rows.length < pageSize) return result
  }
}

async function load() {
  loading.value = true; errorMessage.value = ''
  try {
    const [rows, categoryResult, methodResult] = await Promise.all([
      loadMonthTransactions(),
      categoriesApi.list(),
      paymentMethodsApi.list(),
    ])
    summaryAsOf.value = Date.now()
    categories.value = categoryResult
    paymentMethods.value = methodResult
    monthTransactions.value = rows.map((item) => ({
      ...item,
      category_name: item.category_name || item.category?.name || categories.value.find((category) => String(category.id) === String(item.category_id))?.name,
      payment_method_name: item.payment_method_name || item.payment_method?.name || paymentMethods.value.find((method) => String(method.id) === String(item.payment_method_id))?.name,
      transfer_payment_method_name: item.transfer_payment_method_name || item.transfer_payment_method?.name || paymentMethods.value.find((method) => String(method.id) === String(item.transfer_payment_method_id))?.name,
    }))
  }
  catch (error) { errorMessage.value = error instanceof ApiError ? error.message : '概览数据加载失败。' }
  finally { loading.value = false }
}
function categoryName(transaction) { return isTransfer(transaction) ? (transaction.category_name || '内部转账') : (transaction.category_name || transaction.category?.name || '未分类') }
function paymentMethodName(transaction) {
  const source = transaction.payment_method_name || transaction.payment_method?.name || '—'
  if (!isTransfer(transaction)) return source
  return `${source} → ${transaction.transfer_payment_method_name || transaction.transfer_payment_method?.name || '—'}`
}
function accountRoleLabel(role) { return ({ cash: '现金', liability: '负债', investment: '投资' })[String(role || 'cash')] || '现金' }
function accountRoleIcon(role) { return ({ cash: '¥', liability: '欠', investment: '↗' })[String(role || 'cash')] || '¥' }
function accountBalanceLabel(account) {
  if (!Number.isFinite(account.balance_cents)) return '未跟踪'
  return account.account_role === 'liability' ? `欠 ${formatMoney(account.balance_cents)}` : formatMoney(account.balance_cents)
}
function accountBalanceClass(account) { return account.account_role === 'liability' ? 'expense-text' : account.account_role === 'investment' ? 'investment-text' : 'income-text' }
function groupBalanceLabel(group) { return `${group.role === 'liability' ? '总欠款' : '合计'} ${formatMoney(group.total_cents)}` }
function groupBalanceClass(group) { return group.role === 'liability' ? 'expense-text' : group.role === 'investment' ? 'investment-text' : 'income-text' }
onMounted(load)
</script>

<style scoped>
.quick-link { display: inline-block; color: #fff; text-decoration: none; }.primary { border: 0; border-radius: 8px; background: #2563eb; color: #fff; padding: 11px 18px; font-size: 13px; font-weight: 600; cursor:pointer; white-space:nowrap}.primary:hover { background: #1d4ed8; }.small { padding: 10px 17px; }.summary-groups{display:grid;gap:14px;margin:32px 0}.cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; }.card { background: #fff; border-radius: 13px; padding: 22px; box-shadow: 0 2px 8px #243b5a0d; }.today-cards .card{border:1px solid #e8edf5}.card span { display: block; color: #8090a8; font-size: 13px; }.card strong { display: block; font-size: 25px; margin: 13px 0 9px; }.card em { font-style: normal; font-size: 12px; color: #93a0b1; }.income-text { color: #12966a; }.expense-text { color: #dc5a61; }.up { color: #16a46a !important; }.down { color: #d47777 !important; }.panel { background:#fff;border-radius:13px;box-shadow:0 2px 8px #243b5a0d}.recent-panel{min-height:350px;overflow:hidden}.panel-head{display:flex;align-items:center;justify-content:space-between;padding:21px 24px;border-bottom:1px solid #edf0f5}.panel-head h2{margin:0;color:#33425b;font-size:16px}.panel-head p{margin:5px 0 0;color:#9aa6b7;font-size:12px}.panel-head a{color:#3b82f6;font-size:13px;text-decoration:none}.empty,.state{text-align:center;padding:60px;color:#93a0b1}.empty div{font-size:36px}.empty h3{color:#506078;margin:15px 0 6px}.empty p,.state p{margin:0 0 18px;font-size:13px}.recent-list{padding:0 24px}.recent-row{min-height:74px;display:flex;align-items:center;gap:13px;border-bottom:1px solid #edf0f5}.recent-row:last-child{border-bottom:0}.recent-row.voided{opacity:.55}.recent-icon{display:grid;place-items:center;flex:0 0 34px;width:34px;height:34px;border-radius:10px;font-size:19px;font-weight:700}.income-bg{color:#12966a;background:#e7f8f0}.expense-bg{color:#d65b62;background:#fff0f0}.recent-info{min-width:0;flex:1}.recent-info strong{display:block;color:#4b5b73;font-size:13px}.recent-info span{display:block;color:#99a5b5;font-size:11px;margin-top:4px}.recent-note{display:block;max-width:560px;margin-top:4px;color:#77869b;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.recent-amount{font-size:14px;font-weight:700;white-space:nowrap}.voided-label{color:#9ba5b2;font-size:11px}.spinner{display:inline-block;width:18px;height:18px;margin-bottom:10px;border:2px solid #dce7f8;border-top-color:#2563eb;border-radius:50%;animation:spin .7s linear infinite}.error-state{color:#b54e58}.outline-button{border:1px solid #d6dfec;border-radius:8px;background:#fff;color:#52617a;padding:9px 16px;cursor:pointer;font-size:13px}@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:700px){.summary-groups{margin:22px 0}.cards{grid-template-columns:1fr;gap:12px}.card{padding:17px 18px}.card strong{font-size:21px;margin:9px 0 6px}.recent-list{padding:0 16px}.panel-head{padding:17px 16px}.recent-row{gap:10px}.recent-amount{font-size:13px}.voided-label{display:none}}
@media(max-width:700px){
  .quick-link,.outline-button,.empty .primary{min-height:44px;display:inline-flex;align-items:center;justify-content:center}
  .quick-link{padding:10px 12px}
  .cards{min-width:0}
  .card{min-width:0}
  .panel-head{gap:10px;align-items:flex-start}
  .panel-head>div{min-width:0}
  .panel-head h2,.panel-head p{overflow-wrap:anywhere;line-height:1.45}
  .panel-head a{display:inline-flex;align-items:center;min-height:44px;flex:0 0 auto;white-space:nowrap}
  .empty,.state{padding:44px 18px}
  .recent-row{min-width:0;padding:8px 0}
  .recent-info{min-width:0}
  .recent-info strong,.recent-info span{overflow-wrap:anywhere;word-break:break-word}
  .recent-info span{line-height:1.45;white-space:normal}
  .recent-amount{max-width:112px;overflow:hidden;text-overflow:ellipsis;text-align:right;line-height:1.35;white-space:normal;overflow-wrap:anywhere}
}
@media(max-width:380px){
  .quick-link{padding-left:9px;padding-right:9px;font-size:12px}
  .panel-head{padding-left:13px;padding-right:13px}
  .recent-list{padding-left:13px;padding-right:13px}
  .recent-row{gap:8px}
  .recent-amount{max-width:92px;font-size:12px}
}
.investment-text{color:#567cc5!important}.balance-panel{overflow:hidden;margin-top:18px}.balance-table-wrap{overflow-x:auto}.balance-table{width:100%;border-collapse:collapse}.balance-table th{background:#fafbfd;color:#8d9aae;font-size:11px;font-weight:600;text-align:left;padding:11px 24px;white-space:nowrap}.balance-table td{border-top:1px solid #edf0f5;color:#59677d;font-size:12px;padding:13px 24px}.balance-table .account-group-row td{padding-top:10px;padding-bottom:10px;border-top:1px solid #e2e8f1;background:#f8fafc}.balance-table tbody:first-of-type .account-group-row td{border-top:0}.account-group-title{display:inline-flex;align-items:center;gap:8px}.account-group-title>span{display:grid;place-items:center;width:25px;height:25px;border-radius:8px;font-size:11px;font-weight:700}.group-cash .account-group-title>span{color:#16825d;background:#e7f8f0}.group-investment .account-group-title>span{color:#5672b5;background:#edf2ff}.group-liability .account-group-title>span{color:#bf5962;background:#fff0f0}.account-group-title strong{color:#405169;font-size:12px}.account-group-title small{color:#9aa6b7;font-size:10px}.account-group-total{font-size:11px;white-space:nowrap}.account-name{display:inline-flex;align-items:center;gap:9px}.account-name strong{color:#43536c}.account-icon{display:grid;place-items:center;width:29px;height:29px;border-radius:9px;background:#edf4ff;color:#2563eb;font-size:12px;font-weight:700}.role-badge{display:inline-flex;align-items:center;border-radius:99px;padding:5px 8px;font-size:10px}.role-cash{color:#16825d;background:#e7f8f0}.role-liability{color:#bf5962;background:#fff0f0}.role-investment{color:#5672b5;background:#edf2ff}.balance-value{font-size:13px;white-space:nowrap}
</style>
