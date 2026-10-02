<template>
  <div class="mobile-ai-page">
    <section class="mobile-ai-card mobile-ai-compose mobile-ai-hero">
      <div class="mobile-ai-hero-top">
        <router-link class="mobile-ai-back" :to="selectedPartner ? '/partners' : '/dashboard'">‹ {{ selectedPartner ? '往来账户' : '概览' }}</router-link>
      </div>
      <div class="mobile-ai-card-heading">
        <span class="mobile-ai-badge" aria-hidden="true">{{ isPartnerMode ? '↔' : '✦' }}</span>
        <div>
          <p class="mobile-ai-eyebrow">AI 记账助手</p>
          <h2>说一句话，记账、查收支、要报告都可以</h2>
          <p class="mobile-ai-help">AI 会自动判断现金收支、往来余额变化，或两者同时发生；也可以直接问本月、本年或全部的收支情况，或让它生成收支报告。</p>
        </div>
      </div>
      <div class="mobile-ai-flow" aria-label="记账流程">
        <span class="is-active"><b>1</b> 描述</span><i aria-hidden="true">→</i><span><b>2</b> 核对</span><i aria-hidden="true">→</i><span><b>3</b> 入账</span>
      </div>
      <div v-if="parseSource" class="mobile-ai-parser-row" role="status" aria-live="polite">
        <span class="mobile-ai-parser-badge" :class="{ 'is-local': isLocalParse }">
          <span aria-hidden="true">{{ isLocalParse ? '◇' : '✦' }}</span>{{ parseSourceLabel }}
        </span>
        <span>{{ isLocalParse ? '请重点核对解析结果' : '确认后才会写入账本' }}</span>
      </div>
      <div v-if="effectiveParseWarning" class="mobile-ai-source-warning" :class="{ 'is-local': isLocalParse }" role="status" aria-live="polite">
        <span class="mobile-ai-source-warning-icon" aria-hidden="true">!</span>
        <div>
          <strong>{{ isLocalParse ? '已使用本地规则解析' : '解析提示' }}</strong>
          <p>{{ effectiveParseWarning }}</p>
          <router-link :to="{ path: '/transactions', query: { mode: 'manual', from: 'ai' } }">需要时使用手动流水表单</router-link>
        </div>
      </div>
      <div v-if="requestError" class="mobile-ai-request-error" :class="`is-${requestError.kind}`" role="alert">
        <strong>{{ requestError.title }}</strong>
        <p>{{ requestError.message }}</p>
        <small v-if="requestError.attempts">已自动重试 {{ requestError.attempts }} 次，仍未成功。</small>
        <router-link v-if="requestError.kind === 'ai_unavailable' || requestError.kind === 'ai_error'" :to="{ path: '/transactions', query: { mode: 'manual', from: 'ai' } }">需要时使用普通流水表单</router-link>
      </div>
    </section>

    <section v-if="conversation.length" class="mobile-ai-card mobile-ai-conversation">
      <div class="mobile-ai-section-head">
        <div>
          <p class="mobile-ai-eyebrow">进行中</p>
          <h2>AI 对话</h2>
          <p class="mobile-ai-subcopy">缺什么就继续描述，AI 会沿用本轮上下文。</p>
        </div>
        <div class="mobile-ai-session-actions">
          <button class="mobile-ai-quiet-button" type="button" :disabled="parsing || confirming" @click="focusPrompt">继续描述</button>
          <button class="mobile-ai-quiet-button is-muted" type="button" title="清空本轮对话和已解析草稿" :disabled="parsing || confirming" @click="resetConversation">清空本轮</button>
        </div>
      </div>
      <div ref="conversationThread" class="mobile-ai-thread" aria-live="polite">
        <div
          v-for="(message, index) in conversation"
          :key="`${index}-${message.content}`"
          class="mobile-ai-message"
          :class="[message.role === 'user' ? 'is-user' : 'is-assistant', { 'is-chat': message.kind === 'chat' }]"
        >
          <span class="mobile-ai-avatar">{{ message.role === 'user' ? '我' : '✦' }}</span>
          <div class="mobile-ai-bubble"><p>{{ message.content }}</p><router-link v-if="message.report_id" class="mobile-ai-message-link" :to="{ path: '/reports', query: { report: message.report_id } }">报告已保存，在财务分析中查看 →</router-link></div>
        </div>
        <div v-if="parsing" class="mobile-ai-message is-assistant mobile-ai-parsing-message"><span class="mobile-ai-avatar">✦</span><p><span class="mobile-ai-typing-dots" aria-hidden="true"><i></i><i></i><i></i></span>{{ retryStatus || parsingLabel || '正在整理这笔记录，完成后向下核对' }} <span aria-hidden="true">↓</span></p></div>
      </div>
    </section>

    <section v-if="draftVisible" class="mobile-ai-card mobile-ai-draft" :class="{ 'mobile-ai-partner-draft': isPartnerMode, 'mobile-ai-combined-draft': isCombinedMode }">
      <div class="mobile-ai-section-head">
        <div>
          <p class="mobile-ai-eyebrow">第 2 步 · 核对</p>
          <h2>{{ isPartnerMode ? '确认未结算余额' : isTransferDraft ? '确认账户转账/还款' : isCombinedMode ? '确认现金与未结算余额' : '确认现金入账' }}</h2>
        </div>
        <span class="mobile-ai-status">待确认</span>
      </div>
      <div v-if="!isPartnerMode" class="mobile-ai-draft-banner">
        <span>{{ isTransferDraft ? '内部转账' : draft.direction === 'income' ? '现金流入' : '现金流出' }}</span>
        <strong>{{ draft.amount || '待补充' }}<small> 元</small></strong>
        <em>确认前可修改</em>
      </div>
      <div v-else-if="currentPartner" class="mobile-ai-partner-banner"><span class="mobile-ai-partner-icon">{{ currentPartner.type === 'customer' ? '客' : '供' }}</span><div><strong>{{ currentPartner.name }}</strong><small>{{ currentPartner.type === 'customer' ? '客户' : '供应商' }}往来账户</small></div><em>系统记录 {{ formatMoney(partnerCurrentBalance) }}</em></div>
      <p class="mobile-ai-card-note">{{ isPartnerMode ? '只确认当前未结算余额，不会产生现金流水。' : isTransferDraft ? '只移动账户余额，不计入收入或支出。' : isCombinedMode ? '现金流水与未结算余额会同时确认。' : '请核对以下内容，AI 不会在确认前写入现金账。' }}</p>
      <p v-if="draftWarning" class="mobile-ai-warning" role="status">{{ draftWarning }}</p>
      <form class="mobile-ai-draft-form" @submit.prevent="confirmDraft">
        <template v-if="isPartnerMode">
          <label v-if="!currentPartner">往来账户<select v-model="draft.partner_id" required><option value="" disabled>请选择账户</option><option v-for="item in partners" :key="item.id" :value="String(item.id)">{{ item.name }}</option></select></label>
          <div class="mobile-ai-partner-entries">
            <article v-for="(row, index) in partnerEntryRows" :key="row._key || index" class="mobile-ai-partner-entry">
              <header><span class="mobile-ai-entry-icon" aria-hidden="true">↔</span><div><strong>核对未结算余额</strong><small>不产生现金收支</small></div><em>{{ partnerLedgerLabel(row.entry_type) }}</em></header>
              <div class="mobile-ai-balance-compare"><div><span>系统当前记录</span><strong>{{ formatMoney(partnerCurrentBalance) }}</strong></div><span aria-hidden="true">↓</span><label>本次确认余额（元）<input v-model.trim="row.balance_after" inputmode="decimal" pattern="^[0-9]*([.][0-9]{0,2})?$" required placeholder="例如：12000" /></label></div>
              <div class="mobile-ai-entry-details"><label>发生时间<input v-model="row.occurred_at" type="datetime-local" required /></label><label>备注（可选）<textarea v-model.trim="row.notes" rows="2" maxlength="500" placeholder="例如：8 月对账余额"></textarea></label></div>
              <p class="mobile-ai-entry-preview"><span aria-hidden="true">✓</span>{{ partnerBalancePreview(row) }}</p>
            </article>
          </div>
          <p class="mobile-ai-entry-single-hint"><span aria-hidden="true">i</span>余额相同会留下一条核对记录；余额不同时可选择同步调整账面。</p>
          <label v-if="partnerEntryRows[0]?.balance_after" class="mobile-ai-reconciliation-toggle"><input v-model="partnerBalance.apply_reconciliation" type="checkbox" /><span><strong>同步校准账面余额</strong><small>按差额生成一条可追溯的余额校准流水</small></span></label>
        </template>
        <template v-else>
          <div v-if="!isTransferDraft" class="mobile-ai-segmented" role="group" aria-label="现金流方向">
            <button type="button" :class="{ selected: draft.direction === 'expense' }" @click="draft.direction = 'expense'">现金流出</button>
            <button type="button" :class="{ selected: draft.direction === 'income' }" @click="draft.direction = 'income'">现金流入</button>
          </div>
          <p v-else class="mobile-ai-transfer-hint">来源账户余额减少；目标为负债账户时欠款减少，目标为现金/投资账户时余额增加。</p>
          <label>金额（元）<input v-model.trim="draft.amount" inputmode="decimal" pattern="^[0-9]+([.][0-9]{1,2})?$" required /></label>
          <label>发生时间<input v-model="draft.occurred_at" type="datetime-local" required /></label>
          <label v-if="!isTransferDraft">分类<select v-model="draft.category_id" required @change="syncCategoryDirection"><option value="" disabled>请选择分类</option><option v-for="item in availableCategories" :key="item.id" :value="String(item.id)">{{ item.name }}</option></select></label>
          <label>{{ isTransferDraft ? '来源账户' : draft.direction === 'income' ? '收款账户' : '支付账户' }}<select v-model="draft.payment_method_id" required><option value="" disabled>请选择账户</option><option v-for="item in paymentMethods" :key="item.id" :value="String(item.id)">{{ paymentMethodOptionLabel(item) }}</option></select></label>
          <label v-if="isTransferDraft">转入/还款账户<select v-model="draft.transfer_payment_method_id" required><option value="" disabled>请选择账户</option><option v-for="item in paymentMethods" :key="item.id" :value="String(item.id)">{{ paymentMethodOptionLabel(item) }}</option></select></label>
          <label v-else>关联客户/供应商（仅标签）<select v-model="draft.partner_id"><option value="">不关联</option><option v-for="item in partners" :key="item.id" :value="String(item.id)">{{ item.name }}</option></select></label>
          <label>备注<textarea v-model.trim="draft.notes" rows="2" maxlength="500" placeholder="可填写补充说明"></textarea></label>
          <div v-if="combinedVisible" class="mobile-ai-ledger mobile-ai-combined-panel">
            <div class="mobile-ai-combined-head"><span class="mobile-ai-combined-icon" aria-hidden="true">↔</span><div><strong>记录未结算余额</strong><span>AI 已识别，将与现金流水一次确认</span></div><em>同一笔记录</em></div>
            <div class="mobile-ai-combined-summary"><div><small>往来账户</small><strong>{{ draft.partner_id ? (partners.find((item) => String(item.id) === String(draft.partner_id))?.name || '待选择') : '待选择' }}</strong></div><div><small>当前未结算余额</small><strong>{{ Number.isInteger(partnerBalance.after_cents) ? formatMoney(partnerBalance.after_cents) : '待补充' }}</strong></div><div><small>AI 识别</small><strong>{{ partnerLedger.type ? partnerLedgerLabel(partnerLedger.type) : '未设置' }}</strong></div></div>
            <div class="mobile-ai-combined-fields"><label>当前未结算余额（元）<input v-model.trim="partnerBalance.after_text" inputmode="decimal" placeholder="例如：12000" @input="partnerBalance.after_cents = parseCents($event.target.value)" /></label></div>
            <p class="mobile-ai-combined-hint">填写当前未结算余额即可，系统会自动核对这次变化。</p>
            <p v-if="!draft.partner_id" class="mobile-ai-ledger-hint">请选择客户/供应商，确认时会同时写入往来流水。</p>
          </div>
        </template>
        <p v-if="confirmError" class="mobile-ai-form-error" role="alert">{{ confirmError }}</p>
        <div class="mobile-ai-form-actions">
          <button class="mobile-ai-secondary" type="button" :disabled="confirming || parsing" @click="focusPrompt">继续让 AI 补充</button>
          <button class="mobile-ai-primary" type="submit" :disabled="confirming || !draftReady">
            <span v-if="confirming" class="mobile-ai-spinner"></span>{{ confirming ? '确认中…' : isPartnerMode ? '确认未结算余额' : isTransferDraft ? '确认转账/还款' : isCombinedMode ? '确认现金 + 往来' : '确认现金入账' }}
          </button>
        </div>
        <button class="mobile-ai-reset-link" type="button" title="清空本轮对话和已解析草稿" :disabled="confirming || parsing" @click="resetConversation">清空对话与草稿</button>
      </form>
    </section>

    <section class="mobile-ai-card mobile-ai-composer" aria-label="发送记账描述">
      <form class="mobile-ai-prompt" @submit.prevent="submitPrompt">
        <label class="sr-only" for="mobile-ai-prompt-input">记账描述</label>
        <textarea
          id="mobile-ai-prompt-input"
          ref="promptInput"
          :value="prompt"
          :disabled="parsing || confirming"
          rows="1"
          maxlength="1000"
          autocomplete="off"
          placeholder="描述一笔收支或往来…"
          @input="emitPrompt"
          @keydown.enter.exact.prevent="submitPrompt"
        ></textarea>
        <div class="mobile-ai-suggestions" aria-label="示例描述">
          <button v-for="example in examplesForMode" :key="example" type="button" :disabled="parsing || confirming" @click="useExample(example)">{{ example }}</button>
        </div>
        <div class="mobile-ai-prompt-foot">
          <span class="mobile-ai-prompt-status"><span class="mobile-ai-status-dot" aria-hidden="true"></span>{{ parsing ? 'AI 正在处理…' : conversation.length ? '继续补充记录，或直接提问收支情况' : 'Enter 发送 · Shift + Enter 换行' }}</span>
          <button class="mobile-ai-send" type="submit" :disabled="!prompt || parsing || confirming" :aria-label="parsing ? '解析中' : '发送'" :title="parsing ? '解析中' : '发送'"><span v-if="parsing" class="mobile-ai-spinner"></span><span v-else aria-hidden="true">↑</span></button>
        </div>
      </form>
    </section>

    <section class="mobile-ai-card mobile-ai-history">
      <div class="mobile-ai-section-head">
        <div>
          <p class="mobile-ai-eyebrow">可追溯</p>
          <h2>AI 操作历史</h2>
          <p class="mobile-ai-subcopy">已确认和失败的解析都会保留。</p>
        </div>
        <div class="mobile-ai-session-actions">
          <button class="mobile-ai-quiet-button" type="button" @click="loadHistory">刷新</button>
          <button class="mobile-ai-quiet-button is-muted" type="button" @click="historyOpen = !historyOpen">{{ historyOpen ? '收起' : '展开' }}</button>
        </div>
      </div>
      <div v-if="historyOpen">
        <div v-if="historyLoading" class="mobile-ai-state"><span class="mobile-ai-spinner dark"></span><p>正在加载…</p></div>
        <div v-else-if="historyError" class="mobile-ai-state is-error"><p>{{ historyError }}</p></div>
        <div v-else-if="!history.length" class="mobile-ai-state"><p>还没有 AI 记账记录。</p></div>
        <ul v-else class="mobile-ai-history-list">
          <li v-for="item in history" :key="item.id || item.created_at || item.request_text">
            <span class="mobile-ai-history-icon" aria-hidden="true">✦</span>
            <div class="mobile-ai-history-copy">
              <strong>{{ historyTitle(item) }}</strong>
              <time>{{ formatDateTime(item.created_at || item.generated_at || item.updated_at) }}</time>
              <p>{{ historySummary(item) }}</p>
            </div>
            <span class="mobile-ai-history-status" :class="historyStatusClass(item)">{{ historyStatus(item) }}</span>
          </li>
        </ul>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { amountToCents, formatDateTime, formatMoney } from '../api'

