<template>
  <AppLayout title="收支记录" :subtitle="subtitle" :notice="notice">
    <template #actions>
      <router-link class="primary add-button" to="/ai">{{ isMobile ? '记一笔' : '＋ 记一笔' }}</router-link>
      <button v-if="!isMobile" class="outline-button manual-button" type="button" @click="openCreate">手动记账</button>
    </template>

    <MobileTransactions v-if="isMobile" :ask="ask" :ask-scope-label="askScopeLabel" :report-question="reportQuestion" :generate-report="generateReport" :open-report="openReport" :ask-ledger="askLedger" :clear-ask="clearAsk" :proposal-label="proposalLabel" :describe-snapshot="describeSnapshot" :apply-proposal="applyProposal" :ignore-proposal="ignoreProposal" :load-conversation="loadConversation" :toggle-history="toggleHistory" :new-conversation="newConversation" :delete-conversation="deleteConversation" :transactions="transactions" :summary="summary" :categories="categories" :visible-categories="visibleCategories" :form-categories="formCategories" :payment-methods="paymentMethods" :form-payment-methods="formPaymentMethods" :partners="partners" :filters="filters" :form="form" :loading="loading" :saving="saving" :error-message="errorMessage" :form-error="formError" :modal-open="modalOpen" :editing="editing" :category-name="categoryName" :payment-method-name="paymentMethodName" :payment-method-option-label="paymentMethodOptionLabel" :transaction-cents="transactionCents" :is-voided="isVoided" :load-transactions="loadTransactions" :reset-filters="resetFilters" :open-create="openCreate" :open-edit="openEdit" :close-modal="closeModal" :save-transaction="saveTransaction" :void-transaction="voidTransaction" />
    <template v-else>

    <section class="filters panel" aria-label="流水筛选">
      <div class="filter-row">
        <label class="filter-field"><span>类型</span><select v-model="filters.direction" @change="loadTransactions"><option value="">全部类型</option><option value="income">收入</option><option value="expense">支出</option><option value="transfer">转账/还款</option></select></label>
        <div class="filter-field date-field"><span>开始日期</span><DateSegmentInput :model-value="filters.from" edge="start" label="开始日期" apply-on="enter" @update:model-value="setDateFilter('from', $event)" /></div>
        <div class="filter-field date-field"><span>结束日期</span><DateSegmentInput :model-value="filters.to" edge="end" label="结束日期" placeholder="如 20261031 / 202610" apply-on="enter" @update:model-value="setDateFilter('to', $event)" /></div>
        <label class="filter-field"><span>分类</span><select v-model="filters.category_id" @change="loadTransactions"><option value="">全部分类</option><option v-for="category in visibleCategories" :key="category.id" :value="category.id">{{ category.name }}</option></select></label>
        <label class="filter-field"><span>资金账户</span><select v-model="filters.payment_method_id" @change="loadTransactions"><option value="">全部账户</option><option v-for="method in paymentMethods" :key="method.id" :value="method.id">{{ paymentMethodOptionLabel(method) }}</option></select></label>
        <label class="filter-field"><span>往来账户</span><select v-model="filters.partner_id" @change="loadTransactions"><option value="">全部账户</option><option v-for="partner in partners" :key="partner.id" :value="partner.id">{{ partner.name }}</option></select></label>
        <button class="clear-button" type="button" @click="resetFilters">重置</button>
        <button class="report-button" type="button" :disabled="ask.loading" :title="reportQuestion" @click="generateReport"><span v-if="ask.reportLoading" class="spinner"></span>{{ ask.reportLoading ? '生成中…' : '生成报告' }}</button>
      </div>
    </section>

    <div v-if="!loading && (!visibleCategories.length || !formPaymentMethods.length)" class="setup-hint">
      <span>ⓘ 记账前需要至少一个收支分类和资金账户。</span>
      <router-link to="/settings">前往设置</router-link>
    </div>

    <section class="summary-row">
      <div class="summary-item"><span>收入</span><strong class="income-text">{{ formatMoney(summary.income) }}</strong></div>
      <div class="summary-item"><span>支出</span><strong class="expense-text">{{ formatMoney(summary.expense) }}</strong></div>
      <div class="summary-item"><span>净收支</span><strong :class="summary.net >= 0 ? 'income-text' : 'expense-text'">{{ summary.net >= 0 ? '+' : '' }}{{ formatMoney(summary.net) }}</strong></div>
      <div class="summary-count">共 {{ transactions.length }} 笔</div>
    </section>

    <section class="table-panel panel">
      <div v-if="loading" class="state"><span class="spinner dark"></span><p>正在加载流水…</p></div>
      <div v-else-if="errorMessage" class="state error-state"><p>{{ errorMessage }}</p><button class="outline-button" type="button" @click="loadTransactions">重试</button></div>
      <div v-else-if="transactions.length === 0" class="state"><div class="empty-icon">📒</div><h3>暂无交易记录</h3><p>调整筛选条件，或开始记录您的第一笔收支吧</p><div class="empty-actions"><router-link class="primary small" to="/ai">＋ 记一笔</router-link><button class="outline-button small" type="button" @click="openCreate">手动记账</button></div></div>
      <template v-else>
        <div class="table-wrap">
          <table>
            <thead><tr><th>发生时间</th><th>类型</th><th>分类</th><th>金额</th><th>资金账户</th><th>往来账户</th><th>备注</th><th>状态</th><th class="action-col">操作</th></tr></thead>
            <tbody>
              <tr v-for="transaction in transactions" :key="transaction.id" :class="{ voided: isVoided(transaction) }">
                <td data-label="发生时间" class="time-cell">{{ formatDateTime(transaction.occurred_at || transaction.occurred_time) }}</td>
                <td data-label="类型"><span class="direction" :class="isTransfer(transaction) ? 'transfer-badge' : transaction.direction === 'income' ? 'income-badge' : 'expense-badge'">{{ isTransfer(transaction) ? '转账' : transaction.direction === 'income' ? '收入' : '支出' }}</span></td>
                <td data-label="分类">{{ categoryName(transaction) }}</td>
                <td data-label="金额" class="amount-cell" :class="isTransfer(transaction) ? 'transfer-text' : transaction.direction === 'income' ? 'income-text' : 'expense-text'">{{ isTransfer(transaction) ? '↔' : transaction.direction === 'income' ? '+' : '−' }}{{ formatMoney(transaction.amount_cents ?? transaction.amount, '') }}</td>
                <td data-label="资金账户">{{ paymentMethodName(transaction) }}</td>
                <td data-label="往来账户">{{ transaction.partner_name || '—' }}</td>
                <td data-label="备注" class="notes-cell" :title="transaction.notes || transaction.note">{{ transaction.notes || transaction.note || '—' }}</td>
                <td data-label="状态"><span class="status" :class="isVoided(transaction) ? 'status-voided' : 'status-normal'">{{ isVoided(transaction) ? '已作废' : '正常' }}</span></td>
                <td data-label="操作" class="actions-cell"><button type="button" class="text-button" :disabled="isVoided(transaction)" @click="openEdit(transaction)">编辑</button><button type="button" class="text-button danger" :disabled="isVoided(transaction)" @click="voidTransaction(transaction)">作废</button></td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </section>

    <Teleport to="body">
      <div v-if="modalOpen" class="modal-backdrop" @click.self="closeModal">
        <section class="modal" role="dialog" aria-modal="true" :aria-labelledby="editing ? 'edit-title' : 'create-title'">
          <div class="modal-header"><div><h2 :id="editing ? 'edit-title' : 'create-title'">{{ editing ? (isTransferForm ? '编辑转账' : '编辑收支') : '手动记账' }}</h2><p>{{ isTransferForm ? '转账/还款只在账户之间移动余额，不计入收入或支出' : '金额以元填写，系统将按分保存' }}</p></div><div class="modal-header-actions"><router-link v-if="!editing" class="manual-ai-link" to="/ai" @click="closeModal">改用 AI</router-link><button class="modal-close" type="button" aria-label="关闭" @click="closeModal">×</button></div></div>
          <div v-if="formError" class="form-error" role="alert">{{ formError }}</div>
          <form class="transaction-form" @submit.prevent="saveTransaction">
            <div class="direction-toggle" role="radiogroup" aria-label="流水类型"><button type="button" :class="{ selected: formType === 'expense' }" @click="setFormType('expense')">支出</button><button type="button" :class="{ selected: formType === 'income' }" @click="setFormType('income')">收入</button><button type="button" :class="{ selected: formType === 'transfer' }" @click="setFormType('transfer')">转账/还款</button></div>
            <p v-if="isTransferForm" class="transfer-hint">来源账户余额减少；转入信用卡、花呗等负债账户时欠款减少，转入现金或投资账户时余额增加。</p>
            <label>金额（元）<input v-model="form.amount" inputmode="decimal" pattern="^[0-9]+([.][0-9]{1,2})?$" placeholder="0.00" required /></label>
            <label>发生时间<input v-model="form.occurred_at" type="datetime-local" required /></label>
            <div class="form-grid">
              <label v-if="!isTransferForm">分类<select v-model="form.category_id" required><option value="" disabled>请选择分类</option><option v-for="category in formCategories" :key="category.id" :value="String(category.id)">{{ category.name }}</option></select></label>
              <label>{{ isTransferForm ? '来源账户' : form.direction === 'income' ? '收款账户' : '支付账户' }}<select v-model="form.payment_method_id" required><option value="" disabled>请选择账户</option><option v-for="method in formPaymentMethods" :key="method.id" :value="String(method.id)">{{ paymentMethodOptionLabel(method) }}</option></select></label>
              <label v-if="isTransferForm">转入/还款账户<select v-model="form.transfer_payment_method_id" required><option value="" disabled>请选择账户</option><option v-for="method in formPaymentMethods" :key="method.id" :value="String(method.id)" :disabled="String(method.id) === String(form.payment_method_id)">{{ paymentMethodOptionLabel(method) }}</option></select></label>
              <label v-else>往来账户（可选）<select v-model="form.partner_id"><option value="">不关联</option><option v-for="partner in partners" :key="partner.id" :value="String(partner.id)">{{ partner.name }}</option></select></label>
            </div>
            <label>备注（可选）<textarea v-model.trim="form.notes" rows="3" maxlength="500" placeholder="补充说明…"></textarea></label>
            <div class="modal-actions"><button class="outline-button" type="button" @click="closeModal">取消</button><button class="primary" type="submit" :disabled="saving"><span v-if="saving" class="spinner"></span>{{ saving ? '保存中…' : (editing ? '保存修改' : isTransferForm ? '确认转账' : '确认入账') }}</button></div>
          </form>
        </section>
      </div>
    </Teleport>

    <section v-if="ask.messages.length || ask.loading" ref="askThread" class="ask-panel panel" aria-label="AI 问答">
      <div class="panel-title"><div><h2>问账</h2><p>AI 自行决定查询范围，可以接着追问；改账方案需要你确认后才执行</p></div><button class="text-button" type="button" @click="newConversation">新对话</button></div>
      <div v-if="ask.messages.length || ask.loading" class="ask-thread" aria-live="polite">
        <div v-for="(message, index) in ask.messages" :key="index" class="ask-message" :class="message.role === 'user' ? 'is-user' : 'is-assistant'">
          <ul v-if="message.steps && message.steps.length" class="ask-steps"><li v-for="(step, stepIndex) in message.steps" :key="stepIndex">{{ step.summary }}<em v-if="step.result"> → {{ step.result }}</em></li></ul>
          <p>{{ message.content }}</p>
          <div v-for="proposal in (message.proposals || [])" :key="proposal.index" class="ask-proposal" :class="`is-${proposal.status}`">
            <div class="ask-proposal-head"><strong>{{ proposalLabel(proposal) }}<span v-if="proposal.transaction_id"> #{{ proposal.transaction_id }}</span></strong><span class="ask-proposal-status">{{ ({ pending: '待确认', applied: '已执行', ignored: '已忽略', failed: '执行失败' })[proposal.status] || proposal.status }}</span></div>
            <p v-if="proposal.before" class="ask-proposal-line"><span>原记录</span>{{ describeSnapshot(proposal.before) }}</p>
            <p v-if="proposal.after" class="ask-proposal-line"><span>{{ proposal.type === 'create' ? '补记为' : '改为' }}</span>{{ describeSnapshot(proposal.after) }}</p>
            <p v-if="proposal.reason" class="ask-proposal-line"><span>原因</span>{{ proposal.reason }}</p>
            <p v-if="proposal.detail" class="ask-proposal-line is-error"><span>说明</span>{{ proposal.detail }}</p>
            <div v-if="proposal.status === 'pending'" class="ask-proposal-actions"><button class="primary" type="button" :disabled="proposal.busy" @click="applyProposal(message, proposal)">{{ proposal.busy ? '执行中…' : '确认执行' }}</button><button class="outline-button" type="button" :disabled="proposal.busy" @click="ignoreProposal(message, proposal)">忽略</button></div>
          </div>
          <small v-if="message.role === 'assistant' && (message.period || message.warning)">{{ [message.period, message.warning].filter(Boolean).join(' · ') }}<button v-if="message.report_id || message.report" type="button" class="ask-report-link" @click="openReport(message)">查看报告卡片 →</button></small>
        </div>
        <div v-if="ask.loading" class="ask-message is-assistant is-live" aria-live="polite">
          <ul v-if="ask.steps.length" class="ask-steps"><li v-for="(step, stepIndex) in ask.steps" :key="stepIndex">{{ step.summary }}<em v-if="step.result"> → {{ step.result }}</em></li></ul>
          <p><span class="spinner dark"></span>{{ ask.stage || '正在思考…' }}</p>
        </div>
      </div>
    </section>

    <section class="ask-composer panel" aria-label="向 AI 查账">
      <form class="ask-form" @submit.prevent="askLedger(ask.text)">
        <label class="sr-only" for="ask-ledger-input">查账问题</label>
        <textarea id="ask-ledger-input" v-model="ask.text" rows="1" maxlength="1000" :disabled="ask.loading" placeholder="问问账本：花了多少？哪类最多？和上月比呢？" @keydown.enter.exact.prevent="askLedger(ask.text)" @input="autoGrow($event.target)"></textarea>
        <button class="chat-send" type="submit" :disabled="ask.loading || !ask.text" :aria-label="ask.loading ? '思考中' : '提问'" :title="ask.loading ? '思考中' : '提问'"><span v-if="ask.loading" class="spinner"></span><span v-else aria-hidden="true">↑</span></button>
      </form>
      <p class="ask-scope"><span v-if="ask.error" class="ask-inline-error" role="alert">{{ ask.error }}</span><span v-else>AI 自行决定查询范围 · Enter 发送 · Shift + Enter 换行 · 报告请用筛选栏的“生成报告”</span><span class="ask-scope-actions"><button type="button" class="text-button" @click="toggleHistory">{{ ask.historyOpen ? '收起历史' : '历史对话' }}</button><button v-if="ask.messages.length" type="button" class="text-button" @click="newConversation">新对话</button></span></p>
      <div v-if="ask.historyOpen" class="ask-history" aria-label="历史对话">
        <p v-if="ask.historyLoading" class="ask-history-empty">正在加载…</p>
        <p v-else-if="!ask.history.length" class="ask-history-empty">还没有历史对话。</p>
        <ul v-else>
          <li v-for="item in ask.history" :key="item.id" :class="{ 'is-current': item.id === ask.conversationId }"><button type="button" class="ask-history-item" @click="loadConversation(item.id)"><strong>{{ item.title }}</strong><small>{{ formatDateTime(item.updated_at) }} · {{ Math.floor(item.message_count / 2) }} 轮</small></button><button type="button" class="text-button danger-text" @click="deleteConversation(item.id)">删除</button></li>
        </ul>
      </div>
    </section>
    </template>
    <ReportPreview :open="reportPreview.open" :report="reportPreview.report" :loading="reportPreview.loading" :mobile="isMobile" @close="reportPreview.open = false" />
    <ConfirmDialog
      :open="confirmDialog.open"
      :eyebrow="confirmDialog.eyebrow"
      :title="confirmDialog.title"
      :message="confirmDialog.message"
      :confirm-label="confirmDialog.confirmLabel"
      :tone="confirmDialog.tone"
      @cancel="resolveConfirm(false)"
      @confirm="resolveConfirm(true)"
    />
  </AppLayout>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import AppLayout from '../components/AppLayout.vue'
