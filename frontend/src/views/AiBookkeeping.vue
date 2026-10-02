<template>
  <AppLayout :title="pageTitle" :subtitle="pageSubtitle" :notice="notice">
    <MobileAiBookkeeping
      v-if="isMobile"
      v-model:prompt="prompt"
      :conversation="conversation"
      :parsing="parsing"
      :confirming="confirming"
      :ai-unavailable="aiUnavailable"
      :retry-status="retryStatus"
      :parsing-label="parsingLabel"
      :request-error="requestError"
      :draft-visible="draftVisible"
      :draft-ready="draftReady"
      :draft="draft"
      :partner-ledger="partnerLedger"
      :brief-comment="briefComment"
      :warning="parseWarning"
      :parse-source="parseSource"
      :parse-warning="parseWarning"
      :confirm-error="confirmError"
      :available-categories="availableCategories"
      :payment-methods="paymentMethods"
      :partners="partners"
      :history="history"
      :history-loading="historyLoading"
      :history-error="historyError"
      :mode="mode"
      :page-title="pageTitle"
      :selected-partner="selectedPartner"
      :selected-partner-id="selectedPartnerId"
      :partner-balance="partnerBalance"
      :partner-entry-rows="partnerEntryRows"
      :partner-current-balance="partnerCurrentBalance"
      :partner-intent="partnerIntent"
      :combined-visible="combinedVisible"
      :combined-enabled="combinedEnabled"
      :partner-ledger-options="partnerLedgerOptions"
      :partner-balance-options="partnerBalanceOptions"
      :sync-category-direction="syncCategoryDirection"
      :add-partner-row="addPartnerRow"
      :remove-partner-row="removePartnerRow"
      :submit-prompt="submitPrompt"
      :reset-conversation="resetConversation"
      :confirm-draft="confirmDraft"
      :load-history="loadHistory"
      :partner-ledger-label="partnerLedgerLabel"
    />

    <template v-else>
    <section class="ai-chat-header panel">
      <div class="compose-modebar">
        <div class="compose-mode-current"><span class="compose-mode-icon" aria-hidden="true">{{ isPartnerMode ? '↔' : isCombinedMode ? '✦' : '●' }}</span><div><strong>{{ isPartnerMode ? 'AI 已识别为未结算余额' : isCombinedMode ? 'AI 会同时整理现金与未结算余额' : 'AI 已识别为现金收支' }}</strong><span>不用选择模式，一句话里包含的变化会自动分账</span></div></div>
      </div>
      <div class="section-heading"><div class="ai-badge">{{ isPartnerMode ? '↔' : '✦' }}</div><div><h2>说一句话，记账、查收支、要报告都可以</h2><p>AI 会自动判断这是现金收支、往来余额变化，还是两者同时发生；也可以直接问本月、本年或全部的收支情况，或让它生成收支报告。记账在确认前不会写入账本。</p></div></div>
      <div class="ai-flow" aria-label="AI 记账流程"><span class="ai-flow-step is-active"><b>1</b>描述</span><i aria-hidden="true">→</i><span class="ai-flow-step"><b>2</b>AI 整理</span><i aria-hidden="true">→</i><span class="ai-flow-step"><b>3</b>一次确认</span></div>
      <div v-if="parseSourceLabel || parseWarning" class="parse-result-meta" role="status" aria-live="polite">
        <span v-if="parseSourceLabel" class="parse-source-badge" :class="{ 'is-fallback': isFallbackParse }"><i aria-hidden="true"></i>{{ parseSourceLabel }}</span>
        <span v-if="parseWarning" class="parse-warning-text">{{ parseWarning }}</span>
      </div>
      <div v-if="requestError" class="request-error" :class="`is-${requestError.kind}`" role="alert">
        <strong>{{ requestError.title }}</strong>
        <span>{{ requestError.message }}</span>
        <small v-if="requestError.attempts">已自动重试 {{ requestError.attempts }} 次，仍未成功。</small>
        <router-link v-if="requestError.kind === 'ai_unavailable' || requestError.kind === 'ai_error'" :to="{ path: '/transactions', query: { mode: 'manual', from: 'ai' } }">需要时使用手动流水表单</router-link>
      </div>
      <div v-if="isPartnerMode && selectedPartner" class="mode-context-note"><strong>{{ selectedPartner.name }}</strong><span>{{ selectedPartner.type === 'customer' ? '客户' : '供应商' }} · 当前{{ partnerBalanceKindLabel(partnerBalance.kind) }} {{ formatMoney(partnerCurrentBalance) }}</span></div>
    </section>

    <section v-if="conversation.length" class="conversation panel">
      <div class="panel-title"><div><h2>对话</h2><p>继续补充即可，确认前不会写入账本</p></div><button class="text-button" type="button" title="清空本轮对话和已解析草稿" @click="resetConversation">清空对话与草稿</button></div>
      <div ref="conversationThread" class="messages" aria-live="polite"><div v-for="(message, index) in conversation" :key="`${index}-${message.content}`" class="message" :class="[message.role === 'user' ? 'user-message' : 'assistant-message', { 'chat-message': message.kind === 'chat' }]"><span class="message-avatar">{{ message.role === 'user' ? '我' : '✦' }}</span><div class="message-bubble"><p>{{ message.content }}</p><router-link v-if="message.report_id" class="message-link" :to="{ path: '/reports', query: { report: message.report_id } }">报告已保存，在财务分析中查看 →</router-link></div></div><div v-if="parsing" class="message assistant-message parsing-message"><span class="message-avatar">✦</span><p><span class="typing-dots" aria-hidden="true"><i></i><i></i><i></i></span>{{ retryStatus || parsingLabel }} <span aria-hidden="true">↓</span></p></div></div>
    </section>

    <section v-if="draftVisible" class="confirm-card panel" :class="{ 'partner-confirm-card': isPartnerMode, 'combined-confirm-card': combinedVisible }">
      <div class="panel-title"><div><h2>{{ isPartnerMode ? '确认未结算余额' : isTransferDraft ? '确认账户转账/还款' : combinedVisible ? '确认现金与未结算余额' : '确认现金入账' }}</h2><p>{{ isPartnerMode ? '只确认当前未结算余额，不会产生现金流水' : isTransferDraft ? '只移动账户余额，不计入收入或支出。' : combinedVisible ? '以下两部分会在同一事务中确认' : '请核对后点击确认，AI 不会在确认前写入现金账' }}</p></div><span class="draft-status">待确认</span></div>
      <p class="draft-progress" :class="{ ready: draftReady }" role="status">{{ draftReady ? (isPartnerMode ? '信息已齐全，可以确认未结算余额。' : isTransferDraft ? '信息已齐全，可以确认转账/还款。' : '信息已齐全，可以确认入账。') : `还需补充：${draftMissingFields.join('、')}` }}</p>
      <form class="draft-form" @submit.prevent="confirmDraft">
        <template v-if="isPartnerMode">
          <div class="partner-mode-summary" v-if="partnerCurrent"><span class="partner-mode-avatar">{{ partnerCurrent.type === 'customer' ? '客' : '供' }}</span><div><strong>{{ partnerCurrent.name }}</strong><small>{{ partnerCurrent.type === 'customer' ? '客户' : '供应商' }}往来账户</small></div><span class="partner-balance-chip">系统记录 {{ formatMoney(partnerCurrentBalance) }}</span></div>
          <label class="partner-select-label" v-else>往来账户<select v-model="draft.partner_id"><option value="" disabled>请选择账户</option><option v-for="item in partners" :key="item.id" :value="String(item.id)">{{ item.name }}</option></select></label>
          <div class="partner-entry-list">
            <article v-for="(row, index) in partnerEntryRows" :key="row._key || index" class="partner-entry-row">
              <div class="partner-entry-head"><span class="partner-entry-icon" aria-hidden="true">↔</span><div><strong>核对未结算余额</strong><span>只记录往来余额，不产生现金收支</span></div><em>{{ partnerLedgerLabel(row.entry_type) }}</em></div>
              <div class="partner-balance-comparison">
                <div class="partner-balance-side is-current"><span>系统当前记录</span><strong>{{ formatMoney(partnerCurrentBalance) }}</strong><small>确认前保持不变</small></div>
                <span class="partner-balance-arrow" aria-hidden="true">→</span>
                <label class="partner-balance-side is-target"><span>本次确认余额（元）</span><input v-model.trim="row.balance_after" inputmode="decimal" pattern="^[0-9]*([.][0-9]{0,2})?$" required placeholder="例如：12000" /><small>来自你的描述，可以手动修正</small></label>
              </div>
              <div class="partner-detail-grid"><label>发生时间<input v-model="row.occurred_at" type="datetime-local" required /></label><label>备注（可选）<textarea v-model.trim="row.notes" rows="1" maxlength="500" placeholder="例如：8 月对账余额"></textarea></label></div>
              <p class="partner-entry-preview"><span aria-hidden="true">✓</span>{{ partnerBalancePreview(row) }}</p>
            </article>
          </div>
          <p class="partner-mode-hint"><span aria-hidden="true">i</span><span>余额相同会留下一条核对记录；余额不同时，可选择是否同步调整系统账面余额。</span></p>
          <label v-if="partnerEntryRows[0]?.balance_after" class="reconciliation-toggle"><input v-model="partnerBalance.apply_reconciliation" type="checkbox" /><span><strong>同步校准账面余额</strong><small>开启后，系统会按差额生成一条可追溯的余额校准流水。</small></span></label>
        </template>
        <template v-else>
          <div v-if="!isTransferDraft" class="draft-direction"><button type="button" :class="{ selected: draft.direction === 'expense' }" @click="draft.direction = 'expense'">现金流出</button><button type="button" :class="{ selected: draft.direction === 'income' }" @click="draft.direction = 'income'">现金流入</button></div>
          <p v-else class="transfer-hint">这笔会按内部转账处理：来源账户余额减少；目标为负债账户时欠款减少，目标为现金/投资账户时余额增加。</p>
          <div class="draft-grid"><label>金额（元）<input v-model.trim="draft.amount" inputmode="decimal" pattern="^[0-9]+([.][0-9]{1,2})?$" required /></label><label>发生时间<input v-model="draft.occurred_at" type="datetime-local" required /></label><label v-if="!isTransferDraft">分类<select v-model="draft.category_id" required @change="syncCategoryDirection"><option value="" disabled>请选择分类</option><option v-for="item in availableCategories" :key="item.id" :value="String(item.id)">{{ item.name }}</option></select></label><label>{{ isTransferDraft ? '来源账户' : draft.direction === 'income' ? '收款账户' : '支付账户' }}<select v-model="draft.payment_method_id" required><option value="" disabled>请选择账户</option><option v-for="item in paymentMethods" :key="item.id" :value="String(item.id)">{{ paymentMethodOptionLabel(item) }}</option></select></label><label v-if="isTransferDraft">转入/还款账户<select v-model="draft.transfer_payment_method_id" required><option value="" disabled>请选择账户</option><option v-for="item in paymentMethods" :key="item.id" :value="String(item.id)">{{ paymentMethodOptionLabel(item) }}</option></select></label><label v-else>关联客户/供应商（仅标签）<select v-model="draft.partner_id"><option value="">不关联</option><option v-for="item in partners" :key="item.id" :value="String(item.id)">{{ item.name }}</option></select></label><label>备注<textarea v-model.trim="draft.notes" rows="1" maxlength="500"></textarea></label></div>
          <div v-if="combinedVisible" class="partner-ledger-confirm combined-ledger-panel">
            <div class="combined-ledger-head"><span class="combined-ledger-icon" aria-hidden="true">↔</span><div><strong>记录未结算余额</strong><span>AI 已识别，将与现金流水一次确认</span></div><em>同一笔记录</em></div>
            <div class="combined-ledger-summary"><div><small>往来账户</small><strong>{{ draft.partner_id ? (partners.find((item) => String(item.id) === String(draft.partner_id))?.name || draftNames.partner || '待选择') : (draftNames.partner || '待选择') }}</strong></div><div><small>当前未结算余额</small><strong>{{ Number.isInteger(partnerBalance.after_cents) ? formatMoney(partnerBalance.after_cents) : '待补充' }}</strong></div><div><small>AI 识别</small><strong>{{ partnerLedger.type ? partnerLedgerLabel(partnerLedger.type) : '未设置' }}</strong></div></div>
            <div class="combined-ledger-fields"><label>当前未结算余额（元）<input v-model.trim="partnerBalance.after_text" inputmode="decimal" placeholder="例如：12000" @input="partnerBalance.after_cents = amountToCents($event.target.value)" /></label></div>
            <p class="combined-ledger-hint">填写当前未结算余额即可，系统会自动核对这次变化。</p>
            <p v-if="!draft.partner_id" class="combined-ledger-hint">请选择客户/供应商，确认时会同时写入往来流水。</p>
          </div>
        </template>
        <div v-if="confirmError" class="form-error" role="alert">{{ confirmError }}</div>
        <div class="confirm-actions"><button class="outline-button" type="button" title="清空本轮对话和已解析草稿" @click="resetConversation" :disabled="confirming">清空对话与草稿</button><button class="primary" type="submit" :disabled="confirming || !draftReady"><span v-if="confirming" class="spinner"></span>{{ confirming ? '确认中…' : isPartnerMode ? '确认未结算余额' : isTransferDraft ? '确认转账/还款' : combinedVisible ? '确认现金 + 往来' : '确认现金入账' }}</button></div>
      </form>
    </section>

    <section class="chat-composer panel">
      <form class="prompt-form" @submit.prevent="submitPrompt">
        <label class="sr-only" for="desktop-ai-prompt-input">记账描述</label>
        <textarea id="desktop-ai-prompt-input" ref="promptInput" v-model.trim="prompt" :disabled="parsing || confirming" rows="1" maxlength="1000" placeholder="描述一笔收支或往来…" @keydown.enter.exact.prevent="submitPrompt"></textarea>
        <div class="quick-prompts" aria-label="常用描述示例">
          <span>快速开始</span>
          <button v-for="example in quickPrompts" :key="example.label" type="button" :disabled="parsing || confirming" @click="useQuickPrompt(example.text)">{{ example.label }}</button>
        </div>
        <div class="prompt-foot"><span aria-live="polite">{{ parsing ? (retryStatus || 'AI 正在处理…') : conversation.length ? '继续补充记录，或直接提问收支情况' : 'Enter 发送 · Shift + Enter 换行' }}</span><button class="chat-send" type="submit" :disabled="!prompt || parsing || confirming" :aria-label="parsing ? '解析中' : '发送'" :title="parsing ? '解析中' : '发送'"><span v-if="parsing" class="spinner"></span><span v-else aria-hidden="true">↑</span></button></div>
      </form>
    </section>

    <section class="history panel">
      <div class="panel-title"><div><h2>AI 操作历史</h2><p>解析记录在本轮对话中保留，分析报告可在此回看</p></div><button class="text-button" type="button" @click="loadHistory">刷新</button></div>
      <div v-if="historyLoading" class="history-state"><span class="spinner dark"></span><p>正在加载…</p></div>
      <div v-else-if="historyError" class="history-state error-state"><p>{{ historyError }}</p></div>
      <div v-else-if="!history.length" class="history-state"><p>还没有 AI 记账记录。</p></div>
      <ul v-else class="history-list"><li v-for="item in history" :key="item.id || item.created_at || item.request_text"><div class="history-icon">✦</div><div class="history-content"><strong>{{ historyTitle(item) }}</strong><span>{{ formatDateTime(item.created_at || item.generated_at || item.updated_at) }}</span><p>{{ historySummary(item) }}</p></div><span class="history-status" :class="historyStatusClass(item)">{{ historyStatus(item) }}</span></li></ul>
    </section>
    </template>
  </AppLayout>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import AppLayout from '../components/AppLayout.vue'