const props = defineProps({
  prompt: { type: String, default: '' },
  conversation: { type: Array, default: () => [] },
  parsing: { type: Boolean, default: false },
  confirming: { type: Boolean, default: false },
  aiUnavailable: { type: Boolean, default: false },
  retryStatus: { type: String, default: '' },
  parsingLabel: { type: String, default: '' },
  requestError: { type: Object, default: null },
  parseSource: { type: String, default: '' },
  parseWarning: { type: String, default: '' },
  draftVisible: { type: Boolean, default: false },
  draftReady: { type: Boolean, default: false },
  draft: { type: Object, required: true },
  partnerLedger: { type: Object, required: true },
  briefComment: { type: String, default: '' },
  warning: { type: String, default: '' },
  confirmError: { type: String, default: '' },
  availableCategories: { type: Array, default: () => [] },
  paymentMethods: { type: Array, default: () => [] },
  partners: { type: Array, default: () => [] },
  history: { type: Array, default: () => [] },
  historyLoading: { type: Boolean, default: false },
  historyError: { type: String, default: '' },
  mode: { type: String, default: 'cash' },
  pageTitle: { type: String, default: 'AI 记账' },
  selectedPartner: { type: Object, default: null },
  selectedPartnerId: { type: String, default: '' },
  partnerBalance: { type: Object, default: () => ({ kind: 'prepaid_balance', after_cents: null }) },
  partnerEntryRows: { type: Array, default: () => [] },
  partnerCurrentBalance: { type: Number, default: 0 },
  partnerIntent: { type: String, default: '' },
  combinedVisible: { type: Boolean, default: false },
  combinedEnabled: { type: Boolean, default: false },
  partnerLedgerOptions: { type: Array, default: () => [] },
  partnerBalanceOptions: { type: Array, default: () => [] },
  syncCategoryDirection: { type: Function, required: true },
  addPartnerRow: { type: Function, required: true },
  removePartnerRow: { type: Function, required: true },
  submitPrompt: { type: Function, required: true },
  resetConversation: { type: Function, required: true },
  confirmDraft: { type: Function, required: true },
  loadHistory: { type: Function, required: true },
  partnerLedgerLabel: { type: Function, required: true },
})

