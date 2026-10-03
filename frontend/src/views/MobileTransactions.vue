<template>
  <div class="mobile-transactions">
    <section class="mobile-filter-summary" aria-label="收支筛选">
      <div class="mobile-filter-actions">
        <button type="button" class="mobile-filter-trigger" @click="filterOpen = true"><span>☷</span> 筛选流水 <small v-if="activeFilterCount">{{ activeFilterCount }} 项</small></button>
        <button type="button" class="mobile-report-trigger" :disabled="ask.loading" :title="reportQuestion" @click="generateReport"><span v-if="ask.reportLoading" class="mobile-spinner"></span><span v-else aria-hidden="true">▤</span> {{ ask.reportLoading ? '生成中…' : '生成报告' }}</button>
      </div>
      <span class="mobile-result-count">{{ transactions.length }} 笔</span>
    </section>

    <section class="mobile-finance-summary" aria-label="收支汇总">
      <div><span>收入</span><strong class="income-text">{{ formatMoney(summary.income) }}</strong></div>
      <div><span>支出</span><strong class="expense-text">{{ formatMoney(summary.expense) }}</strong></div>
      <div><span>净收支</span><strong :class="summary.net >= 0 ? 'income-text' : 'expense-text'">{{ summary.net >= 0 ? '+' : '−' }}{{ formatMoney(Math.abs(summary.net)) }}</strong></div>
    </section>

    <section class="mobile-transaction-list panel" aria-labelledby="mobile-transactions-title">
      <header class="mobile-list-head"><div><h2 id="mobile-transactions-title">收支流水</h2><p>按筛选条件显示最近记录</p></div><div class="mobile-list-actions"><button type="button" class="mobile-manual-link" @click="openCreate">手动记账</button></div></header>
      <div v-if="loading" class="mobile-state"><span class="mobile-spinner"></span><p>正在加载流水…</p></div>
      <div v-else-if="errorMessage" class="mobile-state mobile-error"><p>{{ errorMessage }}</p><button type="button" class="mobile-outline" @click="loadTransactions">重试</button></div>
      <div v-else-if="!transactions.length" class="mobile-state"><div class="mobile-empty-icon">📒</div><h3>暂无交易记录</h3><p>调整筛选条件，或开始记录您的第一笔收支吧</p><div class="mobile-empty-actions"><router-link class="mobile-primary" to="/ai">＋ 记一笔</router-link><button type="button" class="mobile-outline" @click="openCreate">手动记账</button></div></div>
      <div v-else class="mobile-transaction-cards">
        <article v-for="transaction in transactions" :key="transaction.id" class="mobile-transaction-card" :class="{ voided: isVoided(transaction) }">
          <div class="mobile-card-top">
            <span class="mobile-direction" :class="isTransfer(transaction) ? 'transfer-badge' : transaction.direction === 'income' ? 'income-badge' : 'expense-badge'">{{ isTransfer(transaction) ? '转账' : transaction.direction === 'income' ? '收入' : '支出' }}</span>
            <time>{{ formatDateTime(transaction.occurred_at || transaction.occurred_time) }}</time>
            <span v-if="isVoided(transaction)" class="mobile-status voided-status">已作废</span>
          </div>
          <div class="mobile-card-main"><strong>{{ categoryName(transaction) }}</strong><b :class="isTransfer(transaction) ? 'transfer-text' : transaction.direction === 'income' ? 'income-text' : 'expense-text'">{{ isTransfer(transaction) ? '↔' : transaction.direction === 'income' ? '+' : '−' }}{{ formatMoney(transactionCents(transaction), '') }}</b></div>
          <div class="mobile-card-meta"><span>{{ paymentMethodName(transaction) }}</span><span>{{ transaction.partner_name || '无往来账户' }}</span></div>
          <p v-if="transaction.notes || transaction.note" class="mobile-card-notes">{{ transaction.notes || transaction.note }}</p>
          <div class="mobile-card-actions"><button type="button" class="mobile-text-button" :disabled="isVoided(transaction)" @click="openEdit(transaction)">编辑</button><button type="button" class="mobile-text-button danger" :disabled="isVoided(transaction)" @click="voidTransaction(transaction)">作废</button></div>
        </article>
      </div>
    </section>


    <section v-if="ask.messages.length || ask.loading" ref="askThread" class="mobile-ask panel" aria-label="AI 问答">
      <header class="mobile-list-head"><div><h2>问账</h2><p>可以接着追问；改账方案需你确认后才执行</p></div><button type="button" class="mobile-text-button" @click="newConversation">新对话</button></header>
      <div v-if="ask.messages.length || ask.loading" class="mobile-ask-thread" aria-live="polite">
        <div v-for="(message, index) in ask.messages" :key="index" class="mobile-ask-message" :class="message.role === 'user' ? 'is-user' : 'is-assistant'">
          <ul v-if="message.steps && message.steps.length" class="mobile-ask-steps"><li v-for="(step, stepIndex) in message.steps" :key="stepIndex">{{ step.summary }}<em v-if="step.result"> → {{ step.result }}</em></li></ul>
          <p>{{ message.content }}</p>
          <div v-for="proposal in (message.proposals || [])" :key="proposal.index" class="mobile-ask-proposal" :class="`is-${proposal.status}`">
            <div class="mobile-ask-proposal-head"><strong>{{ proposalLabel(proposal) }}<span v-if="proposal.transaction_id"> #{{ proposal.transaction_id }}</span></strong><span class="mobile-ask-proposal-status">{{ ({ pending: '待确认', applied: '已执行', ignored: '已忽略', failed: '执行失败' })[proposal.status] || proposal.status }}</span></div>
            <p v-if="proposal.before"><span>原记录</span>{{ describeSnapshot(proposal.before) }}</p>
            <p v-if="proposal.after"><span>{{ proposal.type === 'create' ? '补记为' : '改为' }}</span>{{ describeSnapshot(proposal.after) }}</p>
            <p v-if="proposal.reason"><span>原因</span>{{ proposal.reason }}</p>
            <p v-if="proposal.detail" class="is-error"><span>说明</span>{{ proposal.detail }}</p>
            <div v-if="proposal.status === 'pending'" class="mobile-ask-proposal-actions"><button class="mobile-primary" type="button" :disabled="proposal.busy" @click="applyProposal(message, proposal)">{{ proposal.busy ? '执行中…' : '确认执行' }}</button><button class="mobile-outline" type="button" :disabled="proposal.busy" @click="ignoreProposal(message, proposal)">忽略</button></div>
          </div>
          <small v-if="message.role === 'assistant' && (message.period || message.warning)">{{ [message.period, message.warning].filter(Boolean).join(' · ') }}<button v-if="message.report_id || message.report" type="button" class="mobile-ask-report-link" @click="openReport(message)">查看报告卡片 →</button></small>
        </div>
        <div v-if="ask.loading" class="mobile-ask-message is-assistant is-live" aria-live="polite">
          <ul v-if="ask.steps && ask.steps.length" class="mobile-ask-steps"><li v-for="(step, stepIndex) in ask.steps" :key="stepIndex">{{ step.summary }}<em v-if="step.result"> → {{ step.result }}</em></li></ul>
          <p>{{ ask.stage || '正在思考…' }}</p>
        </div>
      </div>
    </section>

    <section class="mobile-ask-composer panel" aria-label="向 AI 查账">
      <form class="mobile-ask-form" @submit.prevent="askLedger(ask.text)">
        <label class="sr-only" for="mobile-ask-input">查账问题</label>
        <div class="mobile-ask-row">
          <textarea id="mobile-ask-input" :value="ask.text" rows="1" maxlength="1000" :disabled="ask.loading" placeholder="问问账本：花了多少？哪类最多？" @input="ask.text = $event.target.value; autoGrow($event.target)" @keydown.enter.exact.prevent="askLedger(ask.text)"></textarea>
          <button class="mobile-ask-send" type="submit" :disabled="ask.loading || !ask.text" :aria-label="ask.loading ? '思考中' : '提问'"><span v-if="ask.loading" class="mobile-spinner light"></span><span v-else aria-hidden="true">↑</span></button>
        </div>
        <div class="mobile-ask-foot"><span v-if="ask.error" class="mobile-ask-inline-error" role="alert">{{ ask.error }}</span><span v-else>AI 自行决定查询范围 · 报告在上方筛选栏生成</span><span class="mobile-ask-foot-actions"><button class="mobile-text-button" type="button" @click="toggleHistory">{{ ask.historyOpen ? '收起' : '历史' }}</button><button v-if="ask.messages.length" class="mobile-text-button" type="button" @click="newConversation">新对话</button></span></div>
      </form>
      <div v-if="ask.historyOpen" class="mobile-ask-history" aria-label="历史对话">
        <p v-if="ask.historyLoading" class="mobile-ask-history-empty">正在加载…</p>
        <p v-else-if="!ask.history.length" class="mobile-ask-history-empty">还没有历史对话。</p>
        <ul v-else>
          <li v-for="item in ask.history" :key="item.id" :class="{ 'is-current': item.id === ask.conversationId }"><button type="button" class="mobile-ask-history-item" @click="loadConversation(item.id)"><strong>{{ item.title }}</strong><small>{{ formatDateTime(item.updated_at) }} · {{ Math.floor(item.message_count / 2) }} 轮</small></button><button type="button" class="mobile-text-button danger" @click="deleteConversation(item.id)">删除</button></li>
        </ul>
      </div>
    </section>
    <div v-if="filterOpen" class="mobile-sheet-backdrop" @click.self="filterOpen = false">
      <section class="mobile-sheet" role="dialog" aria-modal="true" aria-labelledby="mobile-filter-title">
        <header class="mobile-sheet-head"><div><h2 id="mobile-filter-title">筛选流水</h2><p>选择条件后点击应用</p></div><button type="button" class="mobile-close" aria-label="关闭筛选" @click="filterOpen = false">×</button></header>
        <div class="mobile-filter-form">
          <label>流水类型<select v-model="filters.direction"><option value="">全部类型</option><option value="income">收入</option><option value="expense">支出</option><option value="transfer">转账/还款</option></select></label>
          <div class="mobile-filter-dates"><label>开始日期<DateSegmentInput :model-value="filters.from" edge="start" label="开始日期" @update:model-value="filters.from = $event" /></label><label>结束日期<DateSegmentInput :model-value="filters.to" edge="end" label="结束日期" placeholder="如 20261031 / 202610" @update:model-value="filters.to = $event" /></label></div>
          <label>分类<select v-model="filters.category_id"><option value="">全部分类</option><option v-for="category in visibleCategories" :key="category.id" :value="category.id">{{ category.name }}</option></select></label>
          <label>资金账户<select v-model="filters.payment_method_id"><option value="">全部账户</option><option v-for="method in paymentMethods" :key="method.id" :value="method.id">{{ paymentMethodOptionLabel(method) }}</option></select></label>
          <label>往来账户<select v-model="filters.partner_id"><option value="">全部账户</option><option v-for="partner in partners" :key="partner.id" :value="partner.id">{{ partner.name }}</option></select></label>
        </div>
        <footer class="mobile-sheet-actions"><button type="button" class="mobile-outline" @click="resetFiltersAndClose">重置</button><button type="button" class="mobile-primary" @click="applyFilters">应用筛选</button></footer>
      </section>
    </div>

    <div v-if="modalOpen" class="mobile-sheet-backdrop" @click.self="closeModal">
      <section class="mobile-sheet" role="dialog" aria-modal="true" :aria-labelledby="editing ? 'mobile-edit-title' : 'mobile-create-title'">
        <header class="mobile-sheet-head"><div><h2 :id="editing ? 'mobile-edit-title' : 'mobile-create-title'">{{ editing ? (isTransferForm ? '编辑转账' : '编辑收支') : '手动记账' }}</h2><p>{{ isTransferForm ? '转账/还款只在账户之间移动余额，不计入收支' : '金额以元填写，系统按分保存' }}</p></div><div class="mobile-sheet-head-actions"><router-link v-if="!editing" class="mobile-ai-switch" to="/ai" @click="closeModal">改用 AI</router-link><button type="button" class="mobile-close" aria-label="关闭" @click="closeModal">×</button></div></header>
        <div v-if="formError" class="mobile-form-error" role="alert">{{ formError }}</div>
        <form class="mobile-entry-form" @submit.prevent="saveTransaction">
          <div class="mobile-direction-toggle" role="radiogroup" aria-label="流水类型"><button type="button" :class="{ selected: formType === 'expense' }" @click="setFormType('expense')">支出</button><button type="button" :class="{ selected: formType === 'income' }" @click="setFormType('income')">收入</button><button type="button" :class="{ selected: formType === 'transfer' }" @click="setFormType('transfer')">转账/还款</button></div>
          <p v-if="isTransferForm" class="mobile-transfer-hint">来源账户余额减少；转入信用卡、花呗等负债账户时欠款减少，转入现金或投资账户时余额增加。</p>
          <label>金额（元）<input v-model="form.amount" inputmode="decimal" pattern="^[0-9]+([.][0-9]{1,2})?$" placeholder="0.00" required /></label>
          <label>发生时间<input v-model="form.occurred_at" type="datetime-local" required /></label>
          <label v-if="!isTransferForm">分类<select v-model="form.category_id" required><option value="" disabled>请选择分类</option><option v-for="category in formCategories" :key="category.id" :value="String(category.id)">{{ category.name }}</option></select></label>
          <label>{{ isTransferForm ? '来源账户' : form.direction === 'income' ? '收款账户' : '支付账户' }}<select v-model="form.payment_method_id" required><option value="" disabled>请选择账户</option><option v-for="method in formPaymentMethods" :key="method.id" :value="String(method.id)">{{ paymentMethodOptionLabel(method) }}</option></select></label>
          <label v-if="isTransferForm">转入/还款账户<select v-model="form.transfer_payment_method_id" required><option value="" disabled>请选择账户</option><option v-for="method in formPaymentMethods" :key="method.id" :value="String(method.id)" :disabled="String(method.id) === String(form.payment_method_id)">{{ paymentMethodOptionLabel(method) }}</option></select></label>
          <label v-else>往来账户（可选）<select v-model="form.partner_id"><option value="">不关联</option><option v-for="partner in partners" :key="partner.id" :value="String(partner.id)">{{ partner.name }}</option></select></label>
          <label>备注（可选）<textarea v-model.trim="form.notes" rows="3" maxlength="500" placeholder="补充说明…"></textarea></label>
          <footer class="mobile-sheet-actions"><button type="button" class="mobile-outline" @click="closeModal">取消</button><button type="submit" class="mobile-primary" :disabled="saving"><span v-if="saving" class="mobile-spinner light"></span>{{ saving ? '保存中…' : (editing ? '保存修改' : isTransferForm ? '确认转账' : '确认入账') }}</button></footer>
        </form>
      </section>
    </div>
  </div>
