<template>
  <div class="mobile-dashboard">
    <router-link class="mobile-bookkeeping-fab" to="/ai" aria-label="记一笔" title="记一笔"><span aria-hidden="true">＋</span></router-link>
    <section class="mobile-summary" aria-label="本月收支摘要">
      <article class="mobile-summary-card income-card">
        <span>本月收入</span>
        <strong>{{ formatMoney(summary.income) }}</strong>
        <small>{{ summary.incomeCount }} 笔收入</small>
      </article>
      <article class="mobile-summary-card expense-card">
        <span>本月支出</span>
        <strong>{{ formatMoney(summary.expense) }}</strong>
        <small>{{ summary.expenseCount }} 笔支出</small>
      </article>
      <article class="mobile-summary-card net-card">
        <span>本月净收支</span>
        <strong :class="summary.net >= 0 ? 'income-text' : 'expense-text'">{{ summary.net >= 0 ? '+' : '−' }}{{ formatMoney(Math.abs(summary.net)) }}</strong>
        <small>收入 − 支出</small>
      </article>
    </section>
    <section class="mobile-summary mobile-today-summary" aria-label="本日收支摘要">
      <article class="mobile-summary-card income-card">
        <span>本日收入</span>
        <strong>{{ formatMoney(todaySummary.income) }}</strong>
        <small>{{ todaySummary.incomeCount }} 笔收入</small>
      </article>
      <article class="mobile-summary-card expense-card">
        <span>本日支出</span>
        <strong>{{ formatMoney(todaySummary.expense) }}</strong>
        <small>{{ todaySummary.expenseCount }} 笔支出</small>
      </article>
      <article class="mobile-summary-card net-card">
        <span>本日净收支</span>
        <strong :class="todaySummary.net >= 0 ? 'income-text' : 'expense-text'">{{ todaySummary.net >= 0 ? '+' : '−' }}{{ formatMoney(Math.abs(todaySummary.net)) }}</strong>
        <small>今日 00:00 至当前</small>
      </article>
    </section>

    <section class="mobile-recent panel" aria-labelledby="mobile-recent-title">
      <header class="mobile-section-head">
        <div><h2 id="mobile-recent-title">近期交易</h2><p>本月最新记录</p></div>
        <router-link to="/transactions" class="mobile-inline-link">查看全部</router-link>
      </header>
      <div v-if="loading" class="mobile-state"><span class="mobile-spinner"></span><p>正在加载…</p></div>
      <div v-else-if="errorMessage" class="mobile-state mobile-error"><p>{{ errorMessage }}</p><button type="button" class="mobile-outline" @click="$emit('retry')">重试</button></div>
      <div v-else-if="!recent.length" class="mobile-state"><div class="mobile-empty-icon">📒</div><h3>暂无交易记录</h3><p>开始记录您的第一笔收支吧</p><router-link class="mobile-primary" to="/ai">＋ 记一笔</router-link></div>
      <div v-else class="mobile-recent-list">
        <article v-for="transaction in recent" :key="transaction.id" class="mobile-transaction-card" :class="{ voided: isVoided(transaction) }">
          <div class="mobile-transaction-icon" :class="transaction.direction === 'income' ? 'income-bg' : 'expense-bg'">{{ transaction.direction === 'income' ? '↓' : '↑' }}</div>
          <div class="mobile-transaction-main">
            <strong>{{ categoryName(transaction) }}</strong>
            <span>{{ formatDateTime(transaction.occurred_at || transaction.occurred_time) }} · {{ paymentMethodName(transaction) }}</span>
            <small v-if="transactionNote(transaction, 16)" class="mobile-transaction-note" :title="transactionFullNote(transaction)">备注：{{ transactionNote(transaction, 16) }}</small>
          </div>
          <div class="mobile-transaction-side">
            <b :class="transaction.direction === 'income' ? 'income-text' : 'expense-text'">{{ transaction.direction === 'income' ? '+' : '−' }}{{ formatMoney(cents(transaction), '') }}</b>
            <em v-if="isVoided(transaction)">已作废</em>
          </div>
        </article>
      </div>
    </section>

    <section class="mobile-balances panel" aria-labelledby="mobile-balances-title">
      <header class="mobile-section-head"><div><h2 id="mobile-balances-title">资金账户余额</h2><p>现金、投资、负债账户</p></div><router-link to="/settings" class="mobile-inline-link">管理账户</router-link></header>
      <div v-if="loading && !accountBalances.length" class="mobile-state"><span class="mobile-spinner"></span><p>正在加载账户余额…</p></div>
      <div v-else-if="!accountBalances.length" class="mobile-state"><div class="mobile-empty-icon">◌</div><h3>还没有资金账户</h3><p>在设置中添加资金账户。</p><router-link class="mobile-primary" to="/settings">去设置</router-link></div>
      <div v-else class="mobile-balance-groups"><section v-for="group in accountBalanceGroups" :key="group.role" class="mobile-balance-group"><header><span class="mobile-balance-group-icon" :class="`role-${group.role}`">{{ group.icon }}</span><strong>{{ group.label }}</strong><small>{{ group.items.length }} 个</small><b :class="groupBalanceClass(group)">{{ groupBalanceLabel(group) }}</b></header><div class="mobile-balance-list"><article v-for="account in group.items" :key="account.id" class="mobile-balance-card"><span class="mobile-balance-icon" :class="`role-${account.account_role}`">{{ account.icon || accountRoleIcon(account.account_role) }}</span><div class="mobile-balance-main"><strong>{{ account.name }}</strong></div><b :class="accountBalanceClass(account)">{{ accountBalanceLabel(account) }}</b></article></div></section></div>
    </section>
  </div>