import { useViewport } from '../composables/useViewport'
import MobileAiBookkeeping from './MobileAiBookkeeping.vue'
import { useRoute } from 'vue-router'
import { aiApi, amountToCents, ApiError, categoriesApi, datetimeLocalToUtcIso, formatDateTime, formatMoney, localDateTimeValue, partnersApi, paymentMethodsApi, transactionsApi, utcNowIso } from '../api'

const { isMobile } = useViewport()
const route = useRoute()

// The page has one conversation.  The parser always receives a combined
// proposal request and the resolved proposal mode is inferred from the
// returned fields (cash, partner-only, or both).  Keeping this state separate
// from the URL removes the old mode-switch interaction while preserving the
// partner confirmation card when the AI identifies a virtual-account change.
const resolvedMode = ref('combined')
const mode = computed(() => resolvedMode.value)
const isPartnerMode = computed(() => resolvedMode.value === 'partner')
const isCombinedMode = computed(() => resolvedMode.value === 'combined')
const selectedPartnerId = computed(() => String(route.query.partner_id || ''))
const selectedPartner = computed(() => partners.value.find((item) => String(item.id) === selectedPartnerId.value) || null)
const pageTitle = computed(() => 'AI 记账')
const pageSubtitle = computed(() => selectedPartner.value ? `${selectedPartner.value.name} · AI 会自动判断现金与往来变化` : '一句话描述现金、往来或两者，AI 自动分账后一次确认')

const prompt = ref('')
const conversation = ref([])
const conversationId = ref(null)
const draft = reactive({ kind: 'cashflow', direction: 'expense', amount: '', occurred_at: localDateTimeValue(), category_id: '', payment_method_id: '', transfer_payment_method_id: '', partner_id: '', notes: '' })
const draftNames = reactive({ category: '', method: '', partner: '' })
const partnerLedger = reactive({ type: '', amount_cents: null, amount_text: '', enabled: false })
const partnerBalance = reactive({
  after_cents: null,
  after_text: '',
  kind: 'prepaid_balance',
  expected_cents: null,
  delta_cents: null,
  apply_reconciliation: false,
})
const partnerActions = ref([])
const partnerEntryRows = ref([])
const partnerIntent = ref('')
const parsing = ref(false)
const confirming = ref(false)
const confirmError = ref('')
const parseSource = ref('')
const parseWarning = ref('')
const briefComment = ref('')
const reviewHint = '请向下滑动查看并核对本轮结果。'
const aiUnavailable = ref(false)
const retryStatus = ref('')
const parsingLabel = ref('正在整理这笔记录，完成后向下核对')
const requestError = ref(null)
const notice = ref(null)
const categories = ref([])
const paymentMethods = ref([])
const partners = ref([])
const history = ref([])
const historyLoading = ref(false)
const historyError = ref('')
const promptInput = ref(null)
const conversationThread = ref(null)
const quickPrompts = [
  { label: '记录一笔支出', text: '今天午餐花了 35 元，微信支付' },
  { label: '收到一笔款项', text: '今天收到客户货款 3500 元，微信到账' },
  { label: '现金 + 往来', text: '支付宝扫了 1000 元给供应商王先生，供应商网站现在余额 760 元' },
  { label: '记录余额', text: '客户王先生目前未结算余额 12000 元' },
  { label: '本月收支', text: '本月收支情况怎么样？' },
  { label: '本年收支', text: '今年收入和支出各是多少？' },
  { label: '生成月报', text: '生成本月收支报告' },
]