const emit = defineEmits(['update:prompt'])
const promptInput = ref(null)
const conversationThread = ref(null)
const historyOpen = ref(false)
const examples = [
  '午餐支出 35 元，微信支付',
  '收到客户货款 3500 元，支付宝',
  '客户王先生目前未结算余额 12000 元',
  '支付宝扫了 1000 元给供应商王先生，供应商网站现在余额 760 元',
  '本月收支情况怎么样？',
  '今年收入和支出各是多少？',
  '生成本月收支报告',
]
const normalizedParseSource = computed(() => String(props.parseSource || '').trim().toLowerCase())
const isLocalParse = computed(() => ['fallback', 'local', 'local_rule', 'rule', 'rules', 'heuristic'].includes(normalizedParseSource.value))
const parseSourceLabel = computed(() => isLocalParse.value ? '本地规则解析' : 'AI 模型解析')
const effectiveParseWarning = computed(() => {
  const message = String(props.parseWarning || '').trim()
  if (message) return message
  return isLocalParse.value ? 'AI 模型本轮不可用，系统已用本地规则生成草稿；请重点核对金额、分类、时间和账户。' : ''
})
const draftWarning = computed(() => {
  const message = String(props.warning || '').trim()
  return message && message !== String(props.parseWarning || '').trim() ? message : ''
})
const isPartnerMode = computed(() => props.mode === 'partner')
const isTransferDraft = computed(() => String(props.draft?.kind || '').toLowerCase() === 'transfer')
const isCombinedMode = computed(() => props.mode === 'combined' || props.combinedVisible)
const currentPartner = computed(() => props.selectedPartner || props.partners.find((item) => String(item.id) === String(props.draft?.partner_id)) || null)
const examplesForMode = computed(() => examples)
function amountTextFromCents(value) { const number = Number(value); return Number.isFinite(number) ? String(number / 100) : '' }
function parseCents(value, allowNegative = false) {
  const text = String(value ?? '').trim()
  if (!text) return null
  if (allowNegative && text.startsWith('-')) {
    const cents = amountToCents(text.slice(1))
    return Number.isInteger(cents) ? -cents : null
  }
  const cents = amountToCents(text)
  return Number.isInteger(cents) ? cents : null
}
function accountRoleLabel(role) { return ({ cash: '现金', liability: '负债', investment: '投资' })[String(role || 'cash')] || '现金' }
function paymentMethodOptionLabel(method) { return `${method.name}${method.account_role && method.account_role !== 'cash' ? `（${accountRoleLabel(method.account_role)}）` : ''}` }
function partnerKindLabel(kind) { return '未结算余额' }
function ledgerDisplayAmount(row) { if (row?.entry_type === 'balance_check') return '不产生变动'; const cents = amountToCents(row?.amount); return Number.isInteger(cents) ? formatMoney(Math.abs(cents)) : '按盘点余额计算' }
function partnerBalancePreview(row) {
  const after = parseCents(row?.balance_after)
  if (!Number.isInteger(after)) return '请补充当前未结算余额后再确认'
  const delta = after - Number(props.partnerCurrentBalance || 0)
  if (delta === 0) return '与系统当前记录一致，本次只留存核对记录'
  return `与系统当前记录相差 ${delta > 0 ? '+' : '−'}${formatMoney(Math.abs(delta))}`
}