import ConfirmDialog from '../components/ConfirmDialog.vue'
import { useViewport } from '../composables/useViewport'
import { useConfirmDialog } from '../composables/useConfirmDialog'
import MobileTransactions from './MobileTransactions.vue'
import { useRoute, useRouter } from 'vue-router'
import { aiApi, amountToCents, ApiError, beijingDateIso, categoriesApi, datetimeLocalToUtcIso, formatDateTime, formatMoney, localDateTimeValue, partnersApi, paymentMethodsApi, transactionsApi, utcNowIso } from '../api'
import { currentMonthRange } from '../dateInput'
import DateSegmentInput from '../components/DateSegmentInput.vue'
import ReportPreview from '../components/ReportPreview.vue'

const transactions = ref([])
const categories = ref([])
const paymentMethods = ref([])
const partners = ref([])
const loading = ref(false)
const saving = ref(false)
const errorMessage = ref('')
const formError = ref('')
const modalOpen = ref(false)
const editing = ref(null)
const notice = ref(null)
const route = useRoute()
const router = useRouter()
// The list opens on the current month; dates accept loose input (20261001,
// 202610, 10-1…) and are normalized to YYYY-MM-DD.
const filters = reactive({ direction: '', ...currentMonthRange(), category_id: '', payment_method_id: '', partner_id: String(route.query.partner_id || '') })
function setDateFilter(key, value) {
  if (filters[key] === value) return
  filters[key] = value
  loadTransactions()
}
const form = reactive({ kind: 'cashflow', direction: 'expense', amount: '', occurred_at: localDateTimeValue(), category_id: '', payment_method_id: '', transfer_payment_method_id: '', partner_id: '', notes: '' })
const { isMobile } = useViewport()
const { confirmDialog, requestConfirm, resolveConfirm } = useConfirmDialog()

