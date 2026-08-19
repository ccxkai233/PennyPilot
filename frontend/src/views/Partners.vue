<template>
  <AppLayout title="往来账户" :subtitle="subtitle" :notice="notice">
    <template #actions>
      <router-link class="secondary-link" to="/ai">✦ AI 记账</router-link>
      <button class="primary" type="button" @click="openCreate">{{ isMobile ? '新增账户' : '＋ 新增账户' }}</button>
    </template>

    <MobilePartners v-if="isMobile" :partners="partners" :filtered-partners="filteredPartners" :filters="filters" :loading="loading" :error-message="errorMessage" :modal-open="modalOpen" :detail-open="detailOpen" :ledger-entry-open="ledgerEntryOpen" :editing="editing" :selected-partner="selectedPartner" :ledger="ledger" :ledger-loading="ledgerLoading" :ledger-error="ledgerError" :saving="saving" :form-error="formError" :form="form" :ledger-form="ledgerForm" :ledger-saving="ledgerSaving" :ledger-form-error="ledgerFormError" :selected-partner-ledger-options="selectedPartnerLedgerOptions" :partner-name="partnerName" :partner-type="partnerType" :type-label="typeLabel" :type-icon="typeIcon" :type-class="typeClass" :is-archived="isArchived" :contact-text="contactText" :website-url="websiteUrl" :website-href="websiteHref" :legacy-email="legacyEmail" :prepaid-cents="prepaidCents" :credit-limit-cents="creditLimitCents" :credit-used-cents="creditUsedCents" :balance-class="balanceClass" :ledger-type-label="ledgerTypeLabel" :ledger-delta="ledgerDelta" :reset-filters="resetFilters" :load-partners="loadPartners" :open-create="openCreate" :open-edit="openEdit" :toggle-archive="toggleArchive" :open-detail="openDetail" :close-modal="closeModal" :close-detail="closeDetail" :load-ledger="loadLedger" :open-ledger-entry="openLedgerEntry" :close-ledger-entry="closeLedgerEntry" :save-partner="savePartner" :save-ledger-entry="saveLedgerEntry" :reverse-ledger-entry="reverseLedgerEntry" />
    <template v-else>

    <section class="toolbar panel">
      <label class="search-field"><span>搜索账户</span><input v-model.trim="filters.search" type="search" placeholder="名称、联系人或备注" /></label>
      <label class="type-field"><span>账户类型</span><select v-model="filters.type"><option value="">全部</option><option value="supplier">供应商</option><option value="customer">客户</option></select></label>
      <label class="status-field"><span>状态</span><select v-model="filters.status"><option value="active">启用</option><option value="">全部</option><option value="archived">已归档</option></select></label>
      <button class="outline-button" type="button" @click="resetFilters">重置</button>
    </section>

    <section class="panel list-panel">
      <div class="panel-head">
        <div><h2>账户列表</h2><p>记录供应商、客户的未结算余额</p></div>
        <span class="muted-count">{{ filteredPartners.length }} 个账户</span>
      </div>
      <div v-if="loading" class="state"><span class="spinner dark"></span><p>正在加载往来账户…</p></div>
      <div v-else-if="errorMessage" class="state error-state"><p>{{ errorMessage }}</p><button class="outline-button" type="button" @click="loadPartners">重试</button></div>
      <div v-else-if="filteredPartners.length === 0" class="state"><div class="empty-icon">♧</div><h3>{{ partners.length ? '没有匹配的账户' : '还没有往来账户' }}</h3><p>{{ partners.length ? '试试调整搜索或筛选条件。' : '新增一个客户或供应商，开始追踪资金往来。' }}</p><button class="primary small" type="button" @click="openCreate">＋ 新增账户</button></div>
      <div v-else class="partner-grid">
        <article v-for="partner in filteredPartners" :key="partner.id" class="partner-card" :class="{ archived: isArchived(partner) }" @click="openDetail(partner)">
          <div class="partner-card-head">
            <div class="partner-avatar" :class="typeClass(partner)">{{ typeIcon(partner) }}</div>
            <div class="partner-title"><h3>{{ partnerName(partner) }}</h3><span>{{ typeLabel(partner) }}</span></div>
            <span class="status-pill" :class="isArchived(partner) ? 'status-archived' : 'status-active'">{{ isArchived(partner) ? '已归档' : '启用' }}</span>
          </div>
          <div class="contact-line" v-if="contactText(partner)">⌁ {{ contactText(partner) }}</div>
          <a v-if="websiteUrl(partner) && websiteHref(partner)" class="website-line" :href="websiteHref(partner)" target="_blank" rel="noopener noreferrer" @click.stop>↗ {{ websiteUrl(partner) }}</a>
          <span v-if="legacyEmail(partner)" class="legacy-email-line">邮箱：{{ legacyEmail(partner) }}</span>
          <div class="balance-grid">
            <div><span>未结算余额</span><strong :class="balanceClass(unsettledCents(partner), partnerType(partner) === 'customer')">{{ formatMoney(unsettledCents(partner)) }}</strong></div>
          </div>
          <div class="partner-card-foot"><span>更新于 {{ formatDateTime(partner.updated_at || partner.created_at) }}</span><div><button class="text-button" type="button" @click.stop="openEdit(partner)">编辑</button><button class="text-button danger" type="button" @click.stop="toggleArchive(partner)">{{ isArchived(partner) ? '恢复' : '归档' }}</button></div></div>
        </article>
      </div>
    </section>

    <Teleport to="body">
      <div v-if="modalOpen" class="modal-backdrop" @click.self="closeModal">
        <section class="modal" role="dialog" aria-modal="true" :aria-labelledby="editing ? 'partner-edit-title' : 'partner-create-title'">
          <div class="modal-header"><div><h2 :id="editing ? 'partner-edit-title' : 'partner-create-title'">{{ editing ? '编辑往来账户' : '新增往来账户' }}</h2><p>未结算余额按元填写，系统按分保存</p></div><button class="modal-close" type="button" aria-label="关闭" @click="closeModal">×</button></div>
          <div v-if="formError" class="form-error" role="alert">{{ formError }}</div>
          <form class="partner-form" @submit.prevent="savePartner">
            <div class="form-grid"><label>账户名称<input v-model.trim="form.name" required maxlength="120" placeholder="例如：华东供应链、王先生" /></label><label>账户类型<select v-model="form.type" required><option value="supplier">供应商</option><option value="customer">客户</option></select></label></div>
            <div class="form-grid"><label>联系人<input v-model.trim="form.contact" maxlength="100" placeholder="可选" /></label><label>电话<input v-model.trim="form.phone" maxlength="40" inputmode="tel" placeholder="可选" /></label></div>
            <label>网址<input v-model.trim="form.website" maxlength="2048" type="url" inputmode="url" placeholder="https://example.com" /></label>
            <label>未结算余额（元）<input v-model.trim="form.unsettled_balance" :disabled="Boolean(editing)" inputmode="decimal" pattern="^[0-9]*([.][0-9]{0,2})?$" placeholder="0.00" /></label>
            <p v-if="editing" class="field-hint">账户余额请在详情中的“记录未结算余额”里调整，确保每次变动都有流水。</p>
            <label>备注（可选）<textarea v-model.trim="form.notes" maxlength="1000" rows="3" placeholder="记录合作约定、结算周期等"></textarea></label>
            <div class="modal-actions"><button class="outline-button" type="button" @click="closeModal">取消</button><button class="primary" type="submit" :disabled="saving"><span v-if="saving" class="spinner"></span>{{ saving ? '保存中…' : '保存账户' }}</button></div>
          </form>
        </section>
      </div>

      <div v-if="detailOpen" class="modal-backdrop" @click.self="closeDetail">
        <section class="detail-modal" role="dialog" aria-modal="true" aria-labelledby="partner-detail-title">
          <div class="modal-header"><div><h2 id="partner-detail-title">{{ partnerName(selectedPartner) }}</h2><p>{{ typeLabel(selectedPartner) }} · 完整往来流水</p></div><button class="modal-close" type="button" aria-label="关闭" @click="closeDetail">×</button></div>
          <div class="detail-summary">
            <div><span>未结算余额</span><strong :class="balanceClass(unsettledCents(selectedPartner), partnerType(selectedPartner) === 'customer')">{{ formatMoney(unsettledCents(selectedPartner)) }}</strong></div>
          </div>
          <div v-if="websiteUrl(selectedPartner) || legacyEmail(selectedPartner)" class="detail-contact">
            <a v-if="websiteUrl(selectedPartner) && websiteHref(selectedPartner)" :href="websiteHref(selectedPartner)" target="_blank" rel="noopener noreferrer">网址：{{ websiteUrl(selectedPartner) }}</a>
            <span v-if="legacyEmail(selectedPartner)">历史邮箱：{{ legacyEmail(selectedPartner) }}</span>
          </div>
          <div class="detail-actions"><router-link class="outline-button link-button" :to="{ path: '/transactions', query: { partner_id: String(selectedPartner?.id || '') } }" @click="closeDetail">查看关联现金收支</router-link><router-link class="outline-button link-button ai-partner-link" :to="{ path: '/ai', query: { partner_id: String(selectedPartner?.id || '') } }" @click="closeDetail">✦ AI 记账</router-link><button class="primary" type="button" @click="openLedgerEntry">＋ 记录未结算余额</button></div>
          <div v-if="ledgerLoading" class="state compact"><span class="spinner dark"></span><p>正在加载流水…</p></div>
          <div v-else-if="ledgerError" class="state compact error-state"><p>{{ ledgerError }}</p><button class="outline-button" type="button" @click="loadLedger">重试</button></div>
          <div v-else-if="ledger.length === 0" class="state compact"><div class="empty-icon">↔</div><h3>暂无往来流水</h3><p>记录未结算余额后会显示在这里。</p></div>
          <div v-else class="ledger-wrap"><table><thead><tr><th>时间</th><th>变动类型</th><th>金额</th><th>余额</th><th>备注</th><th>操作</th></tr></thead><tbody><tr v-for="entry in ledger" :key="entry.id || `${entry.occurred_at}-${entry.amount_cents}`"><td data-label="时间">{{ formatDateTime(entry.occurred_at || entry.occurred_time || entry.created_at) }}</td><td data-label="变动类型"><span class="ledger-type">{{ ledgerTypeLabel(entry) }}</span></td><td data-label="金额" class="ledger-amount" :class="ledgerDelta(entry) >= 0 ? 'income-text' : 'expense-text'">{{ ledgerDelta(entry) >= 0 ? '+' : '−' }}{{ formatMoney(Math.abs(ledgerDelta(entry)), '') }}</td><td data-label="余额">{{ formatMoney(entry.balance_after_cents ?? entry.after_balance_cents ?? entry.balance_cents ?? 0) }}</td><td data-label="备注" class="ledger-notes">{{ entry.notes || entry.note || '—' }}</td><td data-label="操作"><button v-if="entry.status !== 'reversed' && !entry.reversed_entry_id && !entry.reversal_of_id" class="text-button danger" type="button" @click="reverseLedgerEntry(entry)">冲正</button><span v-else class="reversed-label">已冲正</span></td></tr></tbody></table></div>
        </section>
      </div>
      <div v-if="ledgerEntryOpen" class="modal-backdrop" @click.self="closeLedgerEntry">
        <section class="modal ledger-entry-modal" role="dialog" aria-modal="true" aria-labelledby="ledger-entry-title">
          <div class="modal-header"><div><h2 id="ledger-entry-title">记录未结算余额</h2><p>{{ partnerName(selectedPartner) }} · 余额与流水会原子更新</p></div><button class="modal-close" type="button" aria-label="关闭" @click="closeLedgerEntry">×</button></div>
          <div v-if="ledgerFormError" class="form-error" role="alert">{{ ledgerFormError }}</div>
          <form class="partner-form" @submit.prevent="saveLedgerEntry">
            <label>未结算余额（元）<input v-model.trim="ledgerForm.balance" inputmode="decimal" required placeholder="0.00" /></label>
            <label>发生时间<input v-model="ledgerForm.occurred_at" type="datetime-local" required /></label>
            <label>备注（可选）<textarea v-model.trim="ledgerForm.notes" rows="3" maxlength="500" placeholder="说明这次变动"></textarea></label>
            <div class="modal-actions"><button class="outline-button" type="button" @click="closeLedgerEntry">取消</button><button class="primary" type="submit" :disabled="ledgerSaving"><span v-if="ledgerSaving" class="spinner"></span>{{ ledgerSaving ? '保存中…' : '确认记录' }}</button></div>
          </form>
        </section>
      </div>
    </Teleport>
    </template>
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
import { computed, onMounted, reactive, ref } from 'vue'
import AppLayout from '../components/AppLayout.vue'
import ConfirmDialog from '../components/ConfirmDialog.vue'
import { useViewport } from '../composables/useViewport'
import { useConfirmDialog } from '../composables/useConfirmDialog'
import MobilePartners from './MobilePartners.vue'
import { ApiError, amountToCents, centsToAmount, datetimeLocalToUtcIso, formatDateTime, formatMoney, localDateTimeValue, partnersApi } from '../api'