</template>

<script setup>
import { toRefs } from 'vue'
import { formatDateTime, formatMoney } from '../api'

defineEmits(['retry'])
const props = defineProps({
  summary: { type: Object, required: true },
  todaySummary: { type: Object, required: true },
  recent: { type: Array, default: () => [] },
  accountBalances: { type: Array, default: () => [] },
  accountBalanceGroups: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  errorMessage: { type: String, default: '' },
  categoryName: { type: Function, required: true },
  paymentMethodName: { type: Function, required: true },
  transactionNote: { type: Function, required: true },
  transactionFullNote: { type: Function, required: true },
  cents: { type: Function, required: true },
  isVoided: { type: Function, required: true },
})
const { summary, todaySummary, recent, accountBalances, accountBalanceGroups, loading, errorMessage, categoryName, paymentMethodName, transactionNote, transactionFullNote, cents, isVoided } = toRefs(props)
function accountRoleLabel(role) { return ({ cash: '现金', liability: '负债', investment: '投资' })[String(role || 'cash')] || '现金' }
function accountRoleIcon(role) { return ({ cash: '¥', liability: '欠', investment: '↗' })[String(role || 'cash')] || '¥' }
function accountBalanceLabel(account) {
  if (!Number.isFinite(account.balance_cents)) return '未跟踪'
  return account.account_role === 'liability' ? `欠 ${formatMoney(account.balance_cents)}` : formatMoney(account.balance_cents)
}
function accountBalanceClass(account) { return account.account_role === 'liability' ? 'expense-text' : account.account_role === 'investment' ? 'investment-text' : 'income-text' }
function groupBalanceLabel(group) { return `${group.role === 'liability' ? '欠' : ''}${formatMoney(group.total_cents)}` }
function groupBalanceClass(group) { return group.role === 'liability' ? 'expense-text' : group.role === 'investment' ? 'investment-text' : 'income-text' }
</script>