const availableCategories = computed(() => categories.value.filter((item) => item.is_active !== false && (!item.direction || !['income', 'expense'].includes(draft.direction) || item.direction === draft.direction)))
const isTransferDraft = computed(() => String(draft.kind || '').toLowerCase() === 'transfer')
const partnerPromptExamples = quickPrompts.map((item) => item.text)
const partnerCurrent = computed(() => selectedPartner.value || partners.value.find((item) => String(item.id) === String(draft.partner_id)) || null)
const partnerCurrentType = computed(() => String(partnerCurrent.value?.type || '').toLowerCase())
const PARTNER_LEDGER_OPTIONS = {
  customer: [
    { value: 'prepaid_in', label: '预存充值' },
    { value: 'credit_repay', label: '授信还款' },
    { value: 'limit_adjust', label: '额度调整' },
    { value: 'refund', label: '退款' },
    { value: 'balance_check', label: '未结算余额' },
  ],
  supplier: [
    { value: 'prepaid_in', label: '预存充值' },
    { value: 'credit_use', label: '授信付款' },
    { value: 'balance_check', label: '未结算余额' },
  ],
  default: [
    { value: 'prepaid_in', label: '预存充值' },
    { value: 'credit_repay', label: '授信还款' },
    { value: 'credit_use', label: '授信付款' },
    { value: 'limit_adjust', label: '额度调整' },
    { value: 'refund', label: '退款' },
    { value: 'balance_check', label: '未结算余额' },
  ],
}
const PARTNER_BALANCE_OPTIONS = {
  customer: [
    { value: 'prepaid_balance', label: '预存余额' },
    { value: 'credit_limit', label: '授信额度' },
    { value: 'credit_used', label: '欠款' },
    { value: 'credit_remaining', label: '可用额度' },
  ],
  supplier: [
    { value: 'prepaid_balance', label: '预存余额' },
    { value: 'credit_used', label: '欠款' },
  ],
  default: [
    { value: 'prepaid_balance', label: '预存余额' },
    { value: 'credit_limit', label: '授信额度' },
    { value: 'credit_used', label: '欠款' },
    { value: 'credit_remaining', label: '可用额度' },
  ],
}
function ledgerOptionsForPartnerType(partnerType) { return PARTNER_LEDGER_OPTIONS[partnerType] || PARTNER_LEDGER_OPTIONS.default }
function balanceOptionsForPartnerType(partnerType) { return PARTNER_BALANCE_OPTIONS[partnerType] || PARTNER_BALANCE_OPTIONS.default }
function defaultLedgerTypeForPartnerType(partnerType) { return ledgerOptionsForPartnerType(partnerType)[0]?.value || 'prepaid_in' }
function defaultBalanceKindForPartnerType(partnerType) { return partnerType === 'customer' ? 'credit_remaining' : 'prepaid_balance' }
function suggestedBalanceKind(entryType, partnerType, fallback = '') {
  if (entryType === 'prepaid_in' || entryType === 'refund') return 'prepaid_balance'
  if (entryType === 'credit_use' || entryType === 'credit_repay') return 'credit_used'
  if (entryType === 'limit_adjust') return 'credit_limit'
  return fallback || defaultBalanceKindForPartnerType(partnerType)
}
function partnerEntryDeltaSign(entryType) {
  if (entryType === 'credit_repay' || entryType === 'refund' || entryType === 'prepaid_out') return -1
  return 1
}
const partnerLedgerOptions = computed(() => ledgerOptionsForPartnerType(partnerCurrentType.value))
const partnerBalanceOptions = computed(() => balanceOptionsForPartnerType(partnerCurrentType.value))
const partnerCurrentBalance = computed(() => {
  const partner = partnerCurrent.value
  if (!partner) return 0
  const kind = String(partnerBalance.kind || 'prepaid_balance')
  if (kind === 'credit_limit') return Number(partner.credit_limit_cents || 0)
  if (kind === 'credit_used') return Number(partner.credit_used_cents || 0)
  if (kind === 'credit_remaining' || kind === 'available_credit') return Number(partner.credit_remaining_cents ?? ((partner.credit_limit_cents || 0) - (partner.credit_used_cents || 0)))
  return Number(partner.prepaid_balance_cents || 0)
})
const cashDraftVisible = computed(() => conversation.value.length > 0 && (Boolean(draft.amount) || Boolean(draft.category_id) || Boolean(draft.payment_method_id) || Boolean(draft.transfer_payment_method_id) || Boolean(draft.partner_id) || isTransferDraft.value))
const partnerDraftVisible = computed(() => conversation.value.length > 0 && (Boolean(draft.partner_id || selectedPartnerId.value) || partnerEntryRows.value.some((row) => row.amount || row.balance_after || row.entry_type)))
const draftVisible = computed(() => isPartnerMode.value ? partnerDraftVisible.value : cashDraftVisible.value)
const cashDraftReady = computed(() => {
  const amount = amountToCents(draft.amount)
  if (!(Number.isInteger(amount) && amount > 0) || !draft.payment_method_id || !['income', 'expense'].includes(draft.direction)) return false
  if (isTransferDraft.value) return Boolean(draft.transfer_payment_method_id) && String(draft.transfer_payment_method_id) !== String(draft.payment_method_id)
  return Boolean(draft.category_id)
})
const partnerDraftReady = computed(() => {
  const partnerId = draft.partner_id || selectedPartnerId.value || draftNames.partner
  if (!partnerId || !partnerEntryRows.value.length) return false
  return partnerEntryRows.value.every((row) => {
    const amount = signedAmountToCents(row.amount, row.entry_type === 'limit_adjust')
    const after = signedAmountToCents(row.balance_after, false)
    return Boolean(row.entry_type) && (Number.isInteger(amount) && amount !== 0 || Number.isInteger(after)) && Boolean(datetimeLocalToUtcIso(row.occurred_at))
  })
})
const combinedDraftReady = computed(() => {
  if (!combinedVisible.value) return true
  const partnerId = draft.partner_id || selectedPartnerId.value || draftNames.partner
  return Boolean(partnerId && partnerLedger.type && Number.isInteger(partnerBalance.after_cents))
})
const draftReady = computed(() => isPartnerMode.value ? partnerDraftReady.value : cashDraftReady.value && combinedDraftReady.value)
// Only show the current-account section when a real partner ledger action was
// parsed.  The page starts in a neutral unified state; that state alone must
// never turn an ordinary cash draft into a disabled “现金 + 往来” form.
const combinedVisible = computed(() => !isPartnerMode.value && !isTransferDraft.value && Boolean(partnerLedger.type && (draft.partner_id || selectedPartnerId.value || draftNames.partner)))
const combinedEnabled = computed(() => combinedVisible.value && Boolean(partnerLedger.type && (draft.partner_id || selectedPartnerId.value || draftNames.partner)))
const normalizedParseSource = computed(() => String(parseSource.value || '').trim().toLowerCase())
const isFallbackParse = computed(() => normalizedParseSource.value === 'fallback')
const parseSourceLabel = computed(() => {
  if (normalizedParseSource.value === 'model') return 'AI 模型解析'
  if (isFallbackParse.value) return '本地规则解析'
  return ''
})
const draftMissingFields = computed(() => {
  if (isPartnerMode.value) {
    const missing = []
    if (!draft.partner_id && !selectedPartnerId.value && !draftNames.partner) missing.push('往来账户')
    partnerEntryRows.value.forEach((row, index) => {
      if (!(Number.isInteger(signedAmountToCents(row.amount, row.entry_type === 'limit_adjust')) && signedAmountToCents(row.amount, row.entry_type === 'limit_adjust') !== 0) && !Number.isInteger(signedAmountToCents(row.balance_after))) missing.push(`第 ${index + 1} 条金额或盘点余额`)
      if (!datetimeLocalToUtcIso(row.occurred_at)) missing.push(`第 ${index + 1} 条时间`)
    })
    return missing
  }
  const missing = []
  if (!(Number.isInteger(amountToCents(draft.amount)) && amountToCents(draft.amount) > 0)) missing.push('金额')
  if (!['income', 'expense'].includes(draft.direction)) missing.push('收支方向')
  if (!draft.payment_method_id) missing.push(isTransferDraft.value ? '来源账户' : draft.direction === 'income' ? '收款账户' : '支付账户')
  if (isTransferDraft.value) {
    if (!draft.transfer_payment_method_id) missing.push('转入/还款账户')
    if (draft.transfer_payment_method_id && String(draft.transfer_payment_method_id) === String(draft.payment_method_id)) missing.push('不同的目标账户')
    return missing
  }
  if (!draft.category_id) missing.push('分类')
  if (combinedVisible.value) {
    if (!draft.partner_id && !selectedPartnerId.value && !draftNames.partner) missing.push('往来账户')
    if (!partnerLedger.type) missing.push('往来识别结果')
    if (!Number.isInteger(partnerBalance.after_cents)) missing.push('当前未结算余额')
  }
  return missing
})

function useQuickPrompt(text) {
  prompt.value = text
  nextTick(() => promptInput.value?.focus())
}

function scrollLatestUserMessageIntoView() {
  nextTick(() => {
    const messages = conversationThread.value?.querySelectorAll('.user-message')
    const target = messages?.[messages.length - 1]
    if (!target) return
    const reduceMotion = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    const top = target.getBoundingClientRect().top + window.scrollY - 20
    window.scrollTo({ top: Math.max(0, top), behavior: reduceMotion ? 'auto' : 'smooth' })
  })
}

watch(() => conversation.value.length, () => {
  if (conversation.value.some((message) => message.role === 'user')) scrollLatestUserMessageIntoView()
})

function syncCategoryDirection(event) {
  const category = categories.value.find((item) => String(item.id) === String(event?.target?.value || draft.category_id))
  if (category?.direction && ['income', 'expense'].includes(category.direction)) draft.direction = category.direction
}