function emitPrompt(event) { emit('update:prompt', event?.target?.value ?? '') }
function useExample(example) {
  emit('update:prompt', example)
  focusPrompt()
}
function focusPrompt() {
  nextTick(() => {
    const input = promptInput.value
    if (!input) return
    input.focus()
    if (typeof input.scrollIntoView === 'function') input.scrollIntoView({ behavior: 'smooth', block: 'center' })
  })
}

function scrollLatestUserMessageIntoView() {
  nextTick(() => {
    const messages = conversationThread.value?.querySelectorAll('.mobile-ai-message.is-user')
    const target = messages?.[messages.length - 1]
    if (!target) return
    const reduceMotion = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    const top = target.getBoundingClientRect().top + window.scrollY - 82
    window.scrollTo({ top: Math.max(0, top), behavior: reduceMotion ? 'auto' : 'smooth' })
  })
}

watch(() => props.conversation.length, () => {
  if (props.conversation.some((message) => message.role === 'user')) scrollLatestUserMessageIntoView()
})

function historyTitle(item) { return item.period ? `AI 分析 · ${item.period}` : item.request_text || item.text || item.prompt || 'AI 记账解析' }
function historySummary(item) { return item.response_text || item.summary || item.content || item.result?.summary || item.status || '已保存' }
function historyStatus(item) { const status = String(item.status || '').toLowerCase(); return status === 'complete' || status === 'confirmed' ? '已确认' : status === 'error' ? '失败' : '已记录' }
function historyStatusClass(item) { return String(item.status || '').toLowerCase() === 'error' ? 'is-error' : 'is-ok' }
</script>