const partners = ref([])
const loading = ref(false)
const errorMessage = ref('')
const notice = ref(null)
const filters = reactive({ search: '', type: '', status: 'active' })
const modalOpen = ref(false)
const detailOpen = ref(false)
const ledgerEntryOpen = ref(false)
const editing = ref(null)
const selectedPartner = ref(null)
const ledger = ref([])
const ledgerLoading = ref(false)
const ledgerError = ref('')
const saving = ref(false)
const formError = ref('')
const form = reactive({ name: '', type: 'supplier', contact: '', phone: '', website: '', unsettled_balance: '', notes: '' })
const ledgerForm = reactive({ balance: '', occurred_at: localDateTimeValue(), notes: '' })
const ledgerSaving = ref(false)
const ledgerFormError = ref('')
const { isMobile } = useViewport()
const { confirmDialog, requestConfirm, resolveConfirm } = useConfirmDialog()
const PARTNER_LEDGER_OPTIONS = {
  customer: [
    { value: 'prepaid_in', label: '预存充值（增加预存）' },
    { value: 'credit_repay', label: '授信还款（减少欠款）' },
    { value: 'limit_adjust', label: '调整授信额度' },
    { value: 'refund', label: '退款（减少预存）' },
    { value: 'balance_check', label: '余额盘点（不改变余额）' },
  ],
  supplier: [
    { value: 'prepaid_in', label: '预存充值（增加预存）' },
    { value: 'credit_use', label: '授信付款（增加欠款）' },
    { value: 'balance_check', label: '余额盘点（不改变余额）' },
  ],
}
function ledgerOptionsForType(type) { return PARTNER_LEDGER_OPTIONS[String(type || '').toLowerCase()] || PARTNER_LEDGER_OPTIONS.supplier }
function defaultLedgerEntryType(type) { return ledgerOptionsForType(type)[0]?.value || 'prepaid_in' }