function firstObject(...values) { return values.find((value) => value && typeof value === 'object' && !Array.isArray(value)) || {} }
function responseDraft(payload) { return firstObject(payload?.parsed, payload?.draft, payload?.transaction, payload?.result?.parsed, payload?.result, payload?.data?.parsed, payload?.data?.draft, payload?.data) }
function responseStatus(payload) { const status = String(payload?.status || payload?.state || '').toLowerCase(); if (status) return status; return payload?.follow_up_question || payload?.question ? 'need_more_info' : 'complete' }
function responseQuestion(payload) { return payload?.follow_up_question || payload?.question || payload?.message || payload?.detail || '' }
function responseBriefComment(payload) { return String(payload?.brief_comment || payload?.comment || payload?.result?.brief_comment || '').trim().replace(/^AI\s*简评\s*[:：]\s*/i, '') }
function centsValue(raw) { if (raw === undefined || raw === null || raw === '') return NaN; const number = Number(raw); return Number.isFinite(number) ? Math.trunc(number) : amountToCents(raw) }
function signedAmountToCents(raw, allowNegative = false) {
  const text = String(raw ?? '').trim()
  if (!text) return NaN
  if (allowNegative && text.startsWith('-')) {
    const value = amountToCents(text.slice(1))
    return Number.isInteger(value) ? -value : NaN
  }
  return amountToCents(text)
}
function field(raw, ...keys) { for (const key of keys) if (raw?.[key] !== undefined && raw?.[key] !== null && raw?.[key] !== '') return raw[key]; return '' }
function normalizeName(value) { return String(value || '').trim().toLowerCase().replace(/\s+/g, '') }
function amountTextFromCents(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return ''
  return String(number / 100)
}
function resolveId(value, name, items) {
  if (value !== undefined && value !== null && value !== '') return String(value)
  const needle = normalizeName(name)
  if (!needle) return ''
  const exact = items.find((item) => normalizeName(item.name) === needle)
  if (exact) return String(exact.id)
  const partial = items.find((item) => {
    const candidate = normalizeName(item.name)
    return candidate.includes(needle) || needle.includes(candidate)
  })
  return partial ? String(partial.id) : ''
}
function accountRoleLabel(role) { return ({ cash: '现金', liability: '负债', investment: '投资' })[String(role || 'cash')] || '现金' }
function paymentMethodOptionLabel(method) { return `${method.name}${method.account_role && method.account_role !== 'cash' ? `（${accountRoleLabel(method.account_role)}）` : ''}` }
function partnerLedgerLabel(type) {
  const partnerType = partnerCurrentType.value
  const normalized = String(type || '').toLowerCase()
  if (normalized === 'credit_use' && partnerType === 'supplier') return '授信付款'
  return ({ prepaid_in: '预存充值', prepaid_out: '预存扣款', credit_use: '授信使用', credit_repay: '授信还款', limit_adjust: '额度调整', refund: '退款', balance_check: '未结算余额' })[normalized] || '往来变动'
}
function partnerBalanceKindLabel(kind) { return '未结算余额' }
function partnerBalanceFieldLabel(kind) { return '当前未结算余额' }
function partnerBalancePreview(row) {
  const after = signedAmountToCents(row?.balance_after)
  if (!Number.isInteger(after)) return '请补充当前未结算余额后再确认'
  const delta = after - partnerCurrentBalance.value
  if (delta === 0) return '与系统当前记录一致，本次只留存余额核对记录'
  return `与系统当前记录相差 ${delta > 0 ? '+' : '−'}${formatMoney(Math.abs(delta))}`
}
function makePartnerRow(seed = {}) {
  const occurred = String(seed.occurred_at || '').trim()
  const occurredValue = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?$/.test(occurred) && !/[zZ]|[+-]\d{2}:?\d{2}$/.test(occurred)
    ? occurred.slice(0, 16)
    : (seed.occurred_at ? localDateTimeValue(seed.occurred_at) : localDateTimeValue())
  return {
    entry_type: seed.entry_type || defaultLedgerTypeForPartnerType(partnerCurrentType.value),
    amount: seed.amount !== undefined && seed.amount !== null ? String(seed.amount) : '',
    balance_after: seed.balance_after !== undefined && seed.balance_after !== null ? String(seed.balance_after) : '',
    occurred_at: occurredValue,
    notes: seed.notes || '',
    balance_kind: seed.balance_kind || suggestedBalanceKind(seed.entry_type, partnerCurrentType.value, defaultBalanceKindForPartnerType(partnerCurrentType.value)),
  }
}
function rawPartnerActions(payload, raw = {}) {
  const value = payload?.partner_actions || payload?.partner_action || raw?.partner_actions || raw?.partner_action || raw?.actions || raw?.entries || []
  if (Array.isArray(value)) return value
  return value && typeof value === 'object' ? [value] : []
}
function ledgerTypeFromRaw(raw, fallback = '') {
  return field(raw, 'entry_type', 'partner_ledger_type', 'ledger_type', 'type', 'action') || fallback
}
function normalizePartnerAction(action, fallback = {}) {
  const source = firstObject(action, fallback)
  const type = ledgerTypeFromRaw(source, fallback.entry_type || defaultLedgerTypeForPartnerType(partnerCurrentType.value))
  const amountRaw = field(source, 'amount_cents', 'partner_ledger_amount_cents', 'delta_cents', 'change_cents', 'amount')
  const afterRaw = field(source, 'balance_after_cents', 'partner_balance_after_cents', 'observed_balance_cents', 'after_balance_cents', 'balance_after', 'observed_balance')
  const kind = field(source, 'balance_kind', 'observed_balance_kind', 'partner_balance_kind', 'kind') || suggestedBalanceKind(type, partnerCurrentType.value, partnerBalance.kind || defaultBalanceKindForPartnerType(partnerCurrentType.value))
  return makePartnerRow({ entry_type: type, amount: amountRaw === '' ? '' : amountTextFromCents(amountRaw), balance_after: afterRaw === '' ? '' : amountTextFromCents(afterRaw), occurred_at: field(source, 'occurred_at', 'occurred_time', 'happened_at'), notes: field(source, 'notes', 'note'), balance_kind: kind })
}
function modeFromPayload(payload) { return String(payload?.mode || payload?.result?.mode || '').toLowerCase() }
function inferredProposalMode(raw) {
  const ledgerType = ledgerTypeFromRaw(raw, '')
  const hasCashFields = Boolean(
    field(raw, 'direction', 'payment_method_id', 'payment_method_name', 'category_id', 'category_name', 'transfer_payment_method_id', 'transfer_payment_method_name')
    || String(field(raw, 'kind', 'transaction_kind')).toLowerCase() === 'transfer'
  )
  if (ledgerType && !hasCashFields) return 'partner'
  if (ledgerType && hasCashFields) return 'combined'
  return 'cash'
}
function applyDraft(raw) {
  const amountCents = field(raw, 'amount_cents', 'cents')
  const amount = amountCents !== '' ? (Number(amountCents) / 100).toFixed(2) : field(raw, 'amount', 'value')
  const rawDirection = raw && Object.prototype.hasOwnProperty.call(raw, 'direction') ? raw.direction : ''
  const categoryName = field(raw, 'category_name', 'category')
  const methodName = field(raw, 'payment_method_name', 'payment_method', 'method')
  const transferMethodName = field(raw, 'transfer_payment_method_name', 'target_payment_method_name', 'target_payment_method', 'to_payment_method')
  const partnerName = field(raw, 'partner_name', 'partner')
  const resolvedPartnerId = resolveId(field(raw, 'partner_id'), partnerName, partners.value) || selectedPartnerId.value
  const hasNotes = Object.prototype.hasOwnProperty.call(raw || {}, 'notes') || Object.prototype.hasOwnProperty.call(raw || {}, 'note')
  Object.assign(draft, {
    kind: field(raw, 'kind', 'transaction_kind') || 'cashflow', direction: rawDirection === null ? null : (rawDirection || 'expense'), amount: String(amount || ''),
    occurred_at: raw.occurred_at || raw.occurred_time || raw.happened_at ? localDateTimeValue(raw.occurred_at || raw.occurred_time || raw.happened_at) : draft.occurred_at || localDateTimeValue(),
    category_id: resolveId(field(raw, 'category_id'), categoryName, categories.value), payment_method_id: resolveId(field(raw, 'payment_method_id'), methodName, paymentMethods.value), transfer_payment_method_id: resolveId(field(raw, 'transfer_payment_method_id', 'target_payment_method_id', 'to_payment_method_id'), transferMethodName, paymentMethods.value), partner_id: resolvedPartnerId, notes: hasNotes ? String(raw.notes ?? raw.note ?? '') : (draft.notes || ''),
  })
  if (draft.kind === 'transfer') { draft.direction = 'expense'; draft.category_id = ''; draft.partner_id = ''; partnerLedger.enabled = false }
  Object.assign(draftNames, { category: categoryName, method: methodName, partner: partnerName })
  const primaryPartnerAction = rawPartnerActions(raw?.__payload || raw, raw)[0] || firstObject(raw?.partner_action, raw?.__payload?.partner_action)
  const hasLedgerType = ['partner_ledger_type', 'ledger_type', 'entry_type'].some((key) => Object.prototype.hasOwnProperty.call(raw || {}, key))
  const ledgerType = field(raw, 'partner_ledger_type', 'ledger_type', 'entry_type') || field(primaryPartnerAction, 'partner_ledger_type', 'ledger_type', 'entry_type') || (hasLedgerType ? '' : partnerLedger.type)
  const ledgerAmount = field(raw, 'partner_ledger_amount_cents', 'ledger_amount_cents', 'delta_cents', 'amount_cents', 'amount') || field(primaryPartnerAction, 'partner_ledger_amount_cents', 'ledger_amount_cents', 'delta_cents', 'amount_cents', 'amount') || partnerLedger.amount_cents || null
  // A partner selector in cash mode is only a label.  The explicit combined
  // action is opt-in in the confirmation card; ordinary supplier/customer
  // mentions can therefore never mutate a virtual balance by accident.
  Object.assign(partnerLedger, { type: ledgerType, amount_cents: ledgerAmount, amount_text: ledgerAmount === null || ledgerAmount === '' ? '' : amountTextFromCents(ledgerAmount), enabled: false })

  const payloadLike = raw?.__payload || raw
  const observed = field(payloadLike, 'partner_balance_after_cents', 'observed_balance_cents', 'balance_after_cents', 'observed_balance', 'balance_after')
  const expected = field(payloadLike, 'expected_balance_cents', 'partner_expected_balance_cents')
  const delta = field(payloadLike, 'balance_delta_cents', 'partner_balance_delta_cents', 'delta_cents')
  const observedKind = field(payloadLike, 'partner_balance_kind', 'observed_balance_kind', 'balance_kind', 'kind') || (ledgerType === 'credit_use' || ledgerType === 'credit_repay' ? 'credit_used' : partnerBalance.kind)
  Object.assign(partnerBalance, {
    after_cents: observed === '' ? null : Number(observed),
    after_text: observed === '' ? '' : amountTextFromCents(observed),
    expected_cents: expected === '' ? null : Number(expected),
    delta_cents: delta === '' ? null : Number(delta),
    kind: observedKind || 'prepaid_balance',
  })
}
function resetPartnerRows() {
  partnerEntryRows.value = [makePartnerRow({
    entry_type: defaultLedgerTypeForPartnerType(partnerCurrentType.value),
    balance_kind: suggestedBalanceKind(defaultLedgerTypeForPartnerType(partnerCurrentType.value), partnerCurrentType.value, partnerBalance.kind || defaultBalanceKindForPartnerType(partnerCurrentType.value)),
  })]
}
function applyPartnerPayload(payload, raw) {
  const actions = rawPartnerActions(payload, raw)
  const fallbackType = ledgerTypeFromRaw(raw, partnerLedger.type || (isPartnerMode.value ? defaultLedgerTypeForPartnerType(partnerCurrentType.value) : ''))
  const fallback = {
    entry_type: fallbackType,
    amount_cents: field(raw, 'partner_ledger_amount_cents', 'ledger_amount_cents', 'amount_cents', 'amount', 'delta_cents'),
    balance_after_cents: field(payload, 'partner_balance_after_cents', 'observed_balance_cents', 'balance_after_cents', 'observed_balance'),
    balance_kind: field(payload, 'partner_balance_kind', 'observed_balance_kind', 'balance_kind', 'kind'),
    occurred_at: field(raw, 'occurred_at', 'occurred_time', 'happened_at'),
    notes: field(raw, 'notes', 'note'),
  }
  const rows = actions.length ? actions.map((item) => normalizePartnerAction(item, fallback)) : [normalizePartnerAction(fallback)]
  // Do not manufacture a blank row from an empty legacy cash draft.  A blank
  // partner mode still gets one editable row so the user can type a balance.
  // The current confirmation contract accepts one partner draft.  Keep the
  // UI's movement + observed-balance pair in one card until the backend
  // exposes an atomic batch endpoint; never silently submit only part of a
  // model-proposed list.
  partnerEntryRows.value = rows.length ? [rows[0]] : [makePartnerRow()]
  const first = rows[0] || {}
  Object.assign(partnerBalance, {
    after_cents: field(payload, 'partner_balance_after_cents', 'observed_balance_cents', 'balance_after_cents', 'observed_balance') === '' ? null : Number(field(payload, 'partner_balance_after_cents', 'observed_balance_cents', 'balance_after_cents', 'observed_balance')),
    after_text: field(payload, 'partner_balance_after_cents', 'observed_balance_cents', 'balance_after_cents', 'observed_balance') === '' ? '' : amountTextFromCents(field(payload, 'partner_balance_after_cents', 'observed_balance_cents', 'balance_after_cents', 'observed_balance')),
    expected_cents: field(payload, 'expected_balance_cents', 'partner_expected_balance_cents') === '' ? null : Number(field(payload, 'expected_balance_cents', 'partner_expected_balance_cents')),
    delta_cents: field(payload, 'balance_delta_cents', 'partner_balance_delta_cents', 'delta_cents') === '' ? null : Number(field(payload, 'balance_delta_cents', 'partner_balance_delta_cents', 'delta_cents')),
    kind: field(payload, 'partner_balance_kind', 'observed_balance_kind', 'balance_kind') || first.balance_kind || 'prepaid_balance',
  })
}
function normalizePartnerSelections() {
  const allowedLedger = new Set(partnerLedgerOptions.value.map((item) => item.value))
  const allowedBalance = new Set(partnerBalanceOptions.value.map((item) => item.value))
  if (partnerLedger.type && !allowedLedger.has(partnerLedger.type)) partnerLedger.type = defaultLedgerTypeForPartnerType(partnerCurrentType.value)
  if (partnerLedger.type === 'balance_check') {
    partnerLedger.amount_cents = 0
    partnerLedger.amount_text = '0'
  }
  if (!allowedBalance.has(partnerBalance.kind)) partnerBalance.kind = suggestedBalanceKind(partnerLedger.type, partnerCurrentType.value, defaultBalanceKindForPartnerType(partnerCurrentType.value))
  partnerEntryRows.value.forEach((row) => {
    if (!allowedLedger.has(row.entry_type)) row.entry_type = defaultLedgerTypeForPartnerType(partnerCurrentType.value)
    if (!allowedBalance.has(row.balance_kind)) row.balance_kind = suggestedBalanceKind(row.entry_type, partnerCurrentType.value, defaultBalanceKindForPartnerType(partnerCurrentType.value))
  })
}
function addPartnerRow() {
  // Kept as a no-op compatibility hook for the mobile/desktop components;
  // batch entry is intentionally disabled until the API supports one atomic
  // request containing multiple partner movements.
}
function removePartnerRow(index) {
  if (partnerEntryRows.value.length <= 1) return
  partnerEntryRows.value.splice(index, 1)
}
function endpointMissing(error) { return error instanceof ApiError && [404, 405, 501].includes(error.status) }

function errorPresentation(error) {
  const kind = error instanceof ApiError ? error.kind : 'unknown'
  const labels = {
    backend_unreachable: '后端服务连接失败',
    backend_error: '后端服务异常',
    timeout: '请求响应超时',
    ai_unavailable: 'AI 服务暂时不可用',
    ai_error: 'AI 服务处理失败',
    rate_limited: '请求过于频繁',
    business_error: '请求未能处理',
  }
  const normalizedKind = labels[kind] ? kind : 'backend_error'
  return {
    kind: normalizedKind,
    title: labels[normalizedKind],
    message: error instanceof ApiError ? error.message : '请求未能完成，请稍后重试。',
    attempts: error instanceof ApiError ? Math.max(0, Number(error.attempts || 1) - 1) : 0,
  }
}

function retryProgress({ error, nextAttempt, maxRetries }) {
  const labels = {
    backend_unreachable: '后端暂时无法连接',
    backend_error: '后端服务异常',
    timeout: '请求响应超时',
    ai_unavailable: 'AI 服务暂时不可用',
    ai_error: 'AI 服务处理失败',
    rate_limited: '请求过于频繁',
  }
  const label = labels[error?.kind] || '请求失败'
  retryStatus.value = `${label}，正在自动重试（${nextAttempt}/${maxRetries + 1}）…`
}

function pushReviewBubbles(...contents) {
  conversation.value.push({ role: 'assistant', content: reviewHint })
  contents.filter((content) => String(content || '').trim()).forEach((content) => {
    conversation.value.push({ role: 'assistant', content: String(content).trim() })
  })
}