const visibleCategories = computed(() => categories.value.filter((category) => category.is_active !== false))
const formPaymentMethods = computed(() => paymentMethods.value.filter((method) => method.is_active !== false))
const formCategories = computed(() => visibleCategories.value.filter((category) => !category.direction || category.direction === form.direction))
const isTransferForm = computed(() => form.kind === 'transfer')
const formType = computed(() => (isTransferForm.value ? 'transfer' : form.direction))
function setFormType(type) {
  if (type === 'transfer') { form.kind = 'transfer'; form.direction = 'expense'; form.category_id = ''; form.partner_id = ''; return }
  form.kind = 'cashflow'; form.direction = type; form.transfer_payment_method_id = ''
}
const subtitle = computed(() => `共 ${transactions.value.length} 笔记录`)

// Questions about the list are answered from aggregated figures within the
// current filters; the AI page only does bookkeeping.
const ask = reactive({ text: '', loading: false, reportLoading: false, follow: false, error: '', messages: [], steps: [], stage: '', conversationId: null, history: [], historyOpen: false, historyLoading: false })
// The report card: figures + the model's text, shown in a preview that can be
// saved as an image.  Older reports are fetched by id when reopened.
const reportPreview = reactive({ open: false, loading: false, report: null })
function reportFromAsk(payload, content) {
  return { content, periodLabel: payload?.period?.label || '', startDate: payload?.period?.start_date || '', endDate: payload?.period?.end_date || '', summary: payload?.summary || null, generatedAt: payload?.generated_at || utcNowIso(), model: payload?.model || '' }
}
function reportFromSaved(saved) {
  const summary = saved?.data_summary && typeof saved.data_summary === 'object' ? saved.data_summary : null
  return { content: saved?.content || '', periodLabel: summary?.period?.label || `${saved?.start_date || ''} 至 ${saved?.end_date || ''}`, startDate: saved?.start_date || '', endDate: saved?.end_date || '', summary, generatedAt: saved?.generated_at || '', model: saved?.model || '' }
}
async function openReport(message) {
  if (message?.report) { reportPreview.report = message.report; reportPreview.open = true; return }
  if (!message?.report_id) return
  reportPreview.report = null; reportPreview.loading = true; reportPreview.open = true
  try {
    message.report = reportFromSaved(await aiApi.report(message.report_id))
    reportPreview.report = message.report
  } catch (error) {
    reportPreview.open = false
    ask.error = error instanceof ApiError ? error.message : '读取报告失败。'
  } finally { reportPreview.loading = false }
}
function generateReport() { return askLedger(reportQuestion.value, 'report') }
const CONVERSATION_KEY = 'pennypilot:ask-conversation'
function proposalLabel(proposal) {
  return ({ update: '修改流水', void: '作废流水', create: '补记一笔' })[proposal?.type] || '修改方案'
}
function describeSnapshot(snapshot) {
  if (!snapshot) return ''
  const amount = Number.isInteger(snapshot.amount_cents) ? formatMoney(snapshot.amount_cents) : ''
  const kind = snapshot.kind === 'transfer' ? `转账 ${snapshot.account || ''} → ${snapshot.to_account || ''}` : `${snapshot.direction === 'income' ? '收入' : '支出'} ${snapshot.account || ''}`
  return [snapshot.occurred_at, kind, amount, snapshot.category, snapshot.partner ? `往来 ${snapshot.partner}` : '', snapshot.notes].filter(Boolean).join(' · ')
}
async function loadConversation(id) {
  if (!id) return
  try {
    const payload = await aiApi.conversation(id)
    ask.follow = false // restoring a thread must not scroll the page
    ask.conversationId = payload.id
    ask.messages = (payload.messages || []).map((item) => ({ id: item.id, role: item.role, content: item.content, steps: item.steps || [], proposals: item.proposals || [], period: item.period || '', warning: item.warning || '', report_id: item.report_id || null }))
    localStorage.setItem(CONVERSATION_KEY, String(payload.id))
    ask.historyOpen = false
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) { ask.conversationId = null; localStorage.removeItem(CONVERSATION_KEY) }
  }
}
async function loadHistory() {
  ask.historyLoading = true
  try { ask.history = await aiApi.conversations(30) } catch { ask.history = [] } finally { ask.historyLoading = false }
}
async function toggleHistory() { ask.historyOpen = !ask.historyOpen; if (ask.historyOpen) await loadHistory() }
function newConversation() { ask.conversationId = null; ask.messages = []; ask.error = ''; ask.steps = []; ask.historyOpen = false; localStorage.removeItem(CONVERSATION_KEY) }
async function deleteConversation(id) {
  if (!await requestConfirm({ eyebrow: 'AI 问答', title: '删除这个对话？', message: '对话记录和其中的修改方案状态会一起删除。', confirmLabel: '删除', tone: 'danger' })) return
  try { await aiApi.deleteConversation(id); ask.history = ask.history.filter((item) => item.id !== id); if (ask.conversationId === id) newConversation() } catch (error) { ask.error = error instanceof ApiError ? error.message : '删除失败。' }
}
async function applyProposal(message, proposal) {
  if (!proposal || proposal.status !== 'pending') return
  proposal.busy = true
  try {
    if (proposal.type === 'update') await transactionsApi.update(proposal.transaction_id, proposal.changes)
    else if (proposal.type === 'void') await transactionsApi.voidTransaction(proposal.transaction_id, proposal.reason || null)
    else if (proposal.type === 'create') await transactionsApi.create(proposal.draft)
    proposal.status = 'applied'
    notice.value = { type: 'success', message: `${proposalLabel(proposal)}已执行。` }
    await Promise.all([loadTransactions(), loadDictionaries()])
  } catch (error) {
    proposal.status = 'failed'; proposal.detail = error instanceof ApiError ? error.message : '执行失败。'
  } finally {
    proposal.busy = false
    if (ask.conversationId && message.id) aiApi.setProposalStatus(ask.conversationId, message.id, proposal.index, proposal.status, proposal.detail || null).catch(() => {})
  }
}
function ignoreProposal(message, proposal) {
  if (!proposal || proposal.status !== 'pending') return
  proposal.status = 'ignored'
  if (ask.conversationId && message.id) aiApi.setProposalStatus(ask.conversationId, message.id, proposal.index, 'ignored').catch(() => {})
}
const ASK_STATUS = { provider_failed: '该通道没有响应，切换到备用通道', local_fallback: 'AI 通道不可用，改用本地汇总回答' }
function handleAskEvent(event) {
  const type = String(event?.type || '')
  if (type === 'provider') ask.stage = `${event.name === 'fallback' ? '备用通道' : '主通道'}${event.model ? ` ${event.model}` : ''} 正在思考…`
  else if (type === 'tool') { ask.steps.push({ summary: event.summary, result: '' }); ask.stage = `查询：${event.summary}` }
  else if (type === 'tool_result') { const step = ask.steps[ask.steps.length - 1]; if (step) step.result = event.summary }
  else if (type === 'status' && ASK_STATUS[event.code]) ask.steps.push({ summary: ASK_STATUS[event.code], result: '' })
}
const askScopeLabel = computed(() => {
  const parts = []
  if (filters.from || filters.to) parts.push(`${filters.from || '最早'} 至 ${filters.to || '今天'}`)
  else parts.push('本月')
  if (filters.payment_method_id) parts.push(paymentMethods.value.find((item) => String(item.id) === String(filters.payment_method_id))?.name || '所选账户')
  if (filters.category_id) parts.push(categories.value.find((item) => String(item.id) === String(filters.category_id))?.name || '所选分类')
  if (filters.partner_id) parts.push(partners.value.find((item) => String(item.id) === String(filters.partner_id))?.name || '所选往来单位')
  if (filters.direction === 'income' || filters.direction === 'expense') parts.push(filters.direction === 'income' ? '仅收入' : '仅支出')
  return parts.join(' · ')
})
// The "report" button turns the current filters into an explicit question;
// everything else is just the user's words, the assistant picks the range.
const reportQuestion = computed(() => {
  const range = filters.from || filters.to ? `${filters.from || '最早记录'} 至 ${filters.to || beijingDateIso()}` : '本月'
  const limits = []
  if (filters.payment_method_id) limits.push(`只看 ${paymentMethods.value.find((item) => String(item.id) === String(filters.payment_method_id))?.name || '所选'} 账户`)
  if (filters.category_id) limits.push(`只看 ${categories.value.find((item) => String(item.id) === String(filters.category_id))?.name || '所选'} 分类`)
  if (filters.partner_id) limits.push(`只看与 ${partners.value.find((item) => String(item.id) === String(filters.partner_id))?.name || '所选往来单位'} 相关的流水`)
  if (filters.direction === 'income' || filters.direction === 'expense') limits.push(filters.direction === 'income' ? '只看收入' : '只看支出')
  return `生成 ${range} 的收支报告${limits.length ? `，${limits.join('，')}` : ''}`
})
async function askLedger(text, intent = 'query') {
  const question = String(text || '').trim()
  if (!question || ask.loading) return
  ask.error = ''; ask.loading = true; ask.follow = true; ask.reportLoading = intent === 'report'; ask.steps = []; ask.stage = '正在连接 AI…'
  ask.messages.push({ role: 'user', content: question })
  if (intent === 'query') { ask.text = ''; nextTick(() => ['ask-ledger-input', 'mobile-ask-input'].forEach((id) => autoGrow(document.getElementById(id)))) }
  try {
    const conversation = ask.conversationId ? [] : ask.messages.slice(0, -1).slice(-8).map(({ role, content }) => ({ role, content }))
    const payload = await aiApi.askStream({ text: question, intent, conversation, reference_time: utcNowIso(), conversation_id: ask.conversationId || undefined }, { onEvent: handleAskEvent })
    const period = intent === 'report' && payload?.period?.label ? payload.period.label : ''
    if (payload?.conversation_id) { ask.conversationId = payload.conversation_id; localStorage.setItem(CONVERSATION_KEY, String(payload.conversation_id)) }
    const content = String(payload?.reply || '').trim() || '没有得到回答。'
    const report = intent === 'report' ? reportFromAsk(payload, content) : null
    ask.messages.push({ id: payload?.message_id || null, role: 'assistant', content, period, warning: payload?.warning || '', report_id: payload?.report_id || null, report, steps: ask.steps.map((step) => ({ ...step })), proposals: (payload?.proposals || []).map((item) => ({ ...item })) })
    if (report) { reportPreview.report = report; reportPreview.loading = false; reportPreview.open = true }
    if (payload?.report_id) notice.value = { type: 'success', message: `${payload?.period?.label || '该周期'}收支报告已生成并保存到财务分析。` }
  } catch (error) {
    ask.messages.pop()
    ask.error = error instanceof ApiError ? error.message : '提问失败，请稍后重试。'
  } finally { ask.loading = false; ask.reportLoading = false; ask.steps = []; ask.stage = '' }
}
function clearAsk() { newConversation() }
// The question box grows with its content up to a few lines.
function autoGrow(element) {
  if (!element) return
  element.style.height = 'auto'
  element.style.height = `${Math.min(element.scrollHeight, 132)}px`
}
const askThread = ref(null)
// Follow the thread only while the user is asking; a thread restored on page
// load stays where it is so the page does not jump down by itself.
watch(() => ask.messages.length + (ask.loading ? 1 : 0), () => {
  if (!ask.follow) return
  nextTick(() => {
    const items = askThread.value?.querySelectorAll('.ask-message')
    items?.[items.length - 1]?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  })
})
const summary = computed(() => {
  const cashflow = transactions.value.filter((item) => !isTransfer(item))
  const income = cashflow.reduce((sum, item) => item.direction === 'income' && !isVoided(item) ? sum + transactionCents(item) : sum, 0)
  const expense = cashflow.reduce((sum, item) => item.direction === 'expense' && !isVoided(item) ? sum + transactionCents(item) : sum, 0)
  return { income, expense, net: income - expense }
})