<style scoped>
.mobile-ai-request-error{display:grid;gap:4px;margin-top:12px;padding:11px 12px;border:1px solid #f1d0d0;border-radius:10px;background:#fff6f6;color:#a33f46;font-size:12px;line-height:1.55}.mobile-ai-request-error strong{font-size:12px}.mobile-ai-request-error p{margin:0;color:#8c555b}.mobile-ai-request-error small{color:#aa7378}.mobile-ai-request-error a{width:max-content;margin-top:2px;color:#2563eb;text-decoration:none;font-weight:600}.mobile-ai-request-error.is-backend_unreachable,.mobile-ai-request-error.is-timeout{border-color:#f0d9af;background:#fff9ed;color:#88651f}.mobile-ai-request-error.is-backend_unreachable p,.mobile-ai-request-error.is-timeout p{color:#866d3d}
.mobile-ai-page{display:grid;gap:14px;margin-top:18px;padding-bottom:18px}.mobile-ai-card{background:#fff;border:1px solid #e7edf6;border-radius:16px;box-shadow:0 4px 16px #243b5a0a;overflow:hidden}.mobile-ai-compose{padding:19px 16px 16px}.mobile-ai-card-heading{display:flex;align-items:flex-start;gap:12px}.mobile-ai-card-heading>div{min-width:0}.mobile-ai-badge{display:grid;place-items:center;flex:0 0 40px;width:40px;height:40px;border-radius:13px;background:#eaf2ff;color:#2563eb;font-size:20px}.mobile-ai-eyebrow{margin:0 0 4px;color:#7e8da4;font-size:11px;letter-spacing:.03em}.mobile-ai-card h2{margin:0;color:#26364e;font-size:18px;line-height:1.35}.mobile-ai-help{margin:6px 0 0;color:#8a97aa;font-size:12px;line-height:1.55;overflow-wrap:anywhere}.mobile-ai-prompt{margin-top:16px}.mobile-ai-prompt textarea{display:block;width:100%;min-height:104px;resize:vertical;border:1px solid #dbe4f0;border-radius:12px;padding:13px;color:#33455e;background:#fbfcff;font:inherit;font-size:16px;line-height:1.55;outline:0}.mobile-ai-prompt textarea:focus{border-color:#3b82f6;box-shadow:0 0 0 3px #3b82f61c}.mobile-ai-prompt-foot{display:grid;gap:9px;margin-top:10px}.mobile-ai-prompt-foot>span{color:#8b99ac;font-size:11px;line-height:1.5}.mobile-ai-primary,.mobile-ai-secondary{display:inline-flex;align-items:center;justify-content:center;min-height:46px;border-radius:10px;padding:10px 16px;font-size:14px;font-weight:600;cursor:pointer}.mobile-ai-primary{border:0;background:#2563eb;color:#fff}.mobile-ai-primary:disabled,.mobile-ai-secondary:disabled{opacity:.58;cursor:wait}.mobile-ai-secondary{border:1px solid #d7e1ee;background:#fff;color:#50617a}.mobile-ai-fallback{margin:12px 0 0;padding:11px 12px;border-radius:10px;background:#fff8e7;color:#876823;font-size:12px;line-height:1.55;overflow-wrap:anywhere}.mobile-ai-fallback a{color:#2563eb;margin-left:4px}.mobile-ai-section-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;padding:16px;border-bottom:1px solid #edf1f6}.mobile-ai-section-head>div{min-width:0}.mobile-ai-section-head h2{font-size:16px}.mobile-ai-quiet-button{display:inline-flex;align-items:center;justify-content:center;flex:0 0 auto;min-height:42px;padding:8px 8px;border:0;border-radius:9px;background:#f1f5fb;color:#2563eb;font-size:12px;cursor:pointer}.mobile-ai-thread{display:grid;gap:11px;padding:15px 13px 17px}.mobile-ai-message{display:flex;align-items:flex-start;gap:8px;max-width:100%;min-width:0}.mobile-ai-message.is-user{flex-direction:row-reverse;scroll-margin-top:82px}.mobile-ai-avatar{display:grid;place-items:center;flex:0 0 28px;width:28px;height:28px;border-radius:9px;background:#edf4ff;color:#2563eb;font-size:11px;font-weight:600}.is-user .mobile-ai-avatar{background:#eef2f8;color:#52617a}.mobile-ai-message p{min-width:0;margin:0;padding:10px 11px;border-radius:12px;background:#f5f8fc;color:#52627a;font-size:13px;line-height:1.6;overflow-wrap:anywhere;word-break:break-word}.mobile-ai-message.is-user p{background:#2563eb;color:#fff}.mobile-ai-bubble{min-width:0;display:grid;gap:6px}.mobile-ai-message.is-chat .mobile-ai-bubble p{white-space:pre-wrap}.mobile-ai-message-link{color:#2563eb;font-size:12px;font-weight:600;text-decoration:none;min-height:32px;display:inline-flex;align-items:center}.mobile-ai-draft{padding-bottom:16px}.mobile-ai-card-note{margin:0;padding:13px 16px 0;color:#8b98aa;font-size:12px;line-height:1.55}.mobile-ai-status,.mobile-ai-history-status{display:inline-flex;align-items:center;min-height:27px;padding:4px 8px;border-radius:99px;background:#fff4da;color:#896923;font-size:10px;white-space:nowrap}.mobile-ai-warning{margin:13px 16px 0;padding:10px 11px;border-radius:9px;background:#fff8e7;color:#896823;font-size:12px;line-height:1.55;overflow-wrap:anywhere}.mobile-ai-draft-form{display:grid;gap:11px;padding:15px 16px 0}.mobile-ai-draft-form>label{display:block;color:#53637a;font-size:12px;line-height:1.45}.mobile-ai-draft-form input,.mobile-ai-draft-form select,.mobile-ai-draft-form textarea{display:block;width:100%;min-height:46px;margin-top:6px;border:1px solid #dbe4f0;border-radius:10px;padding:10px 11px;background:#fff;color:#3f5068;font:inherit;font-size:16px;outline:0}.mobile-ai-draft-form textarea{min-height:70px;resize:vertical}.mobile-ai-draft-form input:focus,.mobile-ai-draft-form select,.mobile-ai-draft-form textarea:focus{border-color:#3b82f6}.mobile-ai-segmented{display:grid;grid-template-columns:1fr 1fr;gap:4px;padding:4px;border-radius:11px;background:#f0f4fa}.mobile-ai-segmented button{min-height:44px;border:0;border-radius:8px;background:transparent;color:#7c8ba1;font-size:13px;cursor:pointer}.mobile-ai-segmented button.selected{background:#fff;color:#2563eb;box-shadow:0 1px 5px #263b6114;font-weight:600}.mobile-ai-ledger{padding:11px;border:1px solid #dbe6f5;border-radius:10px;background:#f8fbff}.mobile-ai-check{display:flex!important;align-items:center;gap:9px;min-height:42px;color:#42536c;font-size:13px;font-weight:600}.mobile-ai-check input{width:20px;height:20px;margin:0;accent-color:#2563eb}.mobile-ai-ledger-hint{margin:6px 0 0;color:#9a6d26;font-size:12px;line-height:1.5}.mobile-ai-ledger-fields{display:grid;gap:8px;margin-top:9px}.mobile-ai-ledger-fields label{color:#53637a;font-size:12px}.mobile-ai-ledger-fields select{margin-top:5px}.mobile-ai-ledger-fields>span{color:#53627a;font-size:12px;line-height:1.5;overflow-wrap:anywhere}.mobile-ai-form-error{margin:0;padding:10px 11px;border-radius:9px;background:#fff0f0;color:#a83232;font-size:12px;line-height:1.55;overflow-wrap:anywhere}.mobile-ai-form-actions{display:grid;gap:8px;margin-top:3px}.mobile-ai-history{margin-bottom:8px}.mobile-ai-state{min-height:120px;display:grid;place-content:center;justify-items:center;padding:20px 16px;color:#8997aa;text-align:center;font-size:13px}.mobile-ai-state p{margin:0;line-height:1.5}.mobile-ai-state.is-error{color:#b54e58}.mobile-ai-history-list{list-style:none;margin:0;padding:0 16px}.mobile-ai-history-list li{display:grid;grid-template-columns:30px minmax(0,1fr) auto;align-items:start;gap:9px;padding:14px 0;border-bottom:1px solid #edf1f6}.mobile-ai-history-list li:last-child{border-bottom:0}.mobile-ai-history-icon{display:grid;place-items:center;width:30px;height:30px;border-radius:9px;background:#edf4ff;color:#2563eb;font-size:14px}.mobile-ai-history-copy{min-width:0}.mobile-ai-history-copy strong{display:block;color:#506078;font-size:13px;line-height:1.45;overflow-wrap:anywhere;word-break:break-word}.mobile-ai-history-copy time{display:block;margin-top:3px;color:#9ba6b6;font-size:10px}.mobile-ai-history-copy p{margin:6px 0 0;color:#7b8aa0;font-size:12px;line-height:1.5;overflow-wrap:anywhere;word-break:break-word}.mobile-ai-history-status{align-self:start;background:#e7f8f0;color:#12845e}.mobile-ai-history-status.is-error{background:#fff0f0;color:#c84d54}.mobile-ai-spinner{display:inline-block;width:15px;height:15px;margin-right:5px;border:2px solid #ffffff66;border-top-color:#fff;border-radius:50%;animation:mobile-ai-spin .7s linear infinite;vertical-align:-3px}.mobile-ai-spinner.dark{margin:0;border-color:#dce7f8;border-top-color:#2563eb}@keyframes mobile-ai-spin{to{transform:rotate(360deg)}}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media(max-width:380px){.mobile-ai-compose{padding-left:13px;padding-right:13px}.mobile-ai-section-head{padding-left:13px;padding-right:13px}.mobile-ai-card-note,.mobile-ai-warning{margin-left:13px;margin-right:13px}.mobile-ai-card-note{padding-left:0;padding-right:0}.mobile-ai-draft-form{padding-left:13px;padding-right:13px}.mobile-ai-history-list{padding-left:13px;padding-right:13px}.mobile-ai-history-list li{grid-template-columns:30px minmax(0,1fr)}.mobile-ai-history-status{grid-column:2;justify-self:start;margin-top:3px}}
.mobile-ai-hero{padding:14px 16px 16px;background:linear-gradient(145deg,#ffffff 0%,#f5f9ff 100%);border-color:#dce8fa}.mobile-ai-hero-top{display:flex;align-items:center;justify-content:space-between;gap:10px;min-height:30px;margin-bottom:13px}.mobile-ai-back{display:inline-flex;align-items:center;min-height:38px;color:#71819a;font-size:12px;text-decoration:none}.mobile-ai-back:hover{color:#2563eb}.mobile-ai-mode-pill{display:inline-flex;align-items:center;gap:5px;min-height:27px;padding:4px 9px;border:1px solid #cde0ff;border-radius:99px;background:#edf5ff;color:#2563eb;font-size:10px;font-weight:700;white-space:nowrap}.mobile-ai-mode-pill>span{font-size:8px}.mobile-ai-flow{display:flex;align-items:center;gap:7px;margin-top:15px;color:#a4b0c0;font-size:10px}.mobile-ai-flow span{display:inline-flex;align-items:center;gap:4px;white-space:nowrap}.mobile-ai-flow span b{display:grid;place-items:center;width:20px;height:20px;border-radius:50%;background:#edf1f7;color:#8290a4;font-size:10px}.mobile-ai-flow span.is-active{color:#2563eb;font-weight:600}.mobile-ai-flow span.is-active b{background:#2563eb;color:#fff}.mobile-ai-flow i{font-style:normal;color:#b6c1cf}.mobile-ai-parser-row{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin-top:10px;padding:7px 9px;border-radius:9px;background:#f8faff;color:#7c8ba0;font-size:10px;line-height:1.4}.mobile-ai-parser-badge{display:inline-flex;align-items:center;gap:4px;padding:4px 7px;border:1px solid #cfe0fa;border-radius:99px;background:#edf5ff;color:#2563eb;font-weight:700;white-space:nowrap}.mobile-ai-parser-badge.is-local{border-color:#f1d79e;background:#fff7e5;color:#8b6119}.mobile-ai-suggestions{display:flex;gap:7px;margin-top:9px;overflow-x:auto;padding-bottom:2px;scrollbar-width:none}.mobile-ai-suggestions::-webkit-scrollbar{display:none}.mobile-ai-suggestions button{flex:0 0 auto;min-height:34px;border:1px solid #dbe6f5;border-radius:99px;background:#fff;color:#60718a;padding:6px 10px;font-size:11px;white-space:nowrap;cursor:pointer}.mobile-ai-suggestions button:hover,.mobile-ai-suggestions button:focus-visible{border-color:#9fc2f8;color:#2563eb;outline:0}.mobile-ai-suggestions button:disabled{opacity:.55;cursor:wait}.mobile-ai-prompt-status{display:flex;align-items:center;gap:5px}.mobile-ai-status-dot{width:6px;height:6px;border-radius:50%;background:#3b82f6;box-shadow:0 0 0 3px #3b82f61a}.mobile-ai-source-warning{display:grid;grid-template-columns:25px minmax(0,1fr);gap:9px;margin-top:12px;padding:11px 12px;border:1px solid #d9e6f8;border-radius:10px;background:#f5f9ff;color:#536680}.mobile-ai-source-warning.is-local{border-color:#efd9a8;background:#fff8e9;color:#78551a}.mobile-ai-source-warning-icon{display:grid;place-items:center;width:25px;height:25px;border-radius:8px;background:#e6f0ff;color:#2563eb;font-size:12px;font-weight:800}.mobile-ai-source-warning.is-local .mobile-ai-source-warning-icon{background:#fbe9bd;color:#8b6119}.mobile-ai-source-warning>div{min-width:0}.mobile-ai-source-warning strong{display:block;font-size:12px;line-height:1.4}.mobile-ai-source-warning p{margin:3px 0 0;font-size:11px;line-height:1.55;overflow-wrap:anywhere}.mobile-ai-source-warning a{display:inline-flex;align-items:center;min-height:34px;margin-top:3px;color:#2563eb;font-size:11px;font-weight:600;text-decoration:none}.mobile-ai-manual-switch{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:14px;padding-top:13px;border-top:1px solid #e8eef7;color:#8290a4;font-size:11px;line-height:1.45}.mobile-ai-manual-switch a{display:inline-flex;align-items:center;gap:4px;min-height:38px;color:#526984;font-size:11px;font-weight:600;text-decoration:none;white-space:nowrap}.mobile-ai-manual-switch a:hover{color:#2563eb}.mobile-ai-fallback a{display:inline-flex;min-height:28px;align-items:center;color:#2563eb;font-weight:600;text-decoration:none}.mobile-ai-subcopy{margin:4px 0 0;color:#96a2b3;font-size:11px;line-height:1.45;overflow-wrap:anywhere}.mobile-ai-session-actions{display:flex;align-items:center;justify-content:flex-end;gap:5px;flex:0 0 auto}.mobile-ai-quiet-button.is-muted{background:#f7f9fc;color:#75849a}.mobile-ai-quiet-button:disabled{opacity:.52;cursor:wait}.mobile-ai-draft-banner{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:10px;margin:14px 16px 0;padding:12px 13px;border-radius:11px;background:#f2f7ff;border:1px solid #dbe8fb}.mobile-ai-draft-banner>span{color:#2563eb;font-size:11px;font-weight:700}.mobile-ai-draft-banner strong{color:#253b5d;font-size:21px;line-height:1.1}.mobile-ai-draft-banner strong small{font-size:11px;font-weight:500}.mobile-ai-draft-banner em{color:#8b99ac;font-size:10px;font-style:normal;white-space:nowrap}.mobile-ai-reset-link{display:block;margin:4px auto 0;border:0;background:transparent;color:#98a4b4;font-size:11px;line-height:1.5;cursor:pointer;min-height:34px;padding:6px 10px}.mobile-ai-reset-link:hover{color:#d45b63}.mobile-ai-reset-link:disabled{opacity:.5;cursor:wait}.mobile-ai-hero .mobile-ai-card-heading{align-items:flex-start}.mobile-ai-hero .mobile-ai-help{max-width:33em}
@media(max-width:380px){.mobile-ai-hero{padding-left:13px;padding-right:13px}.mobile-ai-manual-switch{align-items:flex-start;flex-direction:column;gap:3px}.mobile-ai-manual-switch a{min-height:36px}.mobile-ai-draft-banner{grid-template-columns:auto 1fr; margin-left:13px;margin-right:13px}.mobile-ai-draft-banner em{grid-column:2}.mobile-ai-session-actions{gap:2px}.mobile-ai-quiet-button{padding-left:6px;padding-right:6px;font-size:11px}.mobile-ai-flow{gap:4px}.mobile-ai-flow i{font-size:9px}}
.mobile-ai-partner-draft{position:relative;border-color:#d8e5f6;box-shadow:0 8px 26px #213b6114}.mobile-ai-partner-draft:before{content:"";position:absolute;inset:0 0 auto;height:3px;background:linear-gradient(90deg,#2563eb,#60a5fa 58%,#d8e7fa);z-index:2}.mobile-ai-partner-draft>.mobile-ai-section-head{background:linear-gradient(145deg,#fff,#f6f9ff)}
.mobile-ai-partner-banner{display:grid;grid-template-columns:40px minmax(0,1fr);align-items:center;gap:10px;margin:13px 16px 0;padding:12px 13px;border:1px solid #d9e6f5;border-radius:12px;background:linear-gradient(145deg,#f9fbff,#f1f6fd)}.mobile-ai-partner-icon{display:grid;place-items:center;width:40px;height:40px;border-radius:12px;background:linear-gradient(145deg,#e7f1ff,#dbe9ff);color:#2563eb;font-size:13px;font-weight:700;box-shadow:0 2px 6px #315e9e1a}.mobile-ai-partner-banner>div{min-width:0}.mobile-ai-partner-banner strong{display:block;color:#35465f;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.mobile-ai-partner-banner small{display:block;margin-top:3px;color:#8a98aa;font-size:10px}.mobile-ai-partner-banner em{grid-column:2;justify-self:start;margin-top:-4px;padding:4px 7px;border:1px solid #d5e3f4;border-radius:99px;background:#fff;color:#55708f;font-size:9px;font-style:normal}
.mobile-ai-partner-entries{display:grid;gap:10px}.mobile-ai-partner-entry{position:relative;padding:14px;border:1px solid #dce7f5;border-radius:14px;background:#fff;box-shadow:0 5px 16px #243b5a0a;overflow:hidden}.mobile-ai-partner-entry:before{content:"";position:absolute;inset:0 0 auto;height:3px;background:linear-gradient(90deg,#2563eb,#79aaf0)}.mobile-ai-partner-entry>header{display:flex;align-items:center;gap:9px;min-width:0}.mobile-ai-partner-entry>header>div{min-width:0;flex:1}.mobile-ai-partner-entry>header strong{display:block;color:#32445e;font-size:13px;line-height:1.4}.mobile-ai-partner-entry>header small{display:block;margin-top:2px;color:#8a98ab;font-size:10px}.mobile-ai-partner-entry>header em{padding:4px 7px;border-radius:99px;background:#edf5ff;color:#2563eb;font-size:9px;font-style:normal;white-space:nowrap}.mobile-ai-entry-icon{display:grid;place-items:center;flex:0 0 31px;width:31px;height:31px;border-radius:9px;background:#e9f2ff;color:#2563eb;font-size:15px;font-weight:700}
.mobile-ai-balance-compare{display:grid;gap:7px;margin-top:12px}.mobile-ai-balance-compare>div,.mobile-ai-balance-compare>label{display:block;padding:11px 12px;border:1px solid #e0e9f4;border-radius:11px;background:#f9fbfd}.mobile-ai-balance-compare>div span,.mobile-ai-balance-compare>label{color:#7f8da1;font-size:11px}.mobile-ai-balance-compare>div strong{display:block;margin-top:5px;color:#40516a;font-size:18px}.mobile-ai-balance-compare>span{height:17px;display:grid;place-items:center;color:#7ea2d6;font-size:15px}.mobile-ai-balance-compare>label{background:#f4f8ff;border-color:#cfe0f5}.mobile-ai-balance-compare input{display:block;width:100%;min-height:45px;margin-top:6px;border:1px solid #cbdced;border-radius:9px;padding:9px 10px;background:#fff;color:#30445f;font:inherit;font-size:17px;font-weight:700;outline:0}.mobile-ai-balance-compare input:focus{border-color:#3b82f6;box-shadow:0 0 0 3px #3b82f617}
.mobile-ai-entry-details{display:grid;gap:10px;margin-top:11px;padding-top:11px;border-top:1px solid #edf1f6}.mobile-ai-entry-details label{display:block;color:#53637a;font-size:11px}.mobile-ai-entry-details input,.mobile-ai-entry-details textarea{display:block;width:100%;min-height:45px;margin-top:5px;border:1px solid #dbe4f0;border-radius:9px;padding:9px 10px;background:#fff;color:#3f5068;font:inherit;font-size:16px;outline:0}.mobile-ai-entry-details textarea{min-height:68px;resize:vertical}.mobile-ai-entry-details input:focus,.mobile-ai-entry-details textarea:focus{border-color:#3b82f6;box-shadow:0 0 0 3px #3b82f612}
.mobile-ai-entry-preview{display:flex;align-items:flex-start;gap:7px;margin:11px 0 0;padding:9px 10px;border-radius:9px;background:#f0f7ff;color:#527098;font-size:11px;line-height:1.5}.mobile-ai-entry-preview>span{display:grid;place-items:center;flex:0 0 18px;width:18px;height:18px;border-radius:50%;background:#dcecff;color:#2563eb;font-size:9px;font-weight:700}.mobile-ai-entry-single-hint{display:flex;align-items:flex-start;gap:7px;margin:0;padding:10px 11px;border-radius:10px;background:#f7f9fc;color:#748298;font-size:11px;line-height:1.5}.mobile-ai-entry-single-hint>span{display:grid;place-items:center;flex:0 0 19px;width:19px;height:19px;border-radius:6px;background:#e8eef7;color:#55708f;font-size:10px;font-weight:700}
.mobile-ai-reconciliation-toggle{display:flex!important;align-items:flex-start;gap:9px;padding:11px 12px;border:1px solid #d7e4f4;border-radius:10px;background:#f7fbff;color:#596b84;font-size:12px;line-height:1.45}.mobile-ai-reconciliation-toggle input{flex:0 0 20px;width:20px!important;min-height:20px!important;margin:1px 0 0!important;accent-color:#2563eb}.mobile-ai-reconciliation-toggle>span{min-width:0}.mobile-ai-reconciliation-toggle strong{display:block;color:#40536e;font-size:12px}.mobile-ai-reconciliation-toggle small{display:block;margin-top:3px;color:#8290a4;font-size:10px;line-height:1.45}.mobile-ai-transfer-hint{margin:0;padding:10px 11px;border:1px solid #dbe6f5;border-radius:9px;background:#f8fbff;color:#596b84;font-size:12px;line-height:1.5}
@media(max-width:380px){.mobile-ai-partner-banner{margin-left:13px;margin-right:13px}.mobile-ai-partner-entry{padding:13px}}
.mobile-ai-combined-panel{position:relative;padding:14px;background:linear-gradient(145deg,#fbfdff 0%,#f3f7fd 100%);border-color:#d9e6f5;box-shadow:0 8px 20px #27415f0e,inset 0 1px 0 #fff;overflow:hidden}
.mobile-ai-combined-panel:before{content:"";position:absolute;inset:0 0 auto 0;height:3px;background:linear-gradient(90deg,#2563eb 0%,#60a5fa 55%,#c7d7f1 100%)}
.mobile-ai-combined-head{display:flex;align-items:center;gap:9px;min-width:0;position:relative;z-index:1}
.mobile-ai-combined-head>div{min-width:0;flex:1}
.mobile-ai-combined-head strong{display:block;color:#2f3f58;font-size:13px;line-height:1.4}
.mobile-ai-combined-head span:not(.mobile-ai-combined-icon){display:block;margin-top:2px;color:#7e8da4;font-size:10px;line-height:1.45}
.mobile-ai-combined-head em{flex:0 0 auto;padding:4px 7px;border:1px solid #cfe0f6;border-radius:99px;background:#edf5ff;color:#2563eb;font-size:9px;font-style:normal;white-space:nowrap}
.mobile-ai-combined-icon{display:grid;place-items:center;flex:0 0 30px;width:30px;height:30px;border-radius:9px;background:linear-gradient(145deg,#e8f1ff 0%,#dce9ff 100%);color:#2563eb;font-size:15px;font-weight:700;box-shadow:0 1px 3px #2c5aa51a}
.mobile-ai-combined-summary{display:grid;gap:7px;margin-top:11px;position:relative;z-index:1}
.mobile-ai-combined-summary>div{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 11px;border:1px solid #e1e9f4;border-radius:10px;background:rgba(255,255,255,.92)}
.mobile-ai-combined-summary small{color:#92a0b2;font-size:10px;letter-spacing:.02em;text-transform:uppercase}
.mobile-ai-combined-summary strong{min-width:0;color:#42536c;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mobile-ai-combined-fields{display:grid;gap:9px;margin-top:11px;padding-top:11px;border-top:1px solid #e1e9f4;position:relative;z-index:1}
.mobile-ai-combined-fields label{color:#53637a;font-size:11px}
.mobile-ai-combined-fields input,.mobile-ai-combined-fields select{display:block;width:100%;margin-top:5px;border:1px solid #d6e1ee;border-radius:10px;padding:10px 11px;background:#fff;color:#3f5068;font:inherit;font-size:16px;outline:0}
.mobile-ai-combined-fields input:focus,.mobile-ai-combined-fields select:focus{border-color:#75a7ef;box-shadow:0 0 0 3px #3b82f61a}
.mobile-ai-combined-hint{margin:8px 0 0;color:#8a6924;font-size:12px;line-height:1.5;position:relative;z-index:1}
.mobile-ai-combined-panel .mobile-ai-ledger-hint{margin:9px 0 0}
.mobile-ai-brief-comment{display:grid;grid-template-columns:28px minmax(0,1fr);gap:9px;margin:11px 16px 0;padding:11px 12px;border:1px solid #dbe8fb;border-radius:10px;background:linear-gradient(145deg,#f7faff,#fff)}.mobile-ai-brief-comment>span{display:grid;place-items:center;width:28px;height:28px;border-radius:8px;background:#e8f1ff;color:#2563eb;font-size:13px}.mobile-ai-brief-comment strong{display:block;color:#41536d;font-size:11px}.mobile-ai-brief-comment p{margin:3px 0 0;color:#61728a;font-size:12px;line-height:1.55;overflow-wrap:anywhere}@media(max-width:380px){.mobile-ai-brief-comment{margin-left:13px;margin-right:13px}}
.mobile-ai-page{padding-bottom:190px}.mobile-ai-composer{position:fixed;right:max(10px,env(safe-area-inset-right,0px));bottom:calc(72px + env(safe-area-inset-bottom,0px));left:max(10px,env(safe-area-inset-left,0px));z-index:45;margin:0;padding:8px;border:1px solid #d8e6f8;border-radius:16px;box-shadow:0 10px 32px #23436d2b}.mobile-ai-composer .mobile-ai-prompt{margin:0}.mobile-ai-composer .mobile-ai-prompt textarea{min-height:42px;max-height:100px;resize:vertical;padding:10px 12px;font-size:16px}.mobile-ai-composer .mobile-ai-suggestions{margin-top:7px}.mobile-ai-composer .mobile-ai-prompt-foot{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:7px}.mobile-ai-composer .mobile-ai-prompt-status{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.mobile-ai-send{display:grid;place-items:center;flex:0 0 42px;width:42px;height:42px;border:0;border-radius:50%;background:#2563eb;color:#fff;font-size:22px;line-height:1;box-shadow:0 4px 10px #2563eb38;cursor:pointer}.mobile-ai-send:disabled{opacity:.45;cursor:wait;box-shadow:none}.mobile-ai-send .mobile-ai-spinner{margin:0}.mobile-ai-parsing-message p{display:inline-flex;align-items:center;gap:8px;color:#7e8da4}.mobile-ai-typing-dots{display:inline-flex;align-items:center;gap:3px}.mobile-ai-typing-dots i{width:5px;height:5px;border-radius:50%;background:#8ba5ce;animation:mobile-ai-typing 1.1s infinite ease-in-out}.mobile-ai-typing-dots i:nth-child(2){animation-delay:.15s}.mobile-ai-typing-dots i:nth-child(3){animation-delay:.3s}@keyframes mobile-ai-typing{0%,60%,100%{opacity:.35;transform:translateY(0)}30%{opacity:1;transform:translateY(-2px)}}@media(max-width:380px){.mobile-ai-composer{right:7px;left:7px;padding:7px}.mobile-ai-page{padding-bottom:184px}}
</style>