async function answerLedgerQuestion(text, priorMessages, reference_time, requestOptions) {
  const chatContext = priorMessages.filter((message) => message.kind === 'chat').slice(-12).map(({ role, content }) => ({ role, content }))
  let payload
  try {
    payload = await aiApi.chat({ text, conversation: chatContext, reference_time }, requestOptions)
  } catch (error) {
    // An older backend without the assistant route simply parses as before.
    if (endpointMissing(error)) return false
    throw error
  }
  const intent = String(payload?.intent || 'bookkeeping').toLowerCase()
  if (intent === 'bookkeeping' || !payload?.reply) return false
  const userMessage = conversation.value[conversation.value.length - 1]
  if (userMessage?.role === 'user') userMessage.kind = 'chat'
  parseSource.value = String(payload?.source || '')
  parseWarning.value = String(payload?.warning || '')
  conversation.value.push({ role: 'assistant', content: String(payload.reply).trim(), kind: 'chat', report_id: payload?.report_id || null, period: payload?.period || null })
  if (payload?.report_id) {
    notice.value = { type: 'success', message: `${payload?.period?.label || '该周期'}收支报告已生成并保存到财务分析。` }
    await loadHistory()
  }
  return true
}

async function submitPrompt() {
  const text = prompt.value.trim(); if (!text) return
  parsing.value = true; aiUnavailable.value = false; retryStatus.value = ''; requestError.value = null; confirmError.value = ''; parseSource.value = ''; parseWarning.value = ''
  conversation.value.push({ role: 'user', content: text }); prompt.value = ''
  try {
    const priorMessages = conversation.value.slice(0, -1)
    const reference_time = utcNowIso()
    const requestOptions = { onRetry: retryProgress }
    // Ask the ledger assistant first.  A question or report request is
    // answered from aggregated data; a bookkeeping sentence comes back as
    // ``intent: bookkeeping`` and continues with the strict parse flow below.
    parsingLabel.value = '正在查看账本数据…'
    const handled = await answerLedgerQuestion(text, priorMessages, reference_time, requestOptions)
    if (handled) return
    parsingLabel.value = '正在整理这笔记录，完成后向下核对'
    // Earlier Q&A turns are not part of the transaction being described.
    const priorConversation = priorMessages.filter((message) => message.kind !== 'chat').slice(-12).map(({ role, content }) => ({ role, content }))
    // Always ask for a unified proposal.  If the returned fields contain only
    // a virtual-account movement, transparently re-run the same sentence in
    // partner mode so the existing partner confirmation contract can be used.
    let payload = await aiApi.parseMode('combined', { text, conversation: priorConversation, reference_time }, requestOptions)
    let raw = responseDraft(payload)
    let proposalMode = inferredProposalMode(raw)
    if (proposalMode === 'partner') {
      const partnerPayload = await aiApi.parseMode('partner', { text, conversation: priorConversation, reference_time }, requestOptions)
      const partnerRaw = responseDraft(partnerPayload)
      if (Object.keys(partnerRaw).length && (ledgerTypeFromRaw(partnerRaw, '') || field(partnerRaw, 'partner_id', 'partner_name'))) {
        payload = partnerPayload
        raw = partnerRaw
      }
    }
    conversationId.value = payload?.conversation_id || payload?.id || conversationId.value
    parseSource.value = String(payload?.source || '')
    parseWarning.value = String(payload?.warning || '')
    briefComment.value = responseBriefComment(payload)
    if (Object.keys(raw).length) applyDraft({ ...raw, __payload: payload })
    proposalMode = inferredProposalMode(raw)
    resolvedMode.value = proposalMode
    partnerActions.value = rawPartnerActions(payload, raw)
    const declaredMode = modeFromPayload(payload)
    const actionObject = firstObject(payload?.cash_action, payload?.partner_action, raw?.cash_action)
    partnerIntent.value = String(raw?.partner_ledger_type || payload?.partner_action || payload?.cash_action?.type || declaredMode || '').toLowerCase()
    const explicitCombined = proposalMode === 'combined' || declaredMode === 'combined' || Boolean(payload?.cash_action && (typeof payload.cash_action === 'object' || String(payload.cash_action).toLowerCase() === 'combined'))
    partnerLedger.enabled = Boolean(explicitCombined && partnerLedger.type && (draft.partner_id || selectedPartnerId.value))
    if (actionObject && typeof actionObject === 'object') {
      const actionType = ledgerTypeFromRaw(actionObject, partnerLedger.type)
      if (actionType) partnerLedger.type = actionType
      const actionAmount = field(actionObject, 'amount_cents', 'partner_ledger_amount_cents', 'delta_cents', 'amount')
      if (actionAmount !== '') partnerLedger.amount_cents = Number(actionAmount)
    }
    if (isPartnerMode.value) applyPartnerPayload(payload, raw)
    const status = responseStatus(payload)
    // A legacy parser may report missing cash-only fields for a partner
    // sentence.  They are irrelevant in partner mode; the partner draft card
    // performs its own completeness check instead.
    const partnerNeedsMore = isPartnerMode.value && !partnerDraftReady.value
    if (status === 'need_more_info' || status === 'incomplete' || partnerNeedsMore) { const question = responseQuestion(payload) || (partnerNeedsMore ? '请补充往来账户、变动金额或盘点后的余额。' : ''); pushReviewBubbles(briefComment.value, question) }
    else if (status === 'fallback' || status === 'error') { const question = responseQuestion(payload) || 'AI 暂时无法完整解析，请在下方确认卡片补齐信息。'; conversation.value.push({ role: 'assistant', content: question }) }
    else if (briefComment.value) { pushReviewBubbles(briefComment.value) }
    else if (isPartnerMode.value) { pushReviewBubbles('我已识别为往来账户变化，请核对后一次确认。') }
    else { pushReviewBubbles(isTransferDraft.value ? '我已整理好这笔账户转账/还款，请核对来源和目标账户。' : isCombinedMode.value ? '我已同时整理好现金与往来两部分，请核对后一次确认。' : '我已整理好这笔现金记录，请核对后确认。') }
  } catch (error) {
    retryStatus.value = ''
    const presentation = errorPresentation(error)
    requestError.value = presentation
    aiUnavailable.value = presentation.kind === 'ai_unavailable' || presentation.kind === 'ai_error'
    const retryNote = presentation.attempts ? `\n\n已自动重试 ${presentation.attempts} 次。` : ''
    conversation.value.push({ role: 'assistant', content: `${presentation.message}${retryNote}` })
  } finally { parsing.value = false }
}

function resetConversation() { conversation.value = []; conversationId.value = null; prompt.value = ''; parseSource.value = ''; parseWarning.value = ''; briefComment.value = ''; confirmError.value = ''; retryStatus.value = ''; requestError.value = null; aiUnavailable.value = false; partnerActions.value = []; partnerIntent.value = ''; resolvedMode.value = 'combined'; Object.assign(draftNames, { category: '', method: '', partner: '' }); Object.assign(partnerLedger, { type: '', amount_cents: null, amount_text: '', enabled: false }); Object.assign(partnerBalance, { after_cents: null, after_text: '', expected_cents: null, delta_cents: null, kind: defaultBalanceKindForPartnerType(partnerCurrentType.value), apply_reconciliation: false }); Object.assign(draft, { kind: 'cashflow', direction: 'expense', amount: '', occurred_at: localDateTimeValue(), category_id: '', payment_method_id: '', transfer_payment_method_id: '', partner_id: selectedPartnerId.value || '', notes: '' }); resetPartnerRows(); normalizePartnerSelections() }
function normalizedCashDraft() {
  const cents = amountToCents(draft.amount)
  const occurred_at = datetimeLocalToUtcIso(draft.occurred_at)
  if (!occurred_at) throw new Error('请输入有效的北京时间。')
  const partnerId = draft.partner_id || selectedPartnerId.value
  const value = { occurred_at, kind: isTransferDraft.value ? 'transfer' : 'cashflow', direction: isTransferDraft.value ? 'expense' : draft.direction, amount_cents: cents, category_id: isTransferDraft.value ? null : Number(draft.category_id), payment_method_id: Number(draft.payment_method_id), partner_id: isTransferDraft.value ? null : (partnerId ? Number(partnerId) : null), partner_name: isTransferDraft.value ? null : (!partnerId ? (draftNames.partner || null) : null), notes: draft.notes || null }
  if (isTransferDraft.value) {
    value.transfer_payment_method_id = Number(draft.transfer_payment_method_id)
    return value
  }
  if (combinedEnabled.value && partnerLedger.type && (value.partner_id || value.partner_name)) {
    value.partner_ledger_type = partnerLedger.type
    if (partnerLedger.amount_cents !== null && partnerLedger.amount_cents !== '') value.partner_ledger_amount_cents = Math.abs(Number(partnerLedger.amount_cents))
    if (Number.isInteger(partnerBalance.after_cents)) {
      value.partner_balance_after_cents = partnerBalance.after_cents
    }
  }
  return value
}
function partnerEntrySignedAmount(row, baseBalance) {
  if (row.entry_type === 'balance_check') return 0
  let amount = signedAmountToCents(row.amount, row.entry_type === 'limit_adjust')
  const after = signedAmountToCents(row.balance_after)
  if (!Number.isInteger(amount) && Number.isInteger(after)) {
    const delta = after - Number(baseBalance || 0)
    if (row.entry_type === 'prepaid_in' || row.entry_type === 'credit_repay') amount = Math.abs(delta)
    else if (row.entry_type === 'prepaid_out' || row.entry_type === 'credit_use' || row.entry_type === 'refund') amount = Math.abs(delta)
    else amount = delta
  }
  return amount
}
function normalizedPartnerEntries() {
  const partnerRef = draft.partner_id || selectedPartnerId.value
  const partnerName = partnerRef ? null : (draftNames.partner || null)
  if (!partnerRef && !partnerName) throw new Error('请选择往来账户。')
  const entries = []
  let baseBalance = partnerCurrentBalance.value
  for (const row of partnerEntryRows.value) {
    const occurred_at = datetimeLocalToUtcIso(row.occurred_at)
    if (!occurred_at) throw new Error('请输入有效的北京时间。')
    const amount = partnerEntrySignedAmount(row, baseBalance)
    const after = signedAmountToCents(row.balance_after)
    if (!Number.isInteger(amount) || (row.entry_type === 'limit_adjust' ? amount === 0 : (row.entry_type === 'balance_check' ? amount !== 0 : amount <= 0))) throw new Error('每条往来变动都需要填写有效金额或盘点后的余额。')
    const value = { partner_id: partnerRef ? Number(partnerRef) : null, partner_name: partnerName, entry_type: row.entry_type, amount_cents: amount, occurred_at, notes: row.notes || null }
    if (Number.isInteger(after)) {
      value.observed_balance_cents = after
      value.partner_balance_after_cents = after
      value.observed_balance_kind = row.balance_kind || partnerBalance.kind || 'prepaid_balance'
    }
    entries.push(value)
    const sign = partnerEntryDeltaSign(row.entry_type)
    baseBalance = Number.isInteger(after) ? after : baseBalance + sign * amount
  }
  return { partner_id: partnerRef ? Number(partnerRef) : null, partner_name: partnerName, entries }
}
async function confirmDraft() {
  confirmError.value = ''
  if (!draftReady.value) { confirmError.value = isPartnerMode.value ? `请补齐：${draftMissingFields.value.join('、') || '往来变动信息'}。` : isTransferDraft.value ? `请补齐：${draftMissingFields.value.join('、') || '来源和目标账户'}。` : '请补齐金额、分类和资金账户。'; return }
  let payload
  try { payload = isPartnerMode.value ? normalizedPartnerEntries() : normalizedCashDraft() } catch (error) { confirmError.value = error.message || '请输入有效的北京时间。'; return }
  confirming.value = true
  try {
    let result
    if (isPartnerMode.value) {
      const firstEntry = payload.entries[0]
      // Current backend contract accepts one normalized draft plus optional
      // observed-balance fields.  The UI still presents movement and balance
      // together as one confirmation card, so the operation remains one click
      // and cannot create an accidental cash transaction.
      const modePayload = {
        mode: 'partner',
        confirm: true,
        draft: {
          occurred_at: firstEntry.occurred_at,
          partner_id: firstEntry.partner_id,
          partner_name: firstEntry.partner_name,
          partner_ledger_type: firstEntry.entry_type,
          partner_ledger_amount_cents: firstEntry.amount_cents,
          partner_balance_after_cents: firstEntry.partner_balance_after_cents,
          partner_balance_kind: firstEntry.observed_balance_kind,
          notes: firstEntry.notes,
        },
        partner_ledger_type: firstEntry.entry_type,
        partner_ledger_amount_cents: firstEntry.amount_cents,
        observed_balance_cents: firstEntry.observed_balance_cents,
        observed_balance_kind: firstEntry.observed_balance_kind,
        apply_balance_reconciliation: Boolean(partnerBalance.apply_reconciliation),
      }
      try {
        result = await aiApi.confirmMode('partner', modePayload)
      } catch (error) {
        // Safe compatibility path for a backend without partner-AI mode: write
        // only explicit partner ledger entries, never a cash transaction.
        // Only a missing route is a compatibility case. Validation/conflict
        // responses must stay visible to the user; falling back on 422 could
        // turn a rejected proposal into an unintended ledger write.
        if (!(error instanceof ApiError) || ![404, 405, 501].includes(error.status)) throw error
        const { partner_id: id, observed_balance_cents, partner_balance_after_cents, observed_balance_kind, ...ledgerPayload } = firstEntry
        let saved
        try {
          saved = await partnersApi.addLedgerEntry(id, { ...ledgerPayload, observed_balance_cents, partner_balance_after_cents, observed_balance_kind })
        } catch (ledgerError) {
          // The pre-mode ledger endpoint does not know observed-balance
          // metadata; retry with its canonical fields only.
          if (!(ledgerError instanceof ApiError) || ![400, 422].includes(ledgerError.status)) throw ledgerError
          saved = await partnersApi.addLedgerEntry(id, ledgerPayload)
        }
        result = { partner_action: saved, balance_reconciliation: saved?.balance_reconciliation }
      }
    } else {
      const cashPayload = { mode: isTransferDraft.value ? 'cash' : (isCombinedMode.value || combinedEnabled.value ? 'combined' : 'cash'), draft: payload, confirm: true }
      if (combinedEnabled.value) {
        cashPayload.partner_ledger_type = partnerLedger.type || undefined
        cashPayload.partner_ledger_amount_cents = partnerLedger.amount_cents !== null && partnerLedger.amount_cents !== '' ? Math.abs(Number(partnerLedger.amount_cents)) : undefined
        cashPayload.observed_balance_cents = Number.isInteger(partnerBalance.after_cents) ? partnerBalance.after_cents : undefined
        cashPayload.observed_balance_kind = partnerBalance.kind || undefined
        cashPayload.apply_balance_reconciliation = Boolean(partnerBalance.apply_reconciliation)
      }
      try { result = await aiApi.confirmMode(cashPayload.mode, cashPayload) }
      catch (error) {
        // A combined confirmation must never degrade to cash-only: that would
        // leave the two books out of sync. A legacy cash endpoint may still be
        // used for plain cash mode only.
        if (!endpointMissing(error) || cashPayload.mode === 'combined') throw error
        result = await transactionsApi.create({ ...payload, source: 'ai' })
      }
    }
    const transactionId = result?.transaction?.id || result?.id
    const confirmationWarning = result?.warning
    const actionCount = result?.partner_actions?.length || result?.partner_action ? (Array.isArray(result.partner_actions) ? result.partner_actions.length : 1) : payload?.entries?.length || 0
    const successText = isPartnerMode.value ? `已确认 ${actionCount || 1} 条往来流水${result?.balance_reconciliation ? '，余额盘点已记录' : ''}。` : isTransferDraft.value ? `${confirmationWarning ? `${confirmationWarning} ` : ''}已确认账户转账/还款${transactionId ? `（流水 #${transactionId}）` : ''}。` : `${confirmationWarning ? `${confirmationWarning} ` : ''}已确认现金记账${transactionId ? `（流水 #${transactionId}）` : ''}${combinedEnabled.value ? '，往来变动已同步' : ''}。`
    notice.value = { type: confirmationWarning ? 'error' : 'success', message: successText }
    await loadHistory(); resetConversation()
  } catch (error) { confirmError.value = error instanceof ApiError ? error.message : '确认入账失败，请稍后重试。' }
  finally { confirming.value = false }
}