function transactionCents(item) { return Number(item.amount_cents ?? item.amount ?? 0) || 0 }
function isVoided(item) { return item.status === 'voided' || item.status === 'void' || item.is_voided === true }
function isTransfer(item) { return String(item?.kind || '').toLowerCase() === 'transfer' }
function accountRoleLabel(role) { return ({ cash: '现金', liability: '负债', investment: '投资' })[String(role || 'cash')] || '现金' }
function paymentMethodOptionLabel(method) { return `${method.name}${method.account_role && method.account_role !== 'cash' ? `（${accountRoleLabel(method.account_role)}）` : ''}` }

function normalizeForm(transaction = null) {
  if (!transaction) {
    Object.assign(form, { kind: 'cashflow', direction: 'expense', amount: '', occurred_at: localDateTimeValue(), category_id: '', payment_method_id: '', transfer_payment_method_id: '', partner_id: '', notes: '' })
    return
  }
  Object.assign(form, {
    kind: isTransfer(transaction) ? 'transfer' : 'cashflow', direction: isTransfer(transaction) ? 'expense' : (transaction.direction || 'expense'), amount: (transactionCents(transaction) / 100).toFixed(2),
    occurred_at: localDateTimeValue(transaction.occurred_at || transaction.occurred_time),
    category_id: String(transaction.category_id ?? transaction.category?.id ?? ''), payment_method_id: String(transaction.payment_method_id ?? transaction.payment_method?.id ?? ''), transfer_payment_method_id: String(transaction.transfer_payment_method_id ?? transaction.transfer_payment_method?.id ?? ''), partner_id: String(transaction.partner_id ?? transaction.partner?.id ?? ''),
    notes: transaction.notes ?? transaction.note ?? '',
  })
}