const subtitle = computed(() => `${partners.value.filter((item) => !isArchived(item)).length} 个启用账户`)
const filteredPartners = computed(() => partners.value.filter((item) => {
  const wanted = filters.search.toLowerCase()
  const haystack = [partnerName(item), contactText(item), websiteUrl(item), legacyEmail(item), item.notes].filter(Boolean).join(' ').toLowerCase()
  return (!wanted || haystack.includes(wanted)) && (!filters.type || partnerType(item) === filters.type) && (!filters.status || (filters.status === 'archived' ? isArchived(item) : !isArchived(item)))
}))

function partnerName(item) { return item?.name || item?.title || item?.display_name || '未命名账户' }
function partnerType(item) { return String(item?.type || item?.kind || item?.partner_type || item?.category || 'other').toLowerCase() }
function typeLabel(item) { return ({ supplier: '供应商', customer: '客户', other: '其他' })[partnerType(item)] || '往来单位' }
function typeIcon(item) { return ({ supplier: '供', customer: '客', other: '他' })[partnerType(item)] || '往' }
function typeClass(item) { return `type-${partnerType(item)}` }
function isArchived(item) { return item?.is_active === false || ['archived', 'inactive', 'disabled', 'closed'].includes(String(item?.status || '').toLowerCase()) }
function contactText(item) { return item?.contact || item?.contact_name || item?.contact_info || item?.phone || '' }
function websiteUrl(item) { return String(item?.website || item?.url || '').trim() }
function websiteHref(item) {
  const value = websiteUrl(item)
  if (/^https?:\/\//i.test(value)) return value
  if (/^www\./i.test(value)) return `https://${value}`
  return ''
}
function websiteInputValue(item) {
  const value = websiteUrl(item)
  return /^www\./i.test(value) ? 'https://' + value : value
}
function legacyEmail(item) { return String(item?.email || '').trim() }
function numericFirst(item, keys) { for (const key of keys) { const value = Number(item?.[key]); if (Number.isFinite(value)) return value } return 0 }
function amountField(item, centsKeys, amountKeys) { const cents = numericFirst(item, centsKeys); if (cents) return cents; for (const key of amountKeys) { const value = item?.[key]; if (value !== undefined && value !== null && value !== '') { const parsed = amountToCents(value); if (Number.isFinite(parsed)) return parsed } } return 0 }
function prepaidCents(item) { return amountField(item, ['prepaid_balance_cents', 'prepaid_cents', 'current_prepaid_cents', 'current_balance_cents'], ['prepaid_balance', 'prepaid']) }
function creditLimitCents(item) { return amountField(item, ['credit_limit_cents', 'credit_total_cents', 'limit_cents'], ['credit_limit', 'credit_total']) }
function creditUsedCents(item) { return amountField(item, ['credit_used_cents', 'credit_consumed_cents', 'used_credit_cents'], ['credit_used', 'credit_consumed']) }
function unsettledCents(item) {
  const direct = Number(item?.unsettled_balance_cents)
  if (Number.isFinite(direct)) return direct
  return partnerType(item) === 'customer' ? creditUsedCents(item) : prepaidCents(item)
}
function balanceClass(value, reverse = false) { const positive = Number(value) >= 0; return reverse ? (positive ? 'expense-text' : 'income-text') : (positive ? 'income-text' : 'expense-text') }
const selectedPartnerLedgerOptions = computed(() => ledgerOptionsForType(partnerType(selectedPartner.value)))
function ledgerTypeLabel(entry) {
  const type = String(entry?.entry_type || entry?.event_type || entry?.type || entry?.kind || '').toLowerCase()
  if (type === 'credit_use' && partnerType(selectedPartner.value) === 'supplier') return '授信付款'
  return ({ prepaid_in: '预存充值', prepaid_out: '预存扣款', credit_use: '授信使用', credit_repay: '授信还款', limit_adjust: '额度调整', refund: '退款', balance_check: '未结算余额' })[type] || entry?.label || entry?.description || '账户变动'
}
function ledgerDelta(entry) {
  const direct = Number(entry?.delta_cents ?? entry?.change_cents)
  if (Number.isFinite(direct)) return direct
  const amount = Number(entry?.amount_cents ?? entry?.amount ?? 0) || 0
  const type = String(entry?.entry_type || entry?.event_type || entry?.type || entry?.kind || '').toLowerCase()
  if (type === 'limit_adjust') return amount
  return ['prepaid_out', 'refund', 'credit_use'].includes(type) || entry?.direction === 'out' || entry?.direction === 'debit' ? -Math.abs(amount) : Math.abs(amount)
}

function resetFilters() { Object.assign(filters, { search: '', type: '', status: 'active' }) }
function resetForm() { Object.assign(form, { name: '', type: 'supplier', contact: '', phone: '', website: '', unsettled_balance: '', notes: '' }) }
function openCreate() { editing.value = null; formError.value = ''; resetForm(); modalOpen.value = true }
function openEdit(item) { editing.value = item; formError.value = ''; Object.assign(form, { name: partnerName(item), type: partnerType(item), contact: item.contact || item.contact_name || item.contact_info || '', phone: item.phone || '', website: websiteInputValue(item) || (/^https?:\/\//i.test(String(item?.email || '').trim()) ? String(item.email).trim() : ''), unsettled_balance: centsToAmount(unsettledCents(item)), notes: item.notes || item.note || '' }); modalOpen.value = true }
function closeModal() { if (!saving.value) modalOpen.value = false }
function closeDetail() { detailOpen.value = false; selectedPartner.value = null; ledger.value = []; ledgerError.value = '' }

function payloadFromForm() {
  const unsettled = amountToCents(form.unsettled_balance || '0')
  if (!Number.isInteger(unsettled) || unsettled < 0) throw new Error('余额格式不正确，请输入最多两位小数的非负金额。')
  const payload = { name: form.name, type: form.type, contact: form.contact || null, phone: form.phone || null, website: form.website || null, notes: form.notes || null }
  if (!editing.value) Object.assign(payload, { unsettled_balance_cents: unsettled })
  return payload
}

async function loadPartners() {
  loading.value = true; errorMessage.value = ''
  // The API returns active and inactive accounts by default.  Keep the full
  // list client-side so the “全部/已归档” filter does not issue an unknown
  // compatibility query parameter to the strict FastAPI endpoint.
  try {
    const next = await partnersApi.list()
    partners.value = next
    // Keep an open detail dialog in sync after a ledger write/archive.  The
    // list request replaces the array, so retaining the old object would
    // otherwise leave the summary cards showing the previous balance until
    // the dialog is closed and reopened.
    if (selectedPartner.value?.id) {
      const refreshed = next.find((item) => item.id === selectedPartner.value.id)
      if (refreshed) selectedPartner.value = refreshed
    }
  }
  catch (error) { errorMessage.value = error instanceof ApiError ? error.message : '往来账户加载失败。' }
  finally { loading.value = false }
}

async function savePartner() {
  formError.value = ''
  if (!form.name) { formError.value = '请输入账户名称。'; return }
  let data
  try { data = payloadFromForm() } catch (error) { formError.value = error.message; return }
  saving.value = true
  try { if (editing.value) await partnersApi.update(editing.value.id, data); else await partnersApi.create(data); modalOpen.value = false; notice.value = { type: 'success', message: editing.value ? '往来账户已更新。' : '往来账户已创建。' }; await loadPartners() }
  catch (error) { formError.value = error instanceof ApiError ? error.message : '保存失败，请稍后重试。' }
  finally { saving.value = false }
}

async function toggleArchive(item) {
  const action = isArchived(item) ? '恢复' : '归档'
  if (!await requestConfirm({ eyebrow: '往来账户', title: `${action}“${partnerName(item)}”？`, message: `账户${action}后，历史流水与未结算余额记录都会保留。`, confirmLabel: `确认${action}`, tone: isArchived(item) ? 'primary' : 'danger' })) return
  try {
    if (isArchived(item)) await partnersApi.update(item.id, { is_active: true, status: 'active' })
    else await partnersApi.remove(item.id)
    notice.value = { type: 'success', message: `“${partnerName(item)}”已${action}。` }; await loadPartners()
  } catch (error) { notice.value = { type: 'error', message: error instanceof ApiError ? error.message : `${action}失败。` } }
}

async function openDetail(item) { selectedPartner.value = item; detailOpen.value = true; await loadLedger() }
async function loadLedger() {
  if (!selectedPartner.value?.id) return
  ledgerLoading.value = true; ledgerError.value = ''
  try { ledger.value = await partnersApi.ledger(selectedPartner.value.id, { page_size: 100 }) }
  catch (error) { ledgerError.value = error instanceof ApiError ? error.message : '往来流水加载失败。' }
  finally { ledgerLoading.value = false }
}
function openLedgerEntry() { ledgerFormError.value = ''; Object.assign(ledgerForm, { balance: centsToAmount(unsettledCents(selectedPartner.value)), occurred_at: localDateTimeValue(), notes: '' }); ledgerEntryOpen.value = true }
function closeLedgerEntry() { if (!ledgerSaving.value) ledgerEntryOpen.value = false }
async function saveLedgerEntry() {
  ledgerFormError.value = ''
  const target = amountToCents(ledgerForm.balance || '0')
  if (!Number.isInteger(target) || target < 0) { ledgerFormError.value = '请输入最多两位小数的非负余额。'; return }
  const occurred_at = datetimeLocalToUtcIso(ledgerForm.occurred_at)
  if (!occurred_at) { ledgerFormError.value = '请输入有效的北京时间。'; return }
  const current = unsettledCents(selectedPartner.value)
  const delta = target - current
  const type = partnerType(selectedPartner.value) === 'customer'
    ? (delta >= 0 ? 'credit_use' : 'credit_repay')
    : (delta >= 0 ? 'prepaid_in' : 'prepaid_out')
  const amount = Math.abs(delta)
  ledgerSaving.value = true
  try {
    await partnersApi.addLedgerEntry(selectedPartner.value.id, { entry_type: delta === 0 ? 'balance_check' : type, amount_cents: delta === 0 ? 0 : amount, occurred_at, notes: ledgerForm.notes || null })
    ledgerEntryOpen.value = false; notice.value = { type: 'success', message: '往来流水已记录。' }; await loadLedger(); await loadPartners()
  } catch (error) { ledgerFormError.value = error instanceof ApiError ? error.message : '流水保存失败，请稍后重试。' }
  finally { ledgerSaving.value = false }
}
async function reverseLedgerEntry(entry) {
  if (!entry?.id || !await requestConfirm({ eyebrow: '往来流水', title: '冲正这条流水？', message: '系统会写入一条反向补偿记录，原记录不会删除，余额也会同步恢复。', confirmLabel: '确认冲正' })) return
  try { await partnersApi.reverseLedger(selectedPartner.value.id, entry.id); notice.value = { type: 'success', message: '流水已冲正，原记录仍会保留。' }; await loadLedger(); await loadPartners() }
  catch (error) { notice.value = { type: 'error', message: error instanceof ApiError ? error.message : '冲正失败。' } }
}

onMounted(loadPartners)
</script>

<style scoped>
.panel { background:#fff; border-radius:13px; box-shadow:0 2px 8px #243b5a0d; }.primary { border:0; border-radius:8px; background:#2563eb; color:#fff; padding:10px 16px; font-size:13px; font-weight:600; cursor:pointer; white-space:nowrap; text-decoration:none; }.primary:hover { background:#1d4ed8; }.primary:disabled { opacity:.65; cursor:wait; }.secondary-link { color:#2563eb; text-decoration:none; font-size:13px; font-weight:600; padding:10px 3px; white-space:nowrap; }.toolbar { margin-top:28px; padding:15px 18px; display:flex; align-items:flex-end; flex-wrap:wrap; gap:12px; }.toolbar label { display:block; flex:1 1 200px; margin:0; color:#7b8aa0; font-size:12px; }.toolbar label span { display:block; margin-bottom:6px; }.toolbar input,.toolbar select { width:100%; height:38px; border:1px solid #dbe2ee; border-radius:8px; padding:0 10px; color:#44536a; font:inherit; font-size:13px; outline:none; background:#fff; }.toolbar input:focus,.toolbar select:focus { border-color:#3b82f6; }.type-field,.status-field { flex:0 1 160px!important; }.outline-button { border:1px solid #d6dfec; border-radius:8px; background:#fff; color:#52617a; padding:9px 16px; cursor:pointer; font-size:13px; white-space:nowrap; }.outline-button:hover { border-color:#3b82f6; color:#2563eb; }.link-button { text-decoration:none; display:inline-flex; align-items:center; }.list-panel { margin-top:18px; overflow:hidden; }.panel-head { display:flex; align-items:center; justify-content:space-between; gap:15px; padding:21px 24px; border-bottom:1px solid #edf0f5; }.panel-head h2 { color:#34435b; margin:0; font-size:17px; }.panel-head p { color:#8a97aa; margin:6px 0 0; font-size:12px; }.muted-count { color:#8996a9; font-size:12px; }.partner-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); gap:15px; padding:20px 24px 25px; }.partner-card { border:1px solid #e7edf5; border-radius:12px; padding:17px; cursor:pointer; transition:border-color .15s,box-shadow .15s,transform .15s; }.partner-card:hover { border-color:#b9d0f7; box-shadow:0 7px 22px #244d8612; transform:translateY(-1px); }.partner-card.archived { opacity:.68; }.partner-card-head { display:flex; align-items:center; gap:10px; }.partner-avatar { width:39px; height:39px; flex:0 0 39px; border-radius:11px; display:grid; place-items:center; font-weight:700; font-size:15px; }.type-supplier { color:#995b18; background:#fff2d9; }.type-customer { color:#176b59; background:#e3f8f0; }.type-other { color:#52617a; background:#eef3fa; }.partner-title { min-width:0; flex:1; }.partner-title h3 { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#33425b; font-size:15px; margin:0; }.partner-title span { color:#98a4b4; display:block; font-size:11px; margin-top:4px; }.status-pill { border-radius:99px; padding:4px 7px; font-size:10px; white-space:nowrap; }.status-active { color:#14835e; background:#e7f8f0; }.status-archived { color:#8e98a7; background:#f1f3f5; }.contact-line { color:#8795a8; font-size:12px; margin:14px 0 0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.balance-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:8px; border-top:1px solid #edf0f5; border-bottom:1px solid #edf0f5; margin:14px 0 11px; padding:13px 0 11px; }.balance-grid span,.detail-summary span { display:block; color:#96a2b2; font-size:10px; margin-bottom:5px; }.balance-grid strong { display:block; color:#53627a; font-size:12px; white-space:nowrap; }.income-text { color:#128a63!important; }.expense-text { color:#d25b62!important; }.partner-card-foot { display:flex; justify-content:space-between; align-items:center; gap:8px; color:#a0aaba; font-size:10px; }.text-button { border:0; background:transparent; padding:2px 3px; color:#2563eb; cursor:pointer; font-size:11px; }.text-button.danger { color:#d05a61; }.state { min-height:290px; display:grid; place-content:center; justify-items:center; text-align:center; color:#8b98aa; padding:30px; }.state.compact { min-height:190px; }.state h3 { color:#52617a; margin:14px 0 6px; font-size:16px; }.state p { margin:0 0 17px; font-size:13px; }.error-state p { color:#ba4b53; }.empty-icon { font-size:34px; }.spinner { width:18px; height:18px; border:2px solid #dce7f8; border-top-color:#2563eb; border-radius:50%; animation:spin .7s linear infinite; }.spinner.dark { margin-bottom:10px; }@keyframes spin {to{transform:rotate(360deg)}}
.modal-backdrop { position:fixed; inset:0; z-index:100; display:grid; place-items:center; padding:18px; background:#10213c66; }.modal,.detail-modal { width:min(570px,100%); max-height:min(780px,calc(100vh - 36px)); overflow:auto; background:#fff; border-radius:16px; box-shadow:0 24px 80px #0c1c3560; padding:26px; }.detail-modal { width:min(760px,100%); }.modal-header { display:flex; justify-content:space-between; align-items:flex-start; gap:12px; }.modal-header h2 { margin:0; color:#1e2a3d; font-size:21px; }.modal-header p { color:#8996a9; margin:6px 0 0; font-size:12px; }.modal-close { border:0; background:transparent; color:#8b98aa; font-size:26px; line-height:1; cursor:pointer; }.form-error { margin-top:17px; color:#a83232; background:#fff0f0; border-radius:8px; padding:10px 12px; font-size:13px; }.partner-form { margin-top:17px; }.partner-form label { display:block; color:#59677d; font-size:13px; margin:15px 0; }.partner-form input,.partner-form select,.partner-form textarea { display:block; width:100%; margin-top:7px; border:1px solid #dbe2ee; border-radius:8px; padding:10px 11px; color:#44536a; background:#fff; font:inherit; font-size:13px; outline:none; }.partner-form input:focus,.partner-form select:focus,.partner-form textarea:focus { border-color:#3b82f6; }.partner-form input:disabled { color:#9aa6b6; background:#f5f7fa; }.partner-form textarea { resize:vertical; }.field-hint { margin:-4px 0 12px; color:#98a4b4; font-size:11px; }.form-grid { display:grid; grid-template-columns:1fr 1fr; gap:13px; }.modal-actions { display:flex; justify-content:flex-end; gap:10px; margin-top:22px; }.modal-actions .primary { min-width:110px; }.modal-actions .spinner { display:inline-block; width:14px; height:14px; border-color:#ffffff66; border-top-color:#fff; vertical-align:-2px; }.detail-summary { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; background:#f7faff; border-radius:10px; padding:15px; margin:20px 0 14px; }.detail-summary strong { color:#43536d; font-size:17px; }.detail-actions { display:flex; justify-content:flex-end; gap:9px; margin-bottom:12px; }.ledger-wrap { overflow-x:auto; border:1px solid #edf0f5; border-radius:10px; }.ledger-wrap table { border-collapse:collapse; width:100%; min-width:620px; }.ledger-wrap th { background:#fafbfd; color:#8996a9; font-size:11px; font-weight:600; text-align:left; padding:12px 13px; white-space:nowrap; }.ledger-wrap td { border-top:1px solid #edf0f5; color:#59677d; font-size:12px; padding:12px 13px; vertical-align:middle; }.ledger-type { color:#526d99; background:#eff4fb; border-radius:99px; padding:4px 7px; white-space:nowrap; font-size:10px; }.ledger-amount { font-weight:700; white-space:nowrap; }.ledger-notes { max-width:170px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.detail-modal .state { min-height:180px; }
.modal-backdrop { position:fixed; inset:0; z-index:100; display:grid; place-items:center; padding:18px; background:#10213c66; }.modal,.detail-modal { width:min(570px,100%); max-height:min(780px,calc(100vh - 36px)); overflow:auto; background:#fff; border-radius:16px; box-shadow:0 24px 80px #0c1c3560; padding:26px; }.detail-modal { width:min(760px,100%); }.modal-header { display:flex; justify-content:space-between; align-items:flex-start; gap:12px; }.modal-header h2 { margin:0; color:#1e2a3d; font-size:21px; }.modal-header p { color:#8996a9; margin:6px 0 0; font-size:12px; }.modal-close { border:0; background:transparent; color:#8b98aa; font-size:26px; line-height:1; cursor:pointer; }.form-error { margin-top:17px; color:#a83232; background:#fff0f0; border-radius:8px; padding:10px 12px; font-size:13px; }.partner-form { margin-top:17px; }.partner-form label { display:block; color:#59677d; font-size:13px; margin:15px 0; }.partner-form input,.partner-form select,.partner-form textarea { display:block; width:100%; margin-top:7px; border:1px solid #dbe2ee; border-radius:8px; padding:10px 11px; color:#44536a; background:#fff; font:inherit; font-size:13px; outline:none; }.partner-form input:focus,.partner-form select:focus,.partner-form textarea:focus { border-color:#3b82f6; }.partner-form input:disabled { color:#9aa6b6; background:#f5f7fa; }.partner-form textarea { resize:vertical; }.field-hint { margin:-4px 0 12px; color:#98a4b4; font-size:11px; }.form-grid { display:grid; grid-template-columns:1fr 1fr; gap:13px; }.modal-actions { display:flex; justify-content:flex-end; gap:10px; margin-top:22px; }.modal-actions .primary { min-width:110px; }.modal-actions .spinner { display:inline-block; width:14px; height:14px; border-color:#ffffff66; border-top-color:#fff; vertical-align:-2px; }.detail-summary { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; background:#f7faff; border-radius:10px; padding:15px; margin:20px 0 14px; }.detail-summary strong { color:#43536d; font-size:17px; }.detail-actions { display:flex; justify-content:flex-end; gap:9px; margin-bottom:12px; }.ledger-wrap { overflow-x:auto; border:1px solid #edf0f5; border-radius:10px; }.ledger-wrap table { border-collapse:collapse; width:100%; min-width:620px; }.ledger-wrap th { background:#fafbfd; color:#8996a9; font-size:11px; font-weight:600; text-align:left; padding:12px 13px; white-space:nowrap; }.ledger-wrap td { border-top:1px solid #edf0f5; color:#59677d; font-size:12px; padding:12px 13px; vertical-align:middle; }.ledger-type { color:#526d99; background:#eff4fb; border-radius:99px; padding:4px 7px; white-space:nowrap; font-size:10px; }.ledger-amount { font-weight:700; white-space:nowrap; }.ledger-notes { max-width:170px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.reversed-label { color:#9da6b3; font-size:11px; }.detail-modal .state { min-height:180px; }
@media(max-width:700px){.toolbar{margin-top:20px;padding:13px 14px}.toolbar label,.type-field,.status-field{flex:1 1 100%!important}.partner-grid{grid-template-columns:1fr;padding:15px 14px 20px}.panel-head{padding:17px 16px}.form-grid{grid-template-columns:1fr;gap:0}.modal,.detail-modal{padding:21px 17px}.detail-summary{gap:8px;padding:12px}.detail-summary strong{font-size:14px}.detail-actions{flex-wrap:wrap}.detail-actions>*{flex:1;justify-content:center;text-align:center}.partner-card-foot{align-items:flex-end}.partner-card-foot>div{display:flex;gap:5px}}
@media(max-width:430px){.header-actions{gap:5px}.secondary-link{font-size:11px}.primary{padding:9px 10px;font-size:12px}.balance-grid strong{font-size:11px}}
/* Mobile interaction layer: cards remain compact, while ledger rows become
   readable stacked entries instead of forcing the dialog wider than the
   viewport. */
@media(max-width:700px){
  .toolbar{margin-top:20px;padding:13px 14px;gap:10px}.toolbar label{min-width:0}.toolbar input,.toolbar select{min-height:44px;height:44px;font-size:16px}.toolbar .outline-button{width:100%;min-height:44px}
  .list-panel{margin-top:14px}.panel-head{padding:17px 16px;gap:8px}.panel-head h2{font-size:16px}.panel-head p{line-height:1.5}.muted-count{white-space:nowrap}
  .partner-grid{grid-template-columns:1fr;padding:12px 12px 18px;gap:10px}.partner-card{padding:14px;min-width:0}.partner-card:active{border-color:#9bbdf0;background:#fbfdff}.partner-card-head{min-width:0}.partner-title h3{font-size:15px}.contact-line{margin-top:12px;overflow-wrap:anywhere;white-space:normal;line-height:1.45}.balance-grid{gap:6px;margin-top:12px;padding:12px 0 10px}.balance-grid>div{min-width:0}.balance-grid span{font-size:10px;white-space:nowrap}.balance-grid strong{font-size:12px;overflow:hidden;text-overflow:ellipsis}.partner-card-foot{flex-wrap:wrap;align-items:center;line-height:1.4}.partner-card-foot>span{max-width:100%;overflow-wrap:anywhere}.partner-card-foot>div{display:flex;gap:4px;margin-left:auto}.text-button{min-width:44px;min-height:44px;padding:8px 9px;display:inline-flex;align-items:center;justify-content:center;font-size:12px}
  .modal-backdrop{align-items:end;padding:8px 8px max(8px,env(safe-area-inset-bottom))}.modal,.detail-modal{width:100%;max-height:calc(100dvh - 16px);border-radius:16px 16px 10px 10px;padding:21px 17px;overflow:auto}.modal-header{gap:8px}.modal-header h2{font-size:18px;line-height:1.35}.modal-header p{line-height:1.45}.modal-close{min-width:44px;min-height:44px;padding:8px}.partner-form{margin-top:13px}.partner-form label{margin:14px 0;line-height:1.35}.partner-form input,.partner-form select{min-height:44px;height:44px;font-size:16px}.partner-form textarea{font-size:16px;line-height:1.45}.form-grid{grid-template-columns:1fr;gap:0}.modal-actions{gap:8px}.modal-actions>*{min-height:44px;flex:1}.modal-actions .primary{min-width:0}
  .detail-summary{grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;padding:11px;margin:16px 0 11px}.detail-summary>div{min-width:0}.detail-summary span{font-size:9px;white-space:nowrap}.detail-summary strong{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px}.detail-actions{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px}.detail-actions>*{min-width:0;min-height:44px;justify-content:center;text-align:center}.detail-actions .link-button{padding-left:6px;padding-right:6px}.detail-modal .state{min-height:160px;padding:22px 8px}
  .ledger-wrap{border:0;overflow:visible}.ledger-wrap table,.ledger-wrap thead,.ledger-wrap tbody,.ledger-wrap tr,.ledger-wrap th,.ledger-wrap td{display:block}.ledger-wrap table{min-width:0}.ledger-wrap thead{display:none}.ledger-wrap tbody{display:grid;gap:8px}.ledger-wrap tr{border:1px solid #e7edf5;border-radius:10px;padding:7px 11px;background:#fff}.ledger-wrap td{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;min-height:44px;padding:7px 0;border:0;border-top:1px solid #edf0f5;text-align:right;white-space:normal;overflow-wrap:anywhere}.ledger-wrap td:first-child{border-top:0}.ledger-wrap td::before{content:attr(data-label);flex:0 0 auto;color:#96a2b2;font-size:10px;text-align:left}.ledger-wrap td>*{max-width:68%;overflow-wrap:anywhere}.ledger-wrap td:last-child{justify-content:flex-end;align-items:center}.ledger-wrap td:last-child::before{margin-right:auto}.ledger-wrap .text-button{min-height:44px;min-width:64px}.reversed-label{min-height:44px;display:inline-flex;align-items:center;padding:8px 10px}
  :deep(.header-actions){gap:5px;max-width:53vw;flex-wrap:wrap;justify-content:flex-end}.secondary-link{min-height:44px;display:inline-flex;align-items:center;font-size:11px}.primary{min-height:44px;padding:10px 12px}
}
@media(max-width:430px){.detail-summary strong{font-size:12px}.detail-actions{grid-template-columns:1fr}.balance-grid strong{font-size:11px}.partner-card-foot>div{width:100%;margin-left:0;justify-content:flex-end}}
.website-line{display:block;margin-top:6px;color:#2563eb;font-size:11px;line-height:1.45;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-decoration:none}.website-line:hover{text-decoration:underline}.legacy-email-line{display:block;margin-top:5px;color:#9a7a45;font-size:11px;line-height:1.45;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.detail-contact{display:grid;gap:5px;margin:0 0 14px;padding:10px 12px;border-radius:9px;background:#f8faff;color:#6f8098;font-size:12px;line-height:1.45;overflow-wrap:anywhere}.detail-contact a{color:#2563eb;text-decoration:none;overflow-wrap:anywhere}.detail-contact a:hover{text-decoration:underline}.detail-contact span{color:#8f7650}
@media(max-width:700px){.website-line,.legacy-email-line{white-space:normal;overflow-wrap:anywhere}.website-line{overflow:visible;text-overflow:clip}}
.balance-grid,.detail-summary{grid-template-columns:1fr}
</style>