const periodLabels = { day: '今日', week: '本周', month: '本月', year: '本年', all: '全部', custom: '自定义周期' }
function historyTitle(item) { return item.period ? `AI 分析 · ${periodLabels[item.period] || item.period}` : item.request_text || item.text || item.prompt || 'AI 记账解析' }
function historySummary(item) { return item.response_text || item.summary || item.content || item.result?.summary || item.status || '已保存' }
function historyStatus(item) { const status = String(item.status || '').toLowerCase(); return status === 'complete' || status === 'confirmed' ? '已确认' : status === 'error' ? '失败' : '已记录' }
function historyStatusClass(item) { return String(item.status || '').toLowerCase() === 'error' ? 'history-error' : 'history-ok' }
async function loadHistory() { historyLoading.value = true; historyError.value = ''; try { history.value = await aiApi.history({ limit: 20 }) } catch (error) { if (!endpointMissing(error)) historyError.value = error instanceof ApiError ? error.message : '历史记录加载失败。' } finally { historyLoading.value = false } }
async function loadReferences() { const results = await Promise.allSettled([categoriesApi.list(), paymentMethodsApi.list(), partnersApi.list({ status: 'active' })]); if (results[0].status === 'fulfilled') categories.value = results[0].value; if (results[1].status === 'fulfilled') paymentMethods.value = results[1].value; if (results[2].status === 'fulfilled') partners.value = results[2].value }
watch(selectedPartnerId, () => {
  // Entering a different partner context starts a clean proposal.  The
  // resolved proposal mode itself is deliberately not watched: it changes
  // after every parse and must not clear the confirmation card.
  if (conversation.value.length || draft.amount || partnerEntryRows.value.some((row) => row.amount || row.balance_after)) resetConversation()
  else draft.partner_id = selectedPartnerId.value || ''
})
watch(partnerCurrentType, () => { normalizePartnerSelections() })
onMounted(() => { draft.partner_id = selectedPartnerId.value || ''; loadReferences(); loadHistory() })
</script>