async function loadDictionaries() {
  const [categoryResult, methodResult, partnerResult] = await Promise.allSettled([categoriesApi.list(), paymentMethodsApi.list(), partnersApi.list({ status: 'active' })])
  if (categoryResult.status === 'fulfilled') categories.value = categoryResult.value
  if (methodResult.status === 'fulfilled') paymentMethods.value = methodResult.value
  if (partnerResult.status === 'fulfilled') partners.value = partnerResult.value
  const failure = [categoryResult, methodResult].find((result) => result.status === 'rejected')
  if (failure && !categories.value.length && !paymentMethods.value.length) throw failure.reason
}

async function loadTransactions() {
  loading.value = true; errorMessage.value = ''
  try {
    const { direction, ...rest } = filters
    const typeFilter = direction === 'transfer' ? { kind: 'transfer' } : { direction }
    const rows = await transactionsApi.list({ ...rest, ...typeFilter, include_voided: true, page_size: 100 })
    transactions.value = rows.map((item) => ({
      ...item,
      category_name: item.category_name || item.category?.name || categories.value.find((category) => String(category.id) === String(item.category_id))?.name,
      payment_method_name: item.payment_method_name || item.payment_method?.name || paymentMethods.value.find((method) => String(method.id) === String(item.payment_method_id))?.name,
      transfer_payment_method_name: item.transfer_payment_method_name || item.transfer_payment_method?.name || paymentMethods.value.find((method) => String(method.id) === String(item.transfer_payment_method_id))?.name,
      partner_name: item.partner_name || item.partner?.name || partners.value.find((partner) => String(partner.id) === String(item.partner_id))?.name,
    }))
  }
  catch (error) { errorMessage.value = error instanceof ApiError ? error.message : '流水加载失败。' }
  finally { loading.value = false }
}

function categoryName(transaction) { return isTransfer(transaction) ? (transaction.category_name || '内部转账') : (transaction.category_name || transaction.category?.name || '未分类') }
function paymentMethodName(transaction) {
  const source = transaction.payment_method_name || transaction.payment_method?.name || '—'
  if (!isTransfer(transaction)) return source
  const target = transaction.transfer_payment_method_name || transaction.transfer_payment_method?.name || '—'
  return `${source} → ${target}`
}

function resetFilters() { Object.assign(filters, { direction: '', ...currentMonthRange(), category_id: '', payment_method_id: '', partner_id: '' }); loadTransactions() }
function openCreate() { editing.value = null; formError.value = ''; normalizeForm(); modalOpen.value = true }
function openEdit(transaction) {
  editing.value = transaction; formError.value = ''; normalizeForm(transaction); modalOpen.value = true
}
function closeModal() { if (!saving.value) modalOpen.value = false }
function manualModeRequested(query = route.query) { return String(query?.mode || '').toLowerCase() === 'manual' }
function consumeManualMode() {
  if (!manualModeRequested()) return
  if (!modalOpen.value) openCreate()
  const query = { ...route.query }
  delete query.mode
  delete query.from
  router.replace({ query }).catch(() => {})
}

watch(() => form.direction, (direction) => {
  if (form.category_id && !formCategories.value.some((category) => String(category.id) === String(form.category_id))) form.category_id = ''
  // A category can be direction-neutral; payment method remains valid for both directions.
  void direction
})
watch(() => route.query.mode, consumeManualMode)