<style scoped>
.mobile-dashboard{display:grid;gap:14px;margin-top:20px;min-width:0}.panel{background:#fff;border-radius:14px;box-shadow:0 2px 8px #243b5a0d}.mobile-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.mobile-today-summary{margin-top:-6px}.mobile-today-summary .mobile-summary-card{border:1px solid #e8edf5;border-top-width:3px}.mobile-today-summary .income-card{border-top-color:#35ae82}.mobile-today-summary .expense-card{border-top-color:#df7378}.mobile-today-summary .net-card{border-top-color:#7299d9}.mobile-summary-card{min-width:0;min-height:112px;border-radius:13px;padding:13px 11px;display:flex;flex-direction:column;justify-content:space-between;background:#fff;box-shadow:0 2px 8px #243b5a0d}.mobile-summary-card span{color:#7e8da4;font-size:11px}.mobile-summary-card strong{font-size:17px;line-height:1.25;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.mobile-summary-card small{color:#96a2b2;font-size:10px}.income-card{border-top:3px solid #35ae82}.expense-card{border-top:3px solid #df7378}.net-card{border-top:3px solid #7299d9}.income-text{color:#12966a}.expense-text{color:#dc5a61}.mobile-section-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;padding:16px;border-bottom:1px solid #edf0f5}.mobile-section-head h2{margin:0;color:#33425b;font-size:16px}.mobile-section-head p{margin:5px 0 0;color:#9aa6b7;font-size:11px}.mobile-inline-link{min-height:44px;display:inline-flex;align-items:center;color:#2563eb;text-decoration:none;font-size:12px;white-space:nowrap}.mobile-recent-list{padding:0 14px}.mobile-transaction-card{display:flex;align-items:center;gap:10px;min-width:0;min-height:74px;padding:10px 2px;border-bottom:1px solid #edf0f5}.mobile-transaction-card:last-child{border-bottom:0}.mobile-transaction-card.voided{opacity:.55}.mobile-transaction-icon{width:36px;height:36px;flex:0 0 36px;display:grid;place-items:center;border-radius:10px;font-size:18px;font-weight:700}.income-bg{color:#12966a;background:#e7f8f0}.expense-bg{color:#d65b62;background:#fff0f0}.mobile-transaction-main{min-width:0;flex:1}.mobile-transaction-main strong,.mobile-transaction-main span,.mobile-transaction-main small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.mobile-transaction-main strong{color:#4b5b73;font-size:13px}.mobile-transaction-main span{margin-top:4px;color:#8f9bad;font-size:10px}.mobile-transaction-main small{margin-top:3px;color:#a5afbc;font-size:10px}.mobile-transaction-main .mobile-transaction-note{color:#77869b}.mobile-transaction-side{min-width:0;max-width:105px;text-align:right}.mobile-transaction-side b{display:block;font-size:13px;overflow-wrap:anywhere}.mobile-transaction-side em{display:block;margin-top:4px;color:#9ba5b2;font-size:10px;font-style:normal}.mobile-state{display:grid;place-content:center;justify-items:center;min-height:220px;padding:28px 16px;text-align:center;color:#8b98aa}.mobile-state p{margin:0 0 14px;font-size:12px;line-height:1.5}.mobile-state h3{margin:11px 0 5px;color:#52617a;font-size:16px}.mobile-empty-icon{font-size:32px}.mobile-error p{color:#b54e58}.mobile-primary,.mobile-outline{min-height:44px;display:inline-flex;align-items:center;justify-content:center;border-radius:8px;padding:9px 15px;font-size:13px;text-decoration:none;cursor:pointer}.mobile-primary{border:0;background:#2563eb;color:#fff;font-weight:600}.mobile-outline{border:1px solid #d6dfec;background:#fff;color:#52617a}.mobile-spinner{width:18px;height:18px;border:2px solid #dce7f8;border-top-color:#2563eb;border-radius:50%;animation:spin .7s linear infinite;margin-bottom:9px}@keyframes spin{to{transform:rotate(360deg)}}
.mobile-bookkeeping-fab{position:fixed;right:max(18px,env(safe-area-inset-right,0px));bottom:calc(80px + env(safe-area-inset-bottom,0px));z-index:39;display:grid;place-items:center;width:58px;height:58px;border:1px solid #ffffff99;border-radius:50%;background:linear-gradient(145deg,#3b82f6,#1d4ed8);color:#fff;text-decoration:none;box-shadow:0 10px 28px #1d4ed84d,0 2px 7px #183b7738;touch-action:manipulation}.mobile-bookkeeping-fab span{font-size:30px;font-weight:300;line-height:1;transform:translateY(-1px)}.mobile-bookkeeping-fab:active{transform:scale(.96)}.mobile-bookkeeping-fab:focus-visible{outline:3px solid #93c5fd;outline-offset:3px}
@media(max-width:370px){.mobile-summary{gap:6px}.mobile-summary-card{padding:12px 8px}.mobile-summary-card strong{font-size:14px}.mobile-summary-card small{font-size:9px}.mobile-transaction-side{max-width:89px}}
.investment-text{color:#567cc5}.mobile-balances{overflow:hidden}.mobile-balance-groups{display:grid}.mobile-balance-group+ .mobile-balance-group{border-top:8px solid #f3f6fa}.mobile-balance-group>header{display:flex;align-items:center;gap:8px;min-height:45px;padding:8px 16px;background:#fafbfd;border-bottom:1px solid #edf0f5}.mobile-balance-group>header>strong{color:#405169;font-size:12px}.mobile-balance-group>header>small{color:#9aa6b7;font-size:10px}.mobile-balance-group>header>b{margin-left:auto;font-size:11px;white-space:nowrap}.mobile-balance-group-icon{display:grid;place-items:center;width:26px;height:26px;border-radius:8px;font-size:11px;font-weight:700}.mobile-balance-group-icon.role-cash{color:#16825d;background:#e7f8f0}.mobile-balance-group-icon.role-liability{color:#bf5962;background:#fff0f0}.mobile-balance-group-icon.role-investment{color:#5672b5;background:#edf2ff}.mobile-balance-list{padding:0 14px}.mobile-balance-card{display:flex;align-items:center;gap:10px;min-width:0;min-height:58px;padding:9px 2px;border-bottom:1px solid #edf0f5}.mobile-balance-card:last-child{border-bottom:0}.mobile-balance-icon{display:grid;place-items:center;flex:0 0 34px;width:34px;height:34px;border-radius:10px;font-size:12px;font-weight:700}.mobile-balance-icon.role-cash{color:#16825d;background:#e7f8f0}.mobile-balance-icon.role-liability{color:#bf5962;background:#fff0f0}.mobile-balance-icon.role-investment{color:#5672b5;background:#edf2ff}.mobile-balance-main{min-width:0;flex:1}.mobile-balance-main strong{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#4b5b73;font-size:13px}.mobile-balance-card>b{max-width:125px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px;text-align:right}
</style>