<style scoped>
.request-error{display:grid;gap:4px;margin-top:11px;padding:11px 12px;border:1px solid #f1d0d0;border-radius:9px;background:#fff6f6;color:#a33f46;font-size:12px;line-height:1.5}.request-error strong{font-size:12px}.request-error span{color:#8c555b}.request-error small{color:#aa7378}.request-error a{width:max-content;margin-top:2px;color:#2563eb;text-decoration:none;font-weight:600}.request-error.is-backend_unreachable,.request-error.is-timeout{border-color:#f0d9af;background:#fff9ed;color:#88651f}.request-error.is-backend_unreachable span,.request-error.is-timeout span{color:#866d3d}
.panel{background:#fff;border-radius:13px;box-shadow:0 2px 8px #243b5a0d}.primary{border:0;border-radius:8px;background:#2563eb;color:#fff;padding:10px 17px;font-size:13px;font-weight:600;cursor:pointer;white-space:nowrap}.primary:hover{background:#1d4ed8}.primary:disabled{opacity:.65;cursor:wait}.secondary-link{color:#2563eb;text-decoration:none;font-size:13px;font-weight:600;padding:10px 3px}.ai-chat-header{margin-top:28px;padding:24px;border:1px solid #e1eaf7;box-shadow:0 7px 24px #23436d12}.section-heading{display:flex;align-items:center;gap:12px}.ai-badge{width:38px;height:38px;border-radius:12px;background:#edf4ff;color:#2563eb;display:grid;place-items:center;font-size:19px}.section-heading h2,.panel-title h2{margin:0;color:#34435b;font-size:17px}.section-heading p,.panel-title p{margin:6px 0 0;color:#8a97aa;font-size:12px}.prompt-form{margin-top:18px}.prompt-form textarea{width:100%;min-height:44px;max-height:130px;resize:vertical;border:1px solid #dbe2ee;border-radius:12px;padding:11px 13px;color:#44536a;background:#fbfcff;font:inherit;font-size:14px;outline:0}.prompt-form textarea:focus{border-color:#3b82f6;box-shadow:0 0 0 3px #3b82f61c}.prompt-foot{display:flex;justify-content:space-between;align-items:center;gap:14px;margin-top:11px;color:#98a4b4;font-size:11px}.chat-composer{position:sticky;bottom:14px;z-index:20;margin-top:18px;padding:12px 16px 14px;border:1px solid #d8e6f8;box-shadow:0 10px 28px #23436d1b}.chat-composer .prompt-form{margin-top:0}.chat-send{display:grid;place-items:center;flex:0 0 42px;width:42px;height:42px;border:0;border-radius:50%;background:#2563eb;color:#fff;font-size:23px;line-height:1;cursor:pointer;box-shadow:0 4px 10px #2563eb38}.chat-send:disabled{opacity:.45;cursor:wait;box-shadow:none}.chat-send .spinner{margin:0;width:16px;height:16px}.fallback-hint{margin-top:11px;background:#fff8e7;color:#8a6924;padding:10px 12px;border-radius:8px;font-size:12px}.fallback-hint a{color:#2563eb;margin-left:4px;text-decoration:none}.parse-result-meta{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin-top:12px;padding-top:12px;border-top:1px solid #edf1f6}.parse-source-badge{display:inline-flex;align-items:center;gap:6px;padding:5px 8px;border-radius:99px;background:#edf5ff;color:#2563eb;font-size:10px;font-weight:600;white-space:nowrap}.parse-source-badge i{width:6px;height:6px;border-radius:50%;background:#2563eb}.parse-source-badge.is-fallback{background:#f1f3f6;color:#64748b}.parse-source-badge.is-fallback i{background:#94a3b8}.parse-warning-text{color:#8a6924;font-size:11px;line-height:1.45}.conversation,.confirm-card,.history{margin-top:18px;overflow:hidden}.panel-title{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;padding:20px 24px;border-bottom:1px solid #edf0f5}.text-button{border:0;background:transparent;color:#2563eb;font-size:12px;cursor:pointer;padding:4px}.messages{padding:18px 24px 21px;display:grid;gap:12px}.message{display:flex;gap:9px;align-items:flex-start;max-width:85%}.message-avatar{width:27px;height:27px;flex:0 0 27px;border-radius:9px;display:grid;place-items:center;font-size:11px;font-weight:600}.assistant-message .message-avatar{color:#2563eb;background:#edf4ff}.user-message{margin-left:auto;flex-direction:row-reverse;scroll-margin-top:20px}.user-message .message-avatar{color:#52617a;background:#eef2f8}.message p{margin:0;border-radius:11px;padding:10px 12px;color:#53627a;background:#f6f8fb;font-size:13px;line-height:1.6}.user-message p{color:#fff;background:#2563eb}.parsing-message p{display:inline-flex;align-items:center;gap:8px;color:#7e8da4}.typing-dots{display:inline-flex;gap:3px;align-items:center}.typing-dots i{width:5px;height:5px;border-radius:50%;background:#8ba5ce;animation:typing-dot 1.1s infinite ease-in-out}.typing-dots i:nth-child(2){animation-delay:.15s}.typing-dots i:nth-child(3){animation-delay:.3s}@keyframes typing-dot{0%,60%,100%{opacity:.35;transform:translateY(0)}30%{opacity:1;transform:translateY(-2px)}}.confirm-card{padding-bottom:22px}.draft-status{color:#8a6924;background:#fff4da;border-radius:99px;padding:5px 8px;font-size:11px}.warning{margin:16px 24px 0;border-radius:8px;padding:10px 12px;background:#fff8e7;color:#8a6924;font-size:12px}.draft-form{padding:18px 24px 0}.draft-direction{display:grid;grid-template-columns:1fr 1fr;gap:5px;padding:4px;background:#f1f5fb;border-radius:10px}.draft-direction button{border:0;border-radius:7px;padding:9px;background:transparent;color:#7c8ba1;cursor:pointer;font-size:13px}.draft-direction button.selected{background:#fff;color:#2563eb;box-shadow:0 1px 5px #263b6114;font-weight:600}.draft-grid{display:grid;grid-template-columns:1fr 1fr;gap:0 14px}.draft-grid label{display:block;color:#59677d;font-size:13px;margin:14px 0}.draft-grid input,.draft-grid select,.draft-grid textarea{display:block;width:100%;margin-top:6px;border:1px solid #dbe2ee;border-radius:8px;padding:10px;color:#44536a;background:#fff;font:inherit;font-size:13px;outline:0}.draft-grid input:focus,.draft-grid select,.draft-grid textarea:focus{border-color:#3b82f6}.partner-ledger-confirm{margin-top:13px;border:1px solid #dbe6f5;border-radius:9px;background:#f8fbff;padding:12px}.ledger-toggle{display:flex;align-items:center;gap:8px;color:#42536c;font-size:13px;font-weight:600}.ledger-toggle input{accent-color:#2563eb}.ledger-hint{margin:8px 0 0;color:#9a6d26;font-size:12px}.ledger-fields{display:flex;align-items:center;gap:12px;margin-top:10px}.ledger-fields label{color:#59677d;font-size:12px;flex:0 1 220px}.ledger-fields select{display:block;width:100%;margin-top:5px;border:1px solid #dbe2ee;border-radius:8px;padding:8px;color:#44536a;background:#fff;font:inherit;font-size:12px}.ledger-preview{color:#53627a;font-size:12px;white-space:nowrap}.confirm-actions{display:flex;justify-content:flex-end;gap:9px;margin-top:8px}.outline-button{border:1px solid #d6dfec;border-radius:8px;background:#fff;color:#52617a;padding:9px 15px;cursor:pointer;font-size:13px}.form-error{margin-top:13px;color:#a83232;background:#fff0f0;border-radius:8px;padding:10px 12px;font-size:13px}.history-state{min-height:130px;display:grid;place-content:center;justify-items:center;text-align:center;color:#8b98aa;padding:20px}.history-state p{margin:7px 0;font-size:13px}.error-state{color:#ba4b53}.history-list{list-style:none;padding:0 24px;margin:0}.history-list li{display:flex;align-items:flex-start;gap:11px;padding:15px 0;border-bottom:1px solid #edf0f5}.history-list li:last-child{border-bottom:0}.history-icon{width:30px;height:30px;border-radius:9px;display:grid;place-items:center;color:#2563eb;background:#edf4ff;font-size:14px}.history-content{min-width:0;flex:1}.history-content strong{display:block;color:#53627a;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.history-content span{display:block;color:#a0aaba;font-size:10px;margin-top:4px}.history-content p{margin:6px 0 0;color:#7d8ba0;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.history-status{border-radius:99px;padding:4px 7px;font-size:10px;white-space:nowrap}.history-ok{color:#12845e;background:#e7f8f0}.history-error{color:#c84d54;background:#fff0f0}.spinner{width:16px;height:16px;border:2px solid #ffffff66;border-top-color:#fff;border-radius:50%;animation:spin .7s linear infinite;display:inline-block;vertical-align:-3px;margin-right:5px}.spinner.dark{border-color:#dce7f8;border-top-color:#2563eb;margin:0 0 5px}@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:620px){.ai-chat-header{margin-top:20px;padding:18px 16px}.prompt-foot{align-items:flex-end;flex-direction:row}.prompt-foot .chat-send{width:42px}.panel-title{padding:17px 16px}.messages,.draft-form{padding-left:16px;padding-right:16px}.message{max-width:95%}.draft-grid{grid-template-columns:1fr}.ledger-fields{align-items:stretch;flex-direction:column;gap:5px}.ledger-preview{white-space:normal}.history-list{padding:0 16px}.history-content p{white-space:normal}.secondary-link{font-size:11px}.chat-composer{bottom:8px;margin-left:0;margin-right:0;padding:10px 12px 11px}.chat-composer .prompt-form textarea{min-height:42px}.chat-composer .quick-prompts{overflow-x:auto;flex-wrap:nowrap;scrollbar-width:none}.chat-composer .quick-prompts::-webkit-scrollbar{display:none}.chat-composer .quick-prompts button{white-space:nowrap}}
.message-bubble{min-width:0;display:grid;gap:6px}.chat-message .message-bubble p{white-space:pre-wrap}.assistant-message.chat-message{max-width:92%}.message-link{width:max-content;max-width:100%;color:#2563eb;font-size:12px;font-weight:600;text-decoration:none}
.reconciliation-toggle{display:flex;align-items:center;gap:8px;margin:12px 0 0;padding:10px 11px;border:1px solid #dbe6f5;border-radius:8px;background:#f8fbff;color:#596b84;font-size:12px;line-height:1.45}.reconciliation-toggle input{accent-color:#2563eb}.transfer-hint{margin:0 0 12px;padding:10px 11px;border:1px solid #dbe6f5;border-radius:8px;background:#f8fbff;color:#596b84;font-size:12px;line-height:1.5}
@media(max-width:620px){
  .secondary-link{display:inline-flex;align-items:center;min-height:44px;padding:9px 0;font-size:12px}
  .ai-chat-header{min-width:0}
  .section-heading{align-items:flex-start}
  .section-heading>div:last-child{min-width:0}
  .section-heading h2,.section-heading p{overflow-wrap:anywhere;line-height:1.5}
  .prompt-form textarea{min-height:96px;line-height:1.55;font-size:16px}
  .prompt-foot{align-items:stretch;gap:10px;line-height:1.5}
  .prompt-foot>span{overflow-wrap:anywhere}
  .prompt-foot .primary{min-height:44px}
  .fallback-hint{line-height:1.55;overflow-wrap:anywhere}
  .panel-title{align-items:flex-start;gap:8px}
  .panel-title>div{min-width:0}
  .panel-title h2,.panel-title p{overflow-wrap:anywhere;line-height:1.5}
  .text-button,.outline-button{min-height:44px;min-width:44px;padding:10px 7px;display:inline-flex;align-items:center;justify-content:center}
  .messages{gap:10px;overflow:hidden}
  .message{max-width:100%;min-width:0}
  .message p{min-width:0;overflow-wrap:anywhere;word-break:break-word;line-height:1.55}
  .warning{margin-left:16px;margin-right:16px;line-height:1.55;overflow-wrap:anywhere}
  .draft-form{min-width:0}
  .draft-direction button{min-height:44px}
  .draft-grid label{line-height:1.45}
  .draft-grid input,.draft-grid select,.draft-grid textarea{min-height:44px;font-size:16px}
  .draft-grid textarea{line-height:1.45}
  .partner-ledger-confirm{line-height:1.45}
  .ledger-toggle{min-height:44px}
  .ledger-toggle input{width:20px;height:20px;flex:0 0 20px}
  .ledger-fields select{min-height:44px;font-size:16px}
  .ledger-preview{overflow-wrap:anywhere;line-height:1.5}
  .confirm-actions{flex-direction:column;gap:8px;margin-top:12px}
  .confirm-actions>*{width:100%;min-height:44px}
  .history-list{min-width:0}
  .history-list li{align-items:flex-start;min-width:0;min-height:58px}
  .history-content{min-width:0}
  .history-content strong{white-space:normal;overflow-wrap:anywhere;line-height:1.45}
  .history-content p{line-height:1.5;overflow-wrap:anywhere;word-break:break-word}
  .history-status{align-self:flex-start;min-height:28px;display:inline-flex;align-items:center}
}
@media(max-width:380px){
  .ai-chat-header{padding-left:13px;padding-right:13px}
  .panel-title,.messages,.draft-form{padding-left:13px;padding-right:13px}
  .warning{margin-left:13px;margin-right:13px}
  .history-list{padding-left:13px;padding-right:13px}
  .secondary-link{font-size:11px}
  .message{gap:7px}
  .message-avatar{width:25px;height:25px;flex-basis:25px}
}
.ai-header-actions{display:flex;align-items:center;justify-content:flex-end;gap:12px;flex-wrap:wrap}.ai-header-mode{display:inline-flex;align-items:center;gap:5px;color:#2563eb;background:#edf4ff;border:1px solid #dce9ff;border-radius:99px;padding:7px 10px;font-size:11px;font-weight:600;white-space:nowrap}.ai-header-mode span{font-size:14px;line-height:1}.ai-compose{border:1px solid #e1eaf7;box-shadow:0 7px 24px #23436d12}.compose-modebar{display:flex;align-items:center;justify-content:space-between;gap:16px;margin:-24px -24px 21px;padding:12px 24px;border-bottom:1px solid #e8eef7;background:linear-gradient(90deg,#f7faff,#fff)}.compose-mode-current{display:flex;align-items:center;gap:9px;min-width:0}.compose-mode-icon{display:grid;place-items:center;width:26px;height:26px;border-radius:8px;background:#eaf2ff;color:#2563eb;font-size:14px}.compose-mode-current strong{display:block;color:#33435b;font-size:12px}.compose-mode-current div>span{display:block;margin-top:2px;color:#8b98aa;font-size:10px}.manual-switch{display:inline-flex;align-items:center;gap:5px;color:#64748b;text-decoration:none;border:1px solid #dbe3ef;border-radius:8px;padding:8px 11px;font-size:11px;white-space:nowrap;transition:border-color .15s,color .15s,background .15s}.manual-switch:hover{border-color:#9dbcf1;color:#2563eb;background:#f7faff}.manual-switch span{font-size:14px;line-height:1}.ai-flow{display:flex;align-items:center;gap:8px;margin:18px 0 0;color:#a0aaba;font-size:11px}.ai-flow i{font-style:normal;color:#c1cada}.ai-flow-step{display:inline-flex;align-items:center;gap:5px;white-space:nowrap}.ai-flow-step b{display:grid;place-items:center;width:20px;height:20px;border-radius:50%;background:#eef2f8;color:#7d8ba0;font-size:10px}.ai-flow-step.is-active{color:#2563eb;font-weight:600}.ai-flow-step.is-active b{background:#2563eb;color:#fff}.quick-prompts{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin-top:10px}.quick-prompts>span{color:#99a5b5;font-size:11px;margin-right:2px}.quick-prompts button{border:1px solid #dce5f1;border-radius:99px;background:#fff;color:#62738c;padding:6px 10px;font-size:11px;cursor:pointer;transition:border-color .15s,color .15s,background .15s}.quick-prompts button:hover{border-color:#a8c4f2;color:#2563eb;background:#f7faff}.quick-prompts button:disabled{opacity:.55;cursor:wait}.draft-progress{margin:14px 24px 0;padding:9px 11px;border-radius:8px;color:#8a6924;background:#fff8e7;font-size:12px;line-height:1.45}.draft-progress.ready{color:#12845e;background:#e7f8f0}.ai-brief-comment{display:grid;grid-template-columns:30px minmax(0,1fr);gap:10px;margin:12px 24px 0;padding:12px 13px;border:1px solid #dbe8fb;border-radius:11px;background:linear-gradient(145deg,#f7faff,#fff)}.ai-brief-comment>span{display:grid;place-items:center;width:30px;height:30px;border-radius:9px;background:#e8f1ff;color:#2563eb;font-size:14px}.ai-brief-comment strong{display:block;color:#41536d;font-size:11px}.ai-brief-comment p{margin:4px 0 0;color:#61728a;font-size:12px;line-height:1.55;overflow-wrap:anywhere}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media(max-width:760px){.ai-header-actions{gap:7px}.ai-header-mode{padding:6px 8px}.compose-modebar{align-items:flex-start;flex-direction:column;gap:9px;margin:-18px -16px 17px;padding:11px 16px}.manual-switch{min-height:40px}.ai-flow{gap:5px;justify-content:space-between;font-size:10px}.ai-flow i{font-size:10px}.quick-prompts{gap:6px}.quick-prompts button{min-height:36px}.draft-progress,.ai-brief-comment{margin-left:16px;margin-right:16px}}
.partner-confirm-card{position:relative;border:1px solid #dce7f6;box-shadow:0 10px 30px #213b6114;}
.partner-confirm-card:before{content:"";position:absolute;inset:0 0 auto;height:3px;background:linear-gradient(90deg,#2563eb,#60a5fa 58%,#d9e7fa);z-index:2;}
.partner-confirm-card>.panel-title{background:linear-gradient(145deg,#fff 0%,#f7faff 100%);}
.mode-context-note{display:flex;align-items:center;gap:9px;margin-top:13px;padding:10px 12px;border:1px solid #dce7f5;border-radius:10px;background:#f8fbff;color:#667791;font-size:11px;}
.mode-context-note:before{content:"↔";display:grid;place-items:center;width:27px;height:27px;border-radius:8px;background:#e8f1ff;color:#2563eb;font-size:13px;font-weight:700;}
.mode-context-note strong{color:#40516b;font-size:12px;}.mode-context-note span{margin-left:auto;}
.partner-mode-summary{display:flex;align-items:center;gap:12px;padding:14px 15px;border:1px solid #dce7f5;border-radius:13px;background:linear-gradient(145deg,#f9fbff,#f1f6fd);}
.partner-mode-avatar{display:grid;place-items:center;flex:0 0 40px;width:40px;height:40px;border-radius:12px;background:linear-gradient(145deg,#e7f1ff,#dbe9ff);color:#2563eb;font-size:13px;font-weight:700;box-shadow:0 2px 6px #315e9e1a;}
.partner-mode-summary>div{min-width:0;flex:1}.partner-mode-summary strong{display:block;color:#35465f;font-size:14px;line-height:1.4}.partner-mode-summary small{display:block;margin-top:3px;color:#8a98aa;font-size:11px;}
.partner-balance-chip{flex:0 0 auto;padding:6px 9px;border:1px solid #d5e3f4;border-radius:99px;background:#fff;color:#55708f;font-size:11px;white-space:nowrap;}
.partner-select-label{display:block;padding:14px 15px;border:1px solid #dce7f5;border-radius:13px;background:#f8fbff;color:#59677d;font-size:12px;}.partner-select-label select{display:block;width:100%;margin-top:7px;border:1px solid #d6e1ee;border-radius:9px;padding:10px 11px;background:#fff;color:#44536a;font:inherit;font-size:13px;outline:0;}.partner-select-label select:focus{border-color:#3b82f6;box-shadow:0 0 0 3px #3b82f617;}
.partner-entry-list{display:grid;gap:12px;margin-top:13px;}.partner-entry-row{position:relative;padding:17px;border:1px solid #dce7f5;border-radius:15px;background:#fff;box-shadow:0 6px 18px #243b5a0a;overflow:hidden;}.partner-entry-row:before{content:"";position:absolute;inset:0 0 auto;height:3px;background:linear-gradient(90deg,#2563eb,#79aaf0);}
.partner-entry-head{display:flex;align-items:center;gap:10px;min-width:0;}.partner-entry-head>div{min-width:0;flex:1}.partner-entry-head strong{display:block;color:#32445e;font-size:14px;line-height:1.4}.partner-entry-head div>span{display:block;margin-top:2px;color:#8a98ab;font-size:11px;}.partner-entry-head em{padding:5px 8px;border-radius:99px;background:#edf5ff;color:#2563eb;font-size:10px;font-style:normal;white-space:nowrap;}
.partner-entry-icon{display:grid;place-items:center;flex:0 0 34px;width:34px;height:34px;border-radius:10px;background:#e9f2ff;color:#2563eb;font-size:16px;font-weight:700;}
.partner-balance-comparison{display:grid;grid-template-columns:minmax(0,1fr) 34px minmax(0,1fr);align-items:stretch;gap:10px;margin-top:15px;}.partner-balance-side{min-width:0;padding:14px;border:1px solid #e1e9f3;border-radius:12px;background:#f9fbfd;}.partner-balance-side>span{display:block;color:#8795a9;font-size:11px;}.partner-balance-side>strong{display:block;margin-top:7px;color:#40516a;font-size:21px;line-height:1.2;}.partner-balance-side>small{display:block;margin-top:7px;color:#9aa5b4;font-size:10px;line-height:1.4;}.partner-balance-side.is-target{background:#f5f9ff;border-color:#cfe0f5;color:#53637a;font-size:11px;}.partner-balance-side input{display:block;width:100%;height:43px;margin-top:7px;border:1px solid #cbdced;border-radius:9px;padding:9px 11px;background:#fff;color:#30445f;font:inherit;font-size:17px;font-weight:700;outline:0;}.partner-balance-side input:focus{border-color:#3b82f6;box-shadow:0 0 0 3px #3b82f617;}.partner-balance-arrow{display:grid;place-items:center;color:#7ea2d6;font-size:18px;}
.partner-detail-grid{display:grid;grid-template-columns:1fr 1.25fr;gap:12px;margin-top:13px;padding-top:13px;border-top:1px solid #edf1f6;}.partner-detail-grid label{display:block;color:#59677d;font-size:12px;}.partner-detail-grid input,.partner-detail-grid textarea{display:block;width:100%;min-height:40px;margin-top:6px;border:1px solid #dbe3ee;border-radius:9px;padding:9px 10px;background:#fff;color:#44536a;font:inherit;font-size:13px;outline:0;resize:vertical;}.partner-detail-grid input:focus,.partner-detail-grid textarea:focus{border-color:#3b82f6;box-shadow:0 0 0 3px #3b82f612;}
.partner-entry-preview{display:flex;align-items:flex-start;gap:7px;margin:12px 0 0;padding:9px 10px;border-radius:9px;background:#f0f7ff;color:#527098;font-size:11px;line-height:1.5;}.partner-entry-preview>span{display:grid;place-items:center;flex:0 0 18px;width:18px;height:18px;border-radius:50%;background:#dcecff;color:#2563eb;font-size:10px;font-weight:700;}
.partner-mode-hint{display:flex;align-items:flex-start;gap:8px;margin:12px 0 0;padding:10px 11px;border-radius:10px;background:#f7f9fc;color:#748298;font-size:11px;line-height:1.5;}.partner-mode-hint>span:first-child{display:grid;place-items:center;flex:0 0 20px;width:20px;height:20px;border-radius:7px;background:#e8eef7;color:#55708f;font-weight:700;}
.reconciliation-toggle{display:flex!important;align-items:flex-start;gap:10px;margin-top:11px;padding:12px 13px;border:1px solid #d7e4f4;border-radius:11px;background:#f7fbff;color:#52647e;cursor:pointer;}.reconciliation-toggle input{flex:0 0 19px;width:19px;height:19px;margin:1px 0 0;accent-color:#2563eb;}.reconciliation-toggle>span{min-width:0}.reconciliation-toggle strong{display:block;color:#40536e;font-size:12px;}.reconciliation-toggle small{display:block;margin-top:3px;color:#8290a4;font-size:11px;line-height:1.5;}
@media(max-width:760px){.mode-context-note{align-items:flex-start}.mode-context-note span{margin-left:0}.partner-mode-summary{align-items:flex-start;flex-wrap:wrap}.partner-balance-chip{margin-left:52px}.partner-balance-comparison{grid-template-columns:1fr}.partner-balance-arrow{height:20px;transform:rotate(90deg)}.partner-detail-grid{grid-template-columns:1fr}.partner-entry-row{padding:15px}.partner-balance-side input{font-size:16px}}
.combined-ledger-panel{position:relative;margin-top:16px;padding:18px;border:1px solid #d9e6f5;border-radius:16px;background:linear-gradient(145deg,#fbfdff 0%,#f3f7fd 100%);box-shadow:0 10px 24px #27415f10,inset 0 1px 0 #fff;overflow:hidden;}
.combined-ledger-panel:before{content:"";position:absolute;inset:0 0 auto 0;height:3px;background:linear-gradient(90deg,#2563eb 0%,#60a5fa 55%,#c7d7f1 100%);}
.combined-ledger-head{display:flex;align-items:center;gap:10px;min-width:0;position:relative;z-index:1;}
.combined-ledger-head>div{min-width:0;flex:1;}
.combined-ledger-head strong{display:block;color:#2f3f58;font-size:14px;line-height:1.4;}
.combined-ledger-head span:not(.combined-ledger-icon){display:block;margin-top:3px;color:#7e8da4;font-size:11px;line-height:1.45;}
.combined-ledger-head em{flex:0 0 auto;padding:5px 9px;border:1px solid #cfe0f6;border-radius:99px;background:#edf5ff;color:#2563eb;font-size:10px;font-style:normal;white-space:nowrap;box-shadow:0 1px 0 #fff inset;}
.combined-ledger-icon{display:grid;place-items:center;flex:0 0 34px;width:34px;height:34px;border-radius:11px;background:linear-gradient(145deg,#e8f1ff 0%,#dce9ff 100%);color:#2563eb;font-size:16px;font-weight:700;box-shadow:0 1px 3px #2c5aa51f;}
.combined-ledger-summary{display:grid;grid-template-columns:1.4fr 1fr 1fr;gap:10px;margin-top:14px;position:relative;z-index:1;}
.combined-ledger-summary>div{min-width:0;padding:11px 12px;border:1px solid #e2eaf4;border-radius:12px;background:rgba(255,255,255,.92);box-shadow:0 1px 0 #fff inset;}
.combined-ledger-summary small{display:block;color:#92a0b2;font-size:10px;line-height:1.4;letter-spacing:.02em;text-transform:uppercase;}
.combined-ledger-summary strong{display:block;margin-top:4px;color:#415169;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.combined-ledger-fields{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-top:12px;padding-top:13px;border-top:1px solid #e2eaf4;position:relative;z-index:1;}
.combined-ledger-fields label{display:block;color:#59677d;font-size:12px;line-height:1.45;}
.combined-ledger-fields input,.combined-ledger-fields select{display:block;width:100%;margin-top:6px;border:1px solid #d6e1ee;border-radius:10px;padding:10px 11px;background:#fff;color:#44536a;font:inherit;font-size:13px;outline:0;box-shadow:0 1px 0 #fff inset;}
.combined-ledger-fields input:focus,.combined-ledger-fields select:focus{border-color:#75a7ef;box-shadow:0 0 0 3px #3b82f61a;}
.combined-ledger-hint{margin:10px 0 0;color:#8a6924;font-size:11px;line-height:1.5;position:relative;z-index:1;}
@media(max-width:760px){.combined-ledger-summary{grid-template-columns:1fr}.combined-ledger-fields{grid-template-columns:1fr}.combined-ledger-fields input,.combined-ledger-fields select{min-height:44px;font-size:16px}}
</style>