</template>

<script setup>
import DateSegmentInput from '../components/DateSegmentInput.vue'
import { computed, nextTick, ref, toRefs, watch } from 'vue'
import { formatDateTime, formatMoney } from '../api'

const props = defineProps({
  transactions: { type: Array, default: () => [] },
  summary: { type: Object, required: true },
  categories: { type: Array, default: () => [] },
  visibleCategories: { type: Array, default: () => [] },
  formCategories: { type: Array, default: () => [] },
  paymentMethods: { type: Array, default: () => [] },
  formPaymentMethods: { type: Array, default: () => [] },
  partners: { type: Array, default: () => [] },
  filters: { type: Object, required: true },
  ask: { type: Object, default: () => ({ text: '', loading: false, error: '', messages: [] }) },
  askScopeLabel: { type: String, default: '' },
  reportQuestion: { type: String, default: '生成本月的收支报告' },
  askLedger: { type: Function, default: () => {} },
  generateReport: { type: Function, default: () => {} },
  openReport: { type: Function, default: () => {} },
  clearAsk: { type: Function, default: () => {} },
  proposalLabel: { type: Function, default: () => '' },
  describeSnapshot: { type: Function, default: () => '' },
  applyProposal: { type: Function, default: () => {} },
  ignoreProposal: { type: Function, default: () => {} },
  loadConversation: { type: Function, default: () => {} },
  toggleHistory: { type: Function, default: () => {} },
  newConversation: { type: Function, default: () => {} },
  deleteConversation: { type: Function, default: () => {} },
  form: { type: Object, required: true },
  loading: { type: Boolean, default: false },
  saving: { type: Boolean, default: false },
  errorMessage: { type: String, default: '' },
  formError: { type: String, default: '' },
  modalOpen: { type: Boolean, default: false },
  editing: { type: Object, default: null },
  categoryName: { type: Function, required: true },
  paymentMethodName: { type: Function, required: true },
  paymentMethodOptionLabel: { type: Function, required: true },
  transactionCents: { type: Function, required: true },
  isVoided: { type: Function, required: true },
  loadTransactions: { type: Function, required: true },
  resetFilters: { type: Function, required: true },
  openCreate: { type: Function, required: true },
  openEdit: { type: Function, required: true },
  closeModal: { type: Function, required: true },
  saveTransaction: { type: Function, required: true },
  voidTransaction: { type: Function, required: true },
})
const { transactions, summary, visibleCategories, formCategories, paymentMethods, formPaymentMethods, partners, filters, form, loading, saving, errorMessage, formError, modalOpen, editing, categoryName, paymentMethodName, paymentMethodOptionLabel, transactionCents, isVoided, loadTransactions, resetFilters, openCreate, openEdit, closeModal, saveTransaction, voidTransaction } = toRefs(props)
const filterOpen = ref(false)
const isTransferForm = computed(() => form.value?.kind === 'transfer')
const formType = computed(() => (isTransferForm.value ? 'transfer' : form.value?.direction))
function setFormType(type) {
  const target = form.value
  if (!target) return
  if (type === 'transfer') { target.kind = 'transfer'; target.direction = 'expense'; target.category_id = ''; target.partner_id = ''; return }
  target.kind = 'cashflow'; target.direction = type; target.transfer_payment_method_id = ''
}
const activeFilterCount = computed(() => ['direction', 'from', 'to', 'category_id', 'payment_method_id', 'partner_id'].filter((key) => String(filters.value?.[key] || '') !== '').length)
function isTransfer(transaction) { return String(transaction?.kind || '').toLowerCase() === 'transfer' }
function applyFilters() { filterOpen.value = false; loadTransactions.value() }
function autoGrow(element) {
  if (!element) return
  element.style.height = 'auto'
  element.style.height = `${Math.min(element.scrollHeight, 110)}px`
}
const askThread = ref(null)
watch(() => props.ask.messages.length + (props.ask.loading ? 1 : 0), () => {
  nextTick(() => {
    const items = askThread.value?.querySelectorAll('.mobile-ask-message')
    items?.[items.length - 1]?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  })
})
function resetFiltersAndClose() { resetFilters.value(); filterOpen.value = false }
</script>