async function saveTransaction() {
  formError.value = ''
  const amount_cents = amountToCents(form.amount)
  if (!Number.isInteger(amount_cents) || amount_cents <= 0) { formError.value = '请输入大于 0 且最多两位小数的金额。'; return }
  if (isTransferForm.value) {
    if (!form.payment_method_id || !form.transfer_payment_method_id) { formError.value = '请选择来源账户和转入/还款账户。'; return }
    if (String(form.payment_method_id) === String(form.transfer_payment_method_id)) { formError.value = '来源账户和转入/还款账户不能相同。'; return }
  } else if (!form.category_id || !form.payment_method_id) { formError.value = '请选择分类和资金账户。'; return }
  const occurred_at = datetimeLocalToUtcIso(form.occurred_at)
  if (!occurred_at) { formError.value = '请输入有效的北京时间。'; return }
  saving.value = true
  const data = isTransferForm.value
    ? { kind: 'transfer', direction: 'expense', amount_cents, occurred_at, category_id: null, payment_method_id: Number(form.payment_method_id), transfer_payment_method_id: Number(form.transfer_payment_method_id), partner_id: null, notes: form.notes || null, source: editing.value?.source || 'manual' }
    : { kind: 'cashflow', direction: form.direction, amount_cents, occurred_at, category_id: Number(form.category_id), payment_method_id: Number(form.payment_method_id), transfer_payment_method_id: null, partner_id: form.partner_id ? Number(form.partner_id) : null, notes: form.notes || null, source: editing.value?.source || 'manual' }
  try {
    if (editing.value) await transactionsApi.update(editing.value.id, data)
    else await transactionsApi.create(data)
    modalOpen.value = false
    notice.value = { type: 'success', message: editing.value ? '交易已更新。' : isTransferForm.value ? '转账/还款已记录，账户余额已更新。' : '交易已入账。' }
    await loadTransactions()
  } catch (error) { formError.value = error instanceof ApiError ? error.message : '保存失败，请稍后重试。' }
  finally { saving.value = false }
}

async function voidTransaction(transaction) {
  if (!await requestConfirm({ eyebrow: '现金流水', title: '作废这笔交易？', message: '作废后记录仍会保留，但不会再计入收入、支出和净收支汇总。', confirmLabel: '确认作废' })) return
  try {
    await transactionsApi.voidTransaction(transaction.id)
    notice.value = { type: 'success', message: '交易已作废，原始记录已保留。' }
    await loadTransactions()
  } catch (error) { notice.value = { type: 'error', message: error instanceof ApiError ? error.message : '作废失败。' } }
}

onMounted(() => { loadConversation(Number(localStorage.getItem(CONVERSATION_KEY)) || null) })
onMounted(async () => {
  try { await loadDictionaries() } catch (error) { errorMessage.value = error instanceof ApiError ? error.message : '基础数据加载失败。' }
  await loadTransactions()
  consumeManualMode()
})
</script>