<style scoped>
.mobile-transactions{padding-bottom:150px}.mobile-ask{padding:0 0 13px}.mobile-ask .mobile-ask-thread{padding:0 14px}.mobile-ask-composer{position:fixed;right:max(10px,env(safe-area-inset-right,0px));bottom:calc(72px + env(safe-area-inset-bottom,0px));left:max(10px,env(safe-area-inset-left,0px));z-index:45;margin:0;padding:8px;border:1px solid #d8e6f8;border-radius:16px;box-shadow:0 10px 32px #23436d2b}.mobile-ask-form{display:grid;grid-template-columns:minmax(0,1fr);gap:7px}.mobile-ask-form>*{min-width:0}.mobile-ask-row{display:flex;align-items:center;gap:8px}.mobile-ask-row textarea{flex:1;min-width:0}.mobile-ask-send{display:grid;place-items:center;flex:0 0 42px;width:42px;height:42px;border:0;border-radius:50%;background:#2563eb;color:#fff;font-size:22px;line-height:1;box-shadow:0 4px 10px #2563eb38;cursor:pointer}.mobile-ask-send:disabled{opacity:.45;cursor:wait;box-shadow:none}.mobile-ask-send .mobile-spinner{margin:0}.mobile-ask-foot{display:flex;align-items:center;justify-content:space-between;gap:8px;color:#8b99ac;font-size:11px;line-height:1.4}.mobile-ask-foot>span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.mobile-ask-inline-error{color:#a83232}.mobile-ask-foot-actions{display:inline-flex;gap:4px;flex:0 0 auto}.mobile-ask-history{max-height:200px;overflow-y:auto;margin-top:6px;border-top:1px solid #edf1f6;padding-top:6px}.mobile-ask-history ul{list-style:none;margin:0;padding:0;display:grid;gap:2px}.mobile-ask-history li{display:flex;align-items:center;gap:6px;border-radius:8px;padding:0 4px}.mobile-ask-history li.is-current{background:#eaf2ff}.mobile-ask-history-item{flex:1;min-width:0;display:grid;gap:2px;text-align:left;border:0;background:transparent;padding:7px 4px;font:inherit;color:#34435b}.mobile-ask-history-item strong{font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.mobile-ask-history-item small{color:#8a97aa;font-size:11px}.mobile-ask-history-empty{margin:6px 0;color:#8a97aa;font-size:12px}.mobile-text-button.danger{color:#c8555d}.mobile-ask-proposal{margin-top:8px;padding:10px 11px;border:1px solid #dbe6f5;border-radius:10px;background:#fff;color:#52627a;font-size:12px}.mobile-ask-proposal.is-applied{border-color:#c9ebd9;background:#f3fbf7}.mobile-ask-proposal.is-failed{border-color:#f1d0d0;background:#fff6f6}.mobile-ask-proposal.is-ignored{opacity:.8}.mobile-ask-proposal-head{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:6px;color:#34435b}.mobile-ask-proposal-status{padding:2px 8px;border-radius:99px;background:#fff4da;color:#8a6924;font-size:11px;white-space:nowrap}.mobile-ask-proposal.is-applied .mobile-ask-proposal-status{background:#e7f8f0;color:#12845e}.mobile-ask-proposal p{margin:3px 0;padding:0;background:transparent;color:inherit;font-size:12px;white-space:normal}.mobile-ask-proposal p span{display:inline-block;min-width:44px;color:#8a97aa}.mobile-ask-proposal p.is-error{color:#a83232}.mobile-ask-proposal-actions{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px}.mobile-ask-proposal-actions button{min-height:40px}.mobile-ask-form textarea{display:block;width:100%;min-height:44px;max-height:110px;resize:none;border:1px solid #dbe4f0;border-radius:10px;padding:10px 12px;background:#fbfcff;color:#3f5068;font:inherit;font-size:16px;line-height:1.4;outline:0}.mobile-ask-form textarea:focus{border-color:#3b82f6}.mobile-ask-row{align-items:flex-end}.mobile-text-button{border:0;background:transparent;color:#2563eb;font-size:12px;padding:6px 0 6px 8px}.mobile-ask-thread{display:grid;gap:8px;margin-top:11px}.mobile-ask-message{max-width:94%;padding:9px 11px;border-radius:11px;font-size:13px;line-height:1.6}.mobile-ask-message p{margin:0;white-space:pre-wrap;overflow-wrap:anywhere}.mobile-ask-message small{display:block;margin-top:5px;color:#8a97aa;font-size:11px}.mobile-ask-message small a{color:#2563eb;text-decoration:none;font-weight:600}.mobile-ask-message.is-user{justify-self:end;background:#2563eb;color:#fff}.mobile-ask-message.is-assistant{justify-self:start;background:#f5f8fc;color:#52627a}.mobile-ask-message.is-live p{color:#7c8ba1}.mobile-ask-steps{margin:0 0 6px;padding:0;list-style:none;display:grid;gap:3px;color:#7c8ba1;font-size:11px}.mobile-ask-steps li::before{content:'✓ ';color:#2563eb}.mobile-ask-steps em{font-style:normal;color:#9aa6b6}.mobile-spinner.light{border-color:#ffffff66;border-top-color:#fff}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
.mobile-transactions{display:grid;gap:12px;margin-top:16px;min-width:0}.panel{background:#fff;border-radius:14px;box-shadow:0 2px 8px #243b5a0d}.mobile-filter-summary{display:flex;align-items:center;justify-content:space-between;gap:8px}.mobile-filter-actions{display:flex;align-items:center;gap:8px;min-width:0}.mobile-report-trigger{min-height:44px;display:inline-flex;align-items:center;gap:6px;border:1px solid #c9dbf7;border-radius:9px;background:#eaf2ff;color:#2563eb;padding:9px 12px;font:inherit;font-size:13px;font-weight:600;white-space:nowrap}.mobile-report-trigger:disabled{opacity:.6}.mobile-report-trigger span{font-size:15px}.mobile-report-trigger .mobile-spinner{width:13px;height:13px;margin:0;border-color:#bfd4f7;border-top-color:#2563eb}.mobile-ask-report-link{border:0;background:transparent;padding:0;margin-left:4px;color:#2563eb;font:inherit;font-size:11px;font-weight:600}.mobile-filter-trigger{min-height:44px;display:inline-flex;align-items:center;gap:7px;border:1px solid #d6dfec;border-radius:9px;background:#fff;color:#52617a;padding:9px 13px;font-size:13px;font-weight:600}.mobile-filter-trigger span{font-size:18px;color:#2563eb}.mobile-filter-trigger small{color:#2563eb;font-size:10px}.mobile-result-count{color:#8996a9;font-size:12px}.mobile-finance-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px}.mobile-finance-summary>div{min-width:0;display:flex;flex-direction:column;justify-content:center;gap:4px;min-height:66px;padding:10px;border-radius:10px;background:#fff;box-shadow:0 2px 8px #243b5a0d}.mobile-finance-summary span{color:#8b98aa;font-size:10px}.mobile-finance-summary strong{font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.income-text{color:#12966a}.expense-text{color:#dc5a61}.transfer-text{color:#64748b}.mobile-list-head{display:flex;align-items:flex-start;justify-content:space-between;gap:8px;padding:16px;border-bottom:1px solid #edf0f5}.mobile-list-head h2{margin:0;color:#34435b;font-size:16px}.mobile-list-head p{margin:5px 0 0;color:#9aa6b7;font-size:11px}.mobile-add-link{min-height:44px;border:0;background:transparent;color:#2563eb;font-size:12px;font-weight:600;white-space:nowrap}.mobile-transaction-cards{display:grid;gap:8px;padding:10px}.mobile-transaction-card{min-width:0;padding:12px;border:1px solid #e7edf5;border-radius:11px;background:#fff}.mobile-transaction-card.voided{opacity:.58}.mobile-card-top,.mobile-card-main,.mobile-card-meta{display:flex;align-items:center;gap:8px;min-width:0}.mobile-card-top{color:#8d99aa;font-size:10px}.mobile-card-top time{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.mobile-status{margin-left:auto;white-space:nowrap}.mobile-direction{border-radius:99px;padding:5px 8px;font-size:10px;font-weight:600;white-space:nowrap}.income-badge{color:#12845e;background:#e7f8f0}.expense-badge{color:#c84d54;background:#fff0f0}.transfer-badge{color:#526d99;background:#eff4fb}.voided-status{color:#9aa4b2;background:#f1f3f5;border-radius:99px;padding:5px 7px}.mobile-card-main{justify-content:space-between;margin-top:10px}.mobile-card-main strong{min-width:0;color:#4b5b73;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.mobile-card-main b{max-width:48%;font-size:15px;overflow-wrap:anywhere;text-align:right}.mobile-card-meta{margin-top:8px;color:#8d99aa;font-size:10px}.mobile-card-meta span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.mobile-card-meta span+span{margin-left:auto;text-align:right}.mobile-card-notes{margin:8px 0 0;color:#7d8ba0;font-size:11px;line-height:1.5;overflow-wrap:anywhere}.mobile-card-actions{display:flex;justify-content:flex-end;gap:4px;margin-top:6px;border-top:1px solid #edf0f5}.mobile-text-button{min-width:58px;min-height:44px;border:0;background:transparent;color:#2563eb;font-size:12px}.mobile-text-button.danger{color:#d65b62}.mobile-text-button:disabled{color:#b4bdc9}.mobile-state{display:grid;place-content:center;justify-items:center;min-height:230px;padding:28px 16px;text-align:center;color:#8b98aa}.mobile-state p{margin:0 0 14px;font-size:12px;line-height:1.5}.mobile-state h3{margin:10px 0 5px;color:#52617a;font-size:16px}.mobile-empty-icon{font-size:32px}.mobile-error p,.mobile-form-error{color:#b54e58}.mobile-primary,.mobile-outline{min-height:44px;display:inline-flex;align-items:center;justify-content:center;border-radius:8px;padding:9px 15px;font-size:13px;cursor:pointer}.mobile-primary{border:0;background:#2563eb;color:#fff;font-weight:600}.mobile-outline{border:1px solid #d6dfec;background:#fff;color:#52617a}.mobile-spinner{width:18px;height:18px;border:2px solid #dce7f8;border-top-color:#2563eb;border-radius:50%;animation:spin .7s linear infinite;margin-bottom:9px}.mobile-spinner.light{width:14px;height:14px;border-color:#ffffff66;border-top-color:#fff;margin:0 5px 0 0;vertical-align:-2px}@keyframes spin{to{transform:rotate(360deg)}}
.mobile-sheet-backdrop{position:fixed;inset:0;z-index:110;display:flex;align-items:flex-end;padding:8px 8px max(8px,env(safe-area-inset-bottom));background:#10213c66}.mobile-sheet{width:100%;max-height:calc(100dvh - 16px);overflow:auto;border-radius:16px 16px 10px 10px;background:#fff;padding:20px 17px;box-shadow:0 -12px 50px #0c1c3540}.mobile-sheet-head{display:flex;align-items:flex-start;justify-content:space-between;gap:8px}.mobile-sheet-head h2{margin:0;color:#1e2a3d;font-size:19px}.mobile-sheet-head p{margin:5px 0 0;color:#8996a9;font-size:11px}.mobile-close{min-width:44px;min-height:44px;border:0;border-radius:8px;background:transparent;color:#8b98aa;font-size:27px;line-height:1}.mobile-filter-form,.mobile-entry-form{margin-top:12px}.mobile-filter-form label,.mobile-entry-form label{display:block;margin:13px 0;color:#59677d;font-size:13px;line-height:1.35}.mobile-filter-form input,.mobile-filter-form select,.mobile-entry-form input,.mobile-entry-form select,.mobile-entry-form textarea{display:block;width:100%;min-height:44px;margin-top:6px;border:1px solid #dbe2ee;border-radius:8px;padding:9px 10px;color:#44536a;background:#fff;font:inherit;font-size:16px;outline:0}.mobile-entry-form textarea{resize:vertical;line-height:1.45}.mobile-filter-dates{display:grid;grid-template-columns:1fr 1fr;gap:9px}.mobile-filter-dates :deep(input){display:block;width:100%;min-height:44px;margin-top:6px;border:1px solid #dbe2ee;border-radius:8px;padding:9px 10px;color:#44536a;background:#fff;font:inherit;font-size:16px;outline:0}.mobile-filter-dates :deep(input:focus){border-color:#3b82f6}.mobile-direction-toggle{display:grid;grid-template-columns:repeat(3,1fr);gap:5px;padding:4px;border-radius:10px;background:#f1f5fb}.mobile-direction-toggle button{min-height:44px;border:0;border-radius:7px;background:transparent;color:#7c8ba1;font-size:13px}.mobile-direction-toggle button.selected{background:#fff;color:#2563eb;box-shadow:0 1px 5px #263b6114;font-weight:600}.mobile-transfer-hint{margin:0;padding:10px 11px;border:1px solid #dbe6f5;border-radius:9px;background:#f8fbff;color:#596b84;font-size:12px;line-height:1.5}.mobile-sheet-actions{display:flex;gap:8px;margin-top:19px}.mobile-sheet-actions>*{flex:1;min-height:44px}.mobile-form-error{margin-top:12px;padding:10px 12px;border-radius:8px;background:#fff0f0;font-size:12px;line-height:1.5}
.mobile-list-actions{display:flex;align-items:center;gap:4px;flex:0 0 auto}.mobile-add-link{display:inline-flex;align-items:center;justify-content:center;text-decoration:none}.mobile-manual-link{min-height:44px;border:0;background:transparent;color:#7c8ba1;font-size:12px;padding:0 5px}.mobile-empty-actions{display:flex;align-items:center;justify-content:center;gap:8px;flex-wrap:wrap}.mobile-primary{text-decoration:none}.mobile-sheet-head-actions{display:flex;align-items:center;gap:4px;flex:0 0 auto}.mobile-ai-switch{display:inline-flex;align-items:center;min-height:36px;color:#2563eb;font-size:11px;text-decoration:none;white-space:nowrap}
@media(max-width:380px){.mobile-finance-summary strong{font-size:12px}.mobile-finance-summary>div{padding:8px}.mobile-card-main b{font-size:14px}.mobile-sheet{padding-left:14px;padding-right:14px}}
</style>