<style scoped>
.ask-panel { margin-top: 14px; padding-bottom: 14px; }.ask-panel .panel-title { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; padding: 16px 18px 12px; border-bottom: 1px solid #edf1f6; }.ask-panel .panel-title h2 { margin: 0; color: #34435b; font-size: 15px; }.ask-panel .panel-title p { margin: 4px 0 0; color: #8a97aa; font-size: 12px; }.ask-panel .panel-title .text-button { flex: 0 0 auto; }.ask-panel .ask-thread { padding: 0 18px; }.ask-composer { position: sticky; bottom: 14px; z-index: 20; margin-top: 14px; padding: 12px 16px 10px; border: 1px solid #d8e6f8; box-shadow: 0 10px 28px #23436d1b; }.ask-form { display: flex; gap: 8px; align-items: center; }.chat-send { display: grid; place-items: center; flex: 0 0 42px; width: 42px; height: 42px; border: 0; border-radius: 50%; background: #2563eb; color: #fff; font-size: 23px; line-height: 1; cursor: pointer; box-shadow: 0 4px 10px #2563eb38; }.chat-send:disabled { opacity: .45; cursor: wait; box-shadow: none; }.chat-send .spinner { margin: 0; }.ask-inline-error { color: #a83232; }.ask-scope { display: flex; justify-content: space-between; align-items: center; gap: 10px; }.ask-scope-actions { display: inline-flex; gap: 10px; flex: 0 0 auto; }.ask-history { margin-top: 10px; max-height: 240px; overflow-y: auto; border-top: 1px solid #edf1f6; padding-top: 8px; }.ask-history ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; }.ask-history li { display: flex; align-items: center; gap: 8px; border-radius: 8px; padding: 2px 6px; }.ask-history li.is-current { background: #eaf2ff; }.ask-history-item { flex: 1; min-width: 0; display: grid; gap: 2px; text-align: left; border: 0; background: transparent; padding: 6px 4px; cursor: pointer; font: inherit; color: #34435b; }.ask-history-item strong { font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.ask-history-item small { color: #8a97aa; font-size: 11px; }.ask-history-empty { margin: 6px 0; color: #8a97aa; font-size: 12px; }.danger-text { color: #c8555d; }.ask-proposal { margin-top: 8px; padding: 10px 12px; border: 1px solid #dbe6f5; border-radius: 10px; background: #fff; color: #52627a; font-size: 12px; }.ask-proposal.is-applied { border-color: #c9ebd9; background: #f3fbf7; }.ask-proposal.is-ignored, .ask-proposal.is-failed { opacity: .8; }.ask-proposal.is-failed { border-color: #f1d0d0; background: #fff6f6; }.ask-proposal-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 6px; color: #34435b; }.ask-proposal-status { padding: 2px 8px; border-radius: 99px; background: #fff4da; color: #8a6924; font-size: 11px; }.ask-proposal.is-applied .ask-proposal-status { background: #e7f8f0; color: #12845e; }.ask-proposal-line { margin: 3px 0; white-space: normal; }.ask-proposal-line span { display: inline-block; min-width: 48px; color: #8a97aa; }.ask-proposal-line.is-error { color: #a83232; }.ask-proposal-actions { display: flex; gap: 8px; margin-top: 8px; }.ask-proposal-actions .primary { padding: 7px 14px; }.ask-form textarea { flex: 1; min-width: 0; min-height: 40px; max-height: 132px; resize: none; border: 1px solid #dbe2ee; border-radius: 8px; padding: 10px 12px; color: #44536a; background: #fbfcff; font: inherit; font-size: 13px; line-height: 1.45; outline: 0; }.ask-form textarea:focus { border-color: #3b82f6; }.ask-form { align-items: flex-end; }.ask-scope { margin: 9px 0 0; color: #8a97aa; font-size: 12px; }.ask-scope .text-button { padding: 0; font-size: 12px; }.ask-thread { display: grid; gap: 8px; margin-top: 12px; }.ask-message { max-width: 92%; padding: 9px 12px; border-radius: 10px; font-size: 13px; line-height: 1.6; }.ask-message p { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }.ask-message small { display: block; margin-top: 5px; color: #8a97aa; font-size: 11px; }.ask-message small a { color: #2563eb; text-decoration: none; font-weight: 600; }.ask-message.is-user { justify-self: end; background: #2563eb; color: #fff; }.ask-message.is-assistant { justify-self: start; background: #f5f8fc; color: #52627a; }.ask-message.is-live p { display: flex; align-items: center; gap: 8px; color: #7c8ba1; }.ask-steps { margin: 0 0 6px; padding: 0; list-style: none; display: grid; gap: 3px; color: #7c8ba1; font-size: 11px; }.ask-steps li::before { content: '✓ '; color: #2563eb; }.ask-steps em { font-style: normal; color: #9aa6b6; }.ask-message .spinner.dark { margin: 0; }.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }@media(max-width: 760px){.ask-form{flex-wrap:wrap}.ask-form input{flex-basis:100%}}
.panel { background: #fff; border-radius: 13px; box-shadow: 0 2px 8px #243b5a0d; }.add-button { margin-top: 1px; white-space: nowrap; text-decoration: none; }.manual-button { white-space: nowrap; }.primary { border: 0; border-radius: 8px; background: #2563eb; color: #fff; padding: 11px 18px; font-size: 13px; font-weight: 600; cursor: pointer; }.primary:hover { background: #1d4ed8; }.primary:disabled { opacity: .65; cursor: wait; }
.filters { margin-top: 28px; padding: 16px 18px; }.filter-row { display: flex; align-items: flex-end; flex-wrap: wrap; gap: 12px; }.filter-field { flex: 1 1 135px; min-width: 120px; margin: 0; }.filter-field > span:first-child { display: block; color: #7c8ba1; font-size: 12px; margin-bottom: 6px; }.filter-field select, .filter-field input { width: 100%; height: 38px; border: 1px solid #dbe2ee; border-radius: 8px; padding: 0 10px; color: #44536a; background: #fff; outline: none; font: inherit; font-size: 13px; }.filter-field select:focus, .filter-field input:focus { border-color: #3b82f6; }.date-field { position: relative; }.date-field :deep(input) { width: 100%; height: 38px; border: 1px solid #dbe2ee; border-radius: 8px; padding: 0 10px; color: #44536a; background: #fff; outline: none; font: inherit; font-size: 13px; }.date-field :deep(input:focus) { border-color: #3b82f6; }.clear-button { height: 38px; border: 0; background: #f1f5fb; color: #64748b; border-radius: 8px; padding: 0 15px; cursor: pointer; font-size: 13px; }.clear-button:hover { color: #2563eb; }.report-button { display: inline-flex; align-items: center; gap: 6px; height: 38px; border: 1px solid #c9dbf7; background: #eaf2ff; color: #2563eb; border-radius: 8px; padding: 0 15px; cursor: pointer; font: inherit; font-size: 13px; font-weight: 600; white-space: nowrap; }.report-button:hover { background: #dce9fe; }.report-button:disabled { opacity: .6; cursor: wait; }.report-button .spinner { margin: 0; width: 13px; height: 13px; border-color: #bfd4f7; border-top-color: #2563eb; }.ask-report-link { border: 0; background: transparent; padding: 0; margin-left: 4px; color: #2563eb; font: inherit; font-size: 11px; font-weight: 600; cursor: pointer; }
.setup-hint { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 13px; padding: 10px 14px; border-radius: 9px; background: #fff8e7; color: #8a6924; font-size: 12px; }.setup-hint a { color: #2563eb; text-decoration: none; font-weight: 600; white-space: nowrap; }
.summary-row { display: flex; align-items: center; gap: 30px; padding: 20px 2px 16px; }.summary-item { display: flex; align-items: baseline; gap: 9px; }.summary-item span { color: #8996a9; font-size: 12px; }.summary-item strong { font-size: 16px; }.summary-count { margin-left: auto; color: #8996a9; font-size: 12px; }.income-text { color: #12966a; }.expense-text { color: #dc5a61; }.transfer-text { color: #64748b; }
.table-panel { overflow: hidden; min-height: 330px; }.table-wrap { overflow-x: auto; }table { width: 100%; border-collapse: collapse; min-width: 900px; }th { background: #fafbfd; color: #8996a9; font-size: 11px; font-weight: 600; text-align: left; padding: 13px 18px; white-space: nowrap; }td { border-top: 1px solid #edf0f5; color: #516078; font-size: 13px; padding: 15px 18px; vertical-align: middle; }tr:hover td { background: #fcfdff; }.time-cell { color: #77869b; white-space: nowrap; }.amount-cell { font-weight: 700; white-space: nowrap; }.notes-cell { max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.direction, .status { display: inline-flex; align-items: center; border-radius: 99px; padding: 4px 8px; font-size: 11px; white-space: nowrap; }.income-badge { color: #12845e; background: #e7f8f0; }.expense-badge { color: #c84d54; background: #fff0f0; }.transfer-badge { color: #526d99; background: #eff4fb; }.status-normal { color: #4f6c91; background: #eff4fb; }.status-voided { color: #9aa4b2; background: #f1f3f5; }.voided td { color: #a3acb8; }.actions-cell { white-space: nowrap; }.text-button { border: 0; background: transparent; padding: 3px 5px; color: #2563eb; font-size: 12px; cursor: pointer; }.text-button.danger { color: #d65b62; }.text-button:disabled { color: #b4bdc9; cursor: not-allowed; }.action-col { width: 105px; }
.state { min-height: 330px; display: grid; place-content: center; justify-items: center; text-align: center; color: #8b98aa; padding: 30px; }.state h3 { color: #52617a; margin: 14px 0 6px; font-size: 16px; }.state p { margin: 0 0 17px; font-size: 13px; }.empty-icon { font-size: 34px; }.empty-actions { display: flex; align-items: center; justify-content: center; gap: 9px; flex-wrap: wrap; }.error-state p { color: #ba4b53; }.outline-button { border: 1px solid #d6dfec; border-radius: 8px; background: #fff; color: #52617a; padding: 9px 16px; cursor: pointer; font-size: 13px; }.outline-button:hover { border-color: #3b82f6; color: #2563eb; }.outline-button.small, .primary.small { min-height: 40px; }.spinner { width: 18px; height: 18px; border: 2px solid #dce7f8; border-top-color: #2563eb; border-radius: 50%; animation: spin .7s linear infinite; }.spinner.dark { margin-bottom: 10px; }
.modal-backdrop { position: fixed; inset: 0; z-index: 100; display: grid; place-items: center; padding: 18px; background: #10213c66; }.modal { width: min(550px, 100%); max-height: min(760px, calc(100vh - 36px)); overflow: auto; background: #fff; border-radius: 16px; box-shadow: 0 24px 80px #0c1c3560; padding: 26px; }.modal-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }.modal-header h2 { margin: 0; color: #1e2a3d; font-size: 21px; }.modal-header p { color: #8996a9; margin: 6px 0 0; font-size: 12px; }.modal-header-actions { display: flex; align-items: center; gap: 8px; }.manual-ai-link { display: inline-flex; align-items: center; min-height: 36px; color: #2563eb; font-size: 12px; text-decoration: none; white-space: nowrap; }.modal-close { border: 0; background: transparent; color: #8b98aa; font-size: 26px; line-height: 1; cursor: pointer; }.form-error { margin-top: 17px; color: #a83232; background: #fff0f0; border-radius: 8px; padding: 10px 12px; font-size: 13px; }.transaction-form { margin-top: 17px; }.direction-toggle { display: grid; grid-template-columns: repeat(3, 1fr); gap: 5px; padding: 4px; border-radius: 10px; background: #f1f5fb; margin-bottom: 3px; }.direction-toggle button { border: 0; border-radius: 7px; background: transparent; color: #7c8ba1; padding: 9px; cursor: pointer; font-size: 13px; }.direction-toggle button.selected { background: #fff; color: #2563eb; box-shadow: 0 1px 5px #263b6114; font-weight: 600; }.transfer-hint { margin: 0 0 4px; padding: 10px 11px; border: 1px solid #dbe6f5; border-radius: 8px; background: #f8fbff; color: #596b84; font-size: 12px; line-height: 1.5; }.transaction-form label { display: block; color: #59677d; font-size: 13px; margin: 15px 0; }.transaction-form input, .transaction-form select, .transaction-form textarea { display: block; width: 100%; margin-top: 7px; border: 1px solid #dbe2ee; border-radius: 8px; padding: 10px 11px; color: #44536a; background: #fff; font: inherit; font-size: 13px; outline: none; }.transaction-form input:focus, .transaction-form select:focus, .transaction-form textarea:focus { border-color: #3b82f6; }.transaction-form textarea { resize: vertical; }.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 13px; }.modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 22px; }.modal-actions .primary { min-width: 110px; }.modal-actions .spinner { display: inline-block; width: 14px; height: 14px; border-color: #ffffff66; border-top-color: #fff; vertical-align: -2px; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 700px) { .summary-row { gap: 15px; flex-wrap: wrap; }.summary-count { width: 100%; margin-left: 0; }.filters { margin-top: 20px; }.filter-field { flex-basis: calc(50% - 6px); }.table-panel { border-radius: 10px; } }
@media (max-width: 540px) { .add-button { padding: 9px 11px; font-size: 12px; }.filter-field { flex-basis: 100%; }.modal { padding: 21px 17px; }.form-grid { grid-template-columns: 1fr; gap: 0; } }
@media (max-width: 760px) { table, thead, tbody, th, td, tr { display: block; } table { min-width: 0; }.table-wrap { padding: 5px 14px; }thead { display: none; }tbody tr { padding: 13px 0; border-top: 1px solid #edf0f5; }tbody tr:first-child { border-top: 0; }td { display: flex; justify-content: space-between; align-items: baseline; gap: 15px; border: 0; padding: 6px 2px; text-align: right; }td::before { content: attr(data-label); color: #9aa6b7; font-size: 11px; text-align: left; }td.notes-cell { max-width: none; white-space: normal; }td.actions-cell { justify-content: flex-end; }.action-col { width: auto; } }
/* Mobile interaction layer: filters use a predictable two-column rhythm,
   transaction rows read as cards, and the entry form behaves like a bottom
   sheet on phones. */
@media(max-width:700px){
  .filters{margin-top:20px;padding:13px 14px;overflow:hidden}.filter-row{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.filter-field{min-width:0;flex:none}.filter-field > span:first-child{font-size:11px;margin-bottom:5px}.filter-field select,.filter-field input{width:100%;min-width:0;min-height:44px;height:44px;font-size:16px;padding-left:9px;padding-right:7px}.filter-field:first-child,.filter-field:nth-child(4),.filter-field:nth-child(5),.filter-field:nth-child(6){grid-column:1/-1}.clear-button,.report-button{min-height:44px;height:44px;padding:0 12px}.setup-hint{align-items:flex-start;flex-direction:column;gap:8px;margin-top:12px;line-height:1.5}.setup-hint a{min-height:44px;display:inline-flex;align-items:center}
  .summary-row{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;padding:14px 0 12px}.summary-item{min-width:0;min-height:44px;display:flex;flex-direction:column;align-items:flex-start;justify-content:center;gap:3px;padding:7px 8px;border:1px solid #e8eef7;border-radius:8px;background:#fff}.summary-item span{font-size:10px}.summary-item strong{font-size:13px;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.summary-count{grid-column:1/-1;width:auto;margin:0;text-align:right;padding-right:2px}
  .table-panel{border-radius:10px}.table-wrap{padding:5px 12px;overflow:visible}.table-wrap table,.table-wrap thead,.table-wrap tbody,.table-wrap tr,.table-wrap th,.table-wrap td{display:block}.table-wrap table{min-width:0}.table-wrap thead{display:none}.table-wrap tbody{display:grid;gap:8px}.table-wrap tbody tr{padding:8px 10px;border:1px solid #e7edf5;border-radius:10px;background:#fff}.table-wrap tbody tr:first-child{border-top:1px solid #e7edf5}.table-wrap td{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;min-height:44px;padding:7px 0;border:0;border-top:1px solid #edf0f5;text-align:right;white-space:normal;overflow-wrap:anywhere}.table-wrap td:first-child{border-top:0}.table-wrap td::before{content:attr(data-label);flex:0 0 auto;color:#9aa6b7;font-size:10px;text-align:left}.table-wrap td>*{max-width:68%;overflow-wrap:anywhere}.table-wrap .time-cell{white-space:normal}.table-wrap .notes-cell{max-width:none;white-space:normal;text-overflow:clip;overflow:visible}.table-wrap .actions-cell{justify-content:flex-end;align-items:center}.table-wrap .actions-cell::before{margin-right:auto}.text-button{min-width:64px;min-height:44px;padding:8px 10px;display:inline-flex;align-items:center;justify-content:center;font-size:12px}.state{padding:26px 16px}.state .primary,.state .outline-button{min-height:44px}
  .modal-backdrop{align-items:end;padding:8px 8px max(8px,env(safe-area-inset-bottom))}.modal{width:100%;max-height:calc(100dvh - 16px);border-radius:16px 16px 10px 10px;padding:21px 17px;overflow:auto}.modal-header{gap:8px}.modal-header h2{font-size:18px;line-height:1.35}.modal-header p{line-height:1.45}.modal-close{min-width:44px;min-height:44px;padding:8px}.transaction-form{margin-top:13px}.transaction-form label{margin:14px 0;line-height:1.35}.transaction-form input,.transaction-form select{min-height:44px;height:44px;font-size:16px}.transaction-form textarea{font-size:16px;line-height:1.45}.direction-toggle{min-height:52px}.direction-toggle button{min-height:44px;padding:9px}.form-grid{grid-template-columns:1fr;gap:0}.modal-actions{gap:8px}.modal-actions>*{min-height:44px;flex:1}.modal-actions .primary{min-width:0}
  :deep(.header-actions){gap:5px;max-width:48vw;flex-wrap:wrap;justify-content:flex-end}.add-button{min-height:44px;padding:10px 12px}
}
@media(max-width:430px){.filter-row{grid-template-columns:1fr}.filter-field{grid-column:1/-1!important}.summary-row{grid-template-columns:1fr 1fr}.summary-item:nth-child(3){grid-column:1/-1}.summary-item strong{font-size:12px}.table-wrap{padding-left:9px;padding-right:9px}.table-wrap td>*{max-width:64%}}
</style>
