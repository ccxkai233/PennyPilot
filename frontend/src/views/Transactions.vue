<template>
  <AppLayout title="收支记录" :subtitle="subtitle" :notice="notice">
    <template #actions>
      <router-link class="primary add-button" to="/ai">{{ isMobile ? '记一笔' : '＋ 记一笔' }}</router-link>
      <button v-if="!isMobile" class="outline-button manual-button" type="button" @click="openCreate">手动记账</button>
    </template>

    <MobileTransactions v-if="isMobile" :transactions="transactions" :summary="summary" :categories="categories" :visible-categories="visibleCategories" :form-categories="formCategories" :payment-methods="paymentMethods" :form-payment-methods="formPaymentMethods" :partners="partners" :filters="filters" :form="form" :loading="loading" :saving="saving" :error-message="errorMessage" :form-error="formError" :modal-open="modalOpen" :editing="editing" :category-name="categoryName" :payment-method-name="paymentMethodName" :payment-method-option-label="paymentMethodOptionLabel" :transaction-cents="transactionCents" :is-voided="isVoided" :load-transactions="loadTransactions" :reset-filters="resetFilters" :open-create="openCreate" :open-edit="openEdit" :close-modal="closeModal" :save-transaction="saveTransaction" :void-transaction="voidTransaction" />
    <template v-else>

    <section class="filters panel" aria-label="流水筛选">
      <div class="filter-row">
        <label class="filter-field"><span>方向</span><select v-model="filters.direction" @change="loadTransactions"><option value="">全部收支</option><option value="income">收入</option><option value="expense">支出</option></select></label>
        <label class="filter-field"><span>开始日期</span><input v-model="filters.from" type="date" @change="loadTransactions" /></label>
        <label class="filter-field"><span>结束日期</span><input v-model="filters.to" type="date" @change="loadTransactions" /></label>
        <label class="filter-field"><span>分类</span><select v-model="filters.category_id" @change="loadTransactions"><option value="">全部分类</option><option v-for="category in visibleCategories" :key="category.id" :value="category.id">{{ category.name }}</option></select></label>
        <label class="filter-field"><span>资金账户</span><select v-model="filters.payment_method_id" @change="loadTransactions"><option value="">全部账户</option><option v-for="method in paymentMethods" :key="method.id" :value="method.id">{{ paymentMethodOptionLabel(method) }}</option></select></label>
        <label class="filter-field"><span>往来账户</span><select v-model="filters.partner_id" @change="loadTransactions"><option value="">全部账户</option><option v-for="partner in partners" :key="partner.id" :value="partner.id">{{ partner.name }}</option></select></label>
        <button class="clear-button" type="button" @click="resetFilters">重置</button>
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
                <td data-label="操作" class="actions-cell"><button type="button" class="text-button" :disabled="isVoided(transaction) || isTransfer(transaction)" @click="openEdit(transaction)">编辑</button><button type="button" class="text-button danger" :disabled="isVoided(transaction)" @click="voidTransaction(transaction)">作废</button></td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </section>

    <Teleport to="body">
      <div v-if="modalOpen" class="modal-backdrop" @click.self="closeModal">
        <section class="modal" role="dialog" aria-modal="true" :aria-labelledby="editing ? 'edit-title' : 'create-title'">
          <div class="modal-header"><div><h2 :id="editing ? 'edit-title' : 'create-title'">{{ editing ? '编辑收支' : '手动记账' }}</h2><p>金额以元填写，系统将按分保存</p></div><div class="modal-header-actions"><router-link v-if="!editing" class="manual-ai-link" to="/ai" @click="closeModal">改用 AI</router-link><button class="modal-close" type="button" aria-label="关闭" @click="closeModal">×</button></div></div>
          <div v-if="formError" class="form-error" role="alert">{{ formError }}</div>
          <form class="transaction-form" @submit.prevent="saveTransaction">
            <div class="direction-toggle" role="radiogroup" aria-label="收支方向"><button type="button" :class="{ selected: form.direction === 'expense' }" @click="form.direction = 'expense'">支出</button><button type="button" :class="{ selected: form.direction === 'income' }" @click="form.direction = 'income'">收入</button></div>
            <label>金额（元）<input v-model="form.amount" inputmode="decimal" pattern="^[0-9]+([.][0-9]{1,2})?$" placeholder="0.00" required /></label>
            <label>发生时间<input v-model="form.occurred_at" type="datetime-local" required /></label>
            <div class="form-grid">
              <label>分类<select v-model="form.category_id" required><option value="" disabled>请选择分类</option><option v-for="category in formCategories" :key="category.id" :value="String(category.id)">{{ category.name }}</option></select></label>
              <label>{{ form.direction === 'income' ? '收款账户' : '支付账户' }}<select v-model="form.payment_method_id" required><option value="" disabled>请选择账户</option><option v-for="method in formPaymentMethods" :key="method.id" :value="String(method.id)">{{ paymentMethodOptionLabel(method) }}</option></select></label>
              <label>往来账户（可选）<select v-model="form.partner_id"><option value="">不关联</option><option v-for="partner in partners" :key="partner.id" :value="String(partner.id)">{{ partner.name }}</option></select></label>
            </div>
            <label>备注（可选）<textarea v-model.trim="form.notes" rows="3" maxlength="500" placeholder="补充说明…"></textarea></label>
            <div class="modal-actions"><button class="outline-button" type="button" @click="closeModal">取消</button><button class="primary" type="submit" :disabled="saving"><span v-if="saving" class="spinner"></span>{{ saving ? '保存中…' : (editing ? '保存修改' : '确认入账') }}</button></div>
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
import { computed, onMounted, reactive, ref, watch } from 'vue'
import AppLayout from '../components/AppLayout.vue'
import ConfirmDialog from '../components/ConfirmDialog.vue'
import { useViewport } from '../composables/useViewport'
import { useConfirmDialog } from '../composables/useConfirmDialog'
import MobileTransactions from './MobileTransactions.vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError, amountToCents, datetimeLocalToUtcIso, formatDateTime, formatMoney, localDateTimeValue, categoriesApi, partnersApi, paymentMethodsApi, transactionsApi } from '../api'

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
const filters = reactive({ direction: '', from: '', to: '', category_id: '', payment_method_id: '', partner_id: String(route.query.partner_id || '') })
const form = reactive({ direction: 'expense', amount: '', occurred_at: localDateTimeValue(), category_id: '', payment_method_id: '', partner_id: '', notes: '' })
const { isMobile } = useViewport()
const { confirmDialog, requestConfirm, resolveConfirm } = useConfirmDialog()

const visibleCategories = computed(() => categories.value.filter((category) => category.is_active !== false))
const formPaymentMethods = computed(() => paymentMethods.value.filter((method) => method.is_active !== false))
const formCategories = computed(() => visibleCategories.value.filter((category) => !category.direction || category.direction === form.direction))
const subtitle = computed(() => `共 ${transactions.value.length} 笔记录`)
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
    Object.assign(form, { direction: 'expense', amount: '', occurred_at: localDateTimeValue(), category_id: '', payment_method_id: '', partner_id: '', notes: '' })
    return
  }
  Object.assign(form, {
    direction: transaction.direction || 'expense', amount: (transactionCents(transaction) / 100).toFixed(2),
    occurred_at: localDateTimeValue(transaction.occurred_at || transaction.occurred_time),
    category_id: String(transaction.category_id ?? transaction.category?.id ?? ''), payment_method_id: String(transaction.payment_method_id ?? transaction.payment_method?.id ?? ''), partner_id: String(transaction.partner_id ?? transaction.partner?.id ?? ''),
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
    const rows = await transactionsApi.list({ ...filters, include_voided: true, page_size: 100 })
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

function resetFilters() { Object.assign(filters, { direction: '', from: '', to: '', category_id: '', payment_method_id: '', partner_id: '' }); loadTransactions() }
function openCreate() { editing.value = null; formError.value = ''; normalizeForm(); modalOpen.value = true }
function openEdit(transaction) {
  if (isTransfer(transaction)) {
    notice.value = { type: 'error', message: '转账/还款流水暂不支持在普通表单编辑，请作废后重新记录。' }
    return
  }
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
  if (!form.category_id || !form.payment_method_id) { formError.value = '请选择分类和资金账户。'; return }
  const occurred_at = datetimeLocalToUtcIso(form.occurred_at)
  if (!occurred_at) { formError.value = '请输入有效的北京时间。'; return }
  saving.value = true
  const data = { direction: form.direction, amount_cents, occurred_at, category_id: Number(form.category_id), payment_method_id: Number(form.payment_method_id), partner_id: form.partner_id ? Number(form.partner_id) : null, notes: form.notes || null, source: editing.value?.source || 'manual' }
  try {
    if (editing.value) await transactionsApi.update(editing.value.id, data)
    else await transactionsApi.create(data)
    modalOpen.value = false
    notice.value = { type: 'success', message: editing.value ? '交易已更新。' : '交易已入账。' }
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

onMounted(async () => {
  try { await loadDictionaries() } catch (error) { errorMessage.value = error instanceof ApiError ? error.message : '基础数据加载失败。' }
  await loadTransactions()
  consumeManualMode()
})
</script>

<style scoped>
.panel { background: #fff; border-radius: 13px; box-shadow: 0 2px 8px #243b5a0d; }.add-button { margin-top: 1px; white-space: nowrap; text-decoration: none; }.manual-button { white-space: nowrap; }.primary { border: 0; border-radius: 8px; background: #2563eb; color: #fff; padding: 11px 18px; font-size: 13px; font-weight: 600; cursor: pointer; }.primary:hover { background: #1d4ed8; }.primary:disabled { opacity: .65; cursor: wait; }
.filters { margin-top: 28px; padding: 16px 18px; }.filter-row { display: flex; align-items: flex-end; flex-wrap: wrap; gap: 12px; }.filter-field { flex: 1 1 135px; min-width: 120px; margin: 0; }.filter-field span { display: block; color: #7c8ba1; font-size: 12px; margin-bottom: 6px; }.filter-field select, .filter-field input { width: 100%; height: 38px; border: 1px solid #dbe2ee; border-radius: 8px; padding: 0 10px; color: #44536a; background: #fff; outline: none; font: inherit; font-size: 13px; }.filter-field select:focus, .filter-field input:focus { border-color: #3b82f6; }.clear-button { height: 38px; border: 0; background: #f1f5fb; color: #64748b; border-radius: 8px; padding: 0 15px; cursor: pointer; font-size: 13px; }.clear-button:hover { color: #2563eb; }
.setup-hint { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 13px; padding: 10px 14px; border-radius: 9px; background: #fff8e7; color: #8a6924; font-size: 12px; }.setup-hint a { color: #2563eb; text-decoration: none; font-weight: 600; white-space: nowrap; }
.summary-row { display: flex; align-items: center; gap: 30px; padding: 20px 2px 16px; }.summary-item { display: flex; align-items: baseline; gap: 9px; }.summary-item span { color: #8996a9; font-size: 12px; }.summary-item strong { font-size: 16px; }.summary-count { margin-left: auto; color: #8996a9; font-size: 12px; }.income-text { color: #12966a; }.expense-text { color: #dc5a61; }.transfer-text { color: #64748b; }
.table-panel { overflow: hidden; min-height: 330px; }.table-wrap { overflow-x: auto; }table { width: 100%; border-collapse: collapse; min-width: 900px; }th { background: #fafbfd; color: #8996a9; font-size: 11px; font-weight: 600; text-align: left; padding: 13px 18px; white-space: nowrap; }td { border-top: 1px solid #edf0f5; color: #516078; font-size: 13px; padding: 15px 18px; vertical-align: middle; }tr:hover td { background: #fcfdff; }.time-cell { color: #77869b; white-space: nowrap; }.amount-cell { font-weight: 700; white-space: nowrap; }.notes-cell { max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.direction, .status { display: inline-flex; align-items: center; border-radius: 99px; padding: 4px 8px; font-size: 11px; white-space: nowrap; }.income-badge { color: #12845e; background: #e7f8f0; }.expense-badge { color: #c84d54; background: #fff0f0; }.transfer-badge { color: #526d99; background: #eff4fb; }.status-normal { color: #4f6c91; background: #eff4fb; }.status-voided { color: #9aa4b2; background: #f1f3f5; }.voided td { color: #a3acb8; }.actions-cell { white-space: nowrap; }.text-button { border: 0; background: transparent; padding: 3px 5px; color: #2563eb; font-size: 12px; cursor: pointer; }.text-button.danger { color: #d65b62; }.text-button:disabled { color: #b4bdc9; cursor: not-allowed; }.action-col { width: 105px; }
.state { min-height: 330px; display: grid; place-content: center; justify-items: center; text-align: center; color: #8b98aa; padding: 30px; }.state h3 { color: #52617a; margin: 14px 0 6px; font-size: 16px; }.state p { margin: 0 0 17px; font-size: 13px; }.empty-icon { font-size: 34px; }.empty-actions { display: flex; align-items: center; justify-content: center; gap: 9px; flex-wrap: wrap; }.error-state p { color: #ba4b53; }.outline-button { border: 1px solid #d6dfec; border-radius: 8px; background: #fff; color: #52617a; padding: 9px 16px; cursor: pointer; font-size: 13px; }.outline-button:hover { border-color: #3b82f6; color: #2563eb; }.outline-button.small, .primary.small { min-height: 40px; }.spinner { width: 18px; height: 18px; border: 2px solid #dce7f8; border-top-color: #2563eb; border-radius: 50%; animation: spin .7s linear infinite; }.spinner.dark { margin-bottom: 10px; }
.modal-backdrop { position: fixed; inset: 0; z-index: 100; display: grid; place-items: center; padding: 18px; background: #10213c66; }.modal { width: min(550px, 100%); max-height: min(760px, calc(100vh - 36px)); overflow: auto; background: #fff; border-radius: 16px; box-shadow: 0 24px 80px #0c1c3560; padding: 26px; }.modal-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }.modal-header h2 { margin: 0; color: #1e2a3d; font-size: 21px; }.modal-header p { color: #8996a9; margin: 6px 0 0; font-size: 12px; }.modal-header-actions { display: flex; align-items: center; gap: 8px; }.manual-ai-link { display: inline-flex; align-items: center; min-height: 36px; color: #2563eb; font-size: 12px; text-decoration: none; white-space: nowrap; }.modal-close { border: 0; background: transparent; color: #8b98aa; font-size: 26px; line-height: 1; cursor: pointer; }.form-error { margin-top: 17px; color: #a83232; background: #fff0f0; border-radius: 8px; padding: 10px 12px; font-size: 13px; }.transaction-form { margin-top: 17px; }.direction-toggle { display: grid; grid-template-columns: 1fr 1fr; gap: 5px; padding: 4px; border-radius: 10px; background: #f1f5fb; margin-bottom: 3px; }.direction-toggle button { border: 0; border-radius: 7px; background: transparent; color: #7c8ba1; padding: 9px; cursor: pointer; font-size: 13px; }.direction-toggle button.selected { background: #fff; color: #2563eb; box-shadow: 0 1px 5px #263b6114; font-weight: 600; }.transaction-form label { display: block; color: #59677d; font-size: 13px; margin: 15px 0; }.transaction-form input, .transaction-form select, .transaction-form textarea { display: block; width: 100%; margin-top: 7px; border: 1px solid #dbe2ee; border-radius: 8px; padding: 10px 11px; color: #44536a; background: #fff; font: inherit; font-size: 13px; outline: none; }.transaction-form input:focus, .transaction-form select:focus, .transaction-form textarea:focus { border-color: #3b82f6; }.transaction-form textarea { resize: vertical; }.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 13px; }.modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 22px; }.modal-actions .primary { min-width: 110px; }.modal-actions .spinner { display: inline-block; width: 14px; height: 14px; border-color: #ffffff66; border-top-color: #fff; vertical-align: -2px; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 700px) { .summary-row { gap: 15px; flex-wrap: wrap; }.summary-count { width: 100%; margin-left: 0; }.filters { margin-top: 20px; }.filter-field { flex-basis: calc(50% - 6px); }.table-panel { border-radius: 10px; } }
@media (max-width: 540px) { .add-button { padding: 9px 11px; font-size: 12px; }.filter-field { flex-basis: 100%; }.modal { padding: 21px 17px; }.form-grid { grid-template-columns: 1fr; gap: 0; } }
@media (max-width: 760px) { table, thead, tbody, th, td, tr { display: block; } table { min-width: 0; }.table-wrap { padding: 5px 14px; }thead { display: none; }tbody tr { padding: 13px 0; border-top: 1px solid #edf0f5; }tbody tr:first-child { border-top: 0; }td { display: flex; justify-content: space-between; align-items: baseline; gap: 15px; border: 0; padding: 6px 2px; text-align: right; }td::before { content: attr(data-label); color: #9aa6b7; font-size: 11px; text-align: left; }td.notes-cell { max-width: none; white-space: normal; }td.actions-cell { justify-content: flex-end; }.action-col { width: auto; } }
/* Mobile interaction layer: filters use a predictable two-column rhythm,
   transaction rows read as cards, and the entry form behaves like a bottom
   sheet on phones. */
@media(max-width:700px){
  .filters{margin-top:20px;padding:13px 14px;overflow:hidden}.filter-row{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.filter-field{min-width:0;flex:none}.filter-field span{font-size:11px;margin-bottom:5px}.filter-field select,.filter-field input{width:100%;min-width:0;min-height:44px;height:44px;font-size:16px;padding-left:9px;padding-right:7px}.filter-field:first-child,.filter-field:nth-child(4),.filter-field:nth-child(5),.filter-field:nth-child(6),.clear-button{grid-column:1/-1}.clear-button{min-height:44px;height:44px;padding:0 12px}.setup-hint{align-items:flex-start;flex-direction:column;gap:8px;margin-top:12px;line-height:1.5}.setup-hint a{min-height:44px;display:inline-flex;align-items:center}
  .summary-row{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;padding:14px 0 12px}.summary-item{min-width:0;min-height:44px;display:flex;flex-direction:column;align-items:flex-start;justify-content:center;gap:3px;padding:7px 8px;border:1px solid #e8eef7;border-radius:8px;background:#fff}.summary-item span{font-size:10px}.summary-item strong{font-size:13px;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.summary-count{grid-column:1/-1;width:auto;margin:0;text-align:right;padding-right:2px}
  .table-panel{border-radius:10px}.table-wrap{padding:5px 12px;overflow:visible}.table-wrap table,.table-wrap thead,.table-wrap tbody,.table-wrap tr,.table-wrap th,.table-wrap td{display:block}.table-wrap table{min-width:0}.table-wrap thead{display:none}.table-wrap tbody{display:grid;gap:8px}.table-wrap tbody tr{padding:8px 10px;border:1px solid #e7edf5;border-radius:10px;background:#fff}.table-wrap tbody tr:first-child{border-top:1px solid #e7edf5}.table-wrap td{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;min-height:44px;padding:7px 0;border:0;border-top:1px solid #edf0f5;text-align:right;white-space:normal;overflow-wrap:anywhere}.table-wrap td:first-child{border-top:0}.table-wrap td::before{content:attr(data-label);flex:0 0 auto;color:#9aa6b7;font-size:10px;text-align:left}.table-wrap td>*{max-width:68%;overflow-wrap:anywhere}.table-wrap .time-cell{white-space:normal}.table-wrap .notes-cell{max-width:none;white-space:normal;text-overflow:clip;overflow:visible}.table-wrap .actions-cell{justify-content:flex-end;align-items:center}.table-wrap .actions-cell::before{margin-right:auto}.text-button{min-width:64px;min-height:44px;padding:8px 10px;display:inline-flex;align-items:center;justify-content:center;font-size:12px}.state{padding:26px 16px}.state .primary,.state .outline-button{min-height:44px}
  .modal-backdrop{align-items:end;padding:8px 8px max(8px,env(safe-area-inset-bottom))}.modal{width:100%;max-height:calc(100dvh - 16px);border-radius:16px 16px 10px 10px;padding:21px 17px;overflow:auto}.modal-header{gap:8px}.modal-header h2{font-size:18px;line-height:1.35}.modal-header p{line-height:1.45}.modal-close{min-width:44px;min-height:44px;padding:8px}.transaction-form{margin-top:13px}.transaction-form label{margin:14px 0;line-height:1.35}.transaction-form input,.transaction-form select{min-height:44px;height:44px;font-size:16px}.transaction-form textarea{font-size:16px;line-height:1.45}.direction-toggle{min-height:52px}.direction-toggle button{min-height:44px;padding:9px}.form-grid{grid-template-columns:1fr;gap:0}.modal-actions{gap:8px}.modal-actions>*{min-height:44px;flex:1}.modal-actions .primary{min-width:0}
  :deep(.header-actions){gap:5px;max-width:48vw;flex-wrap:wrap;justify-content:flex-end}.add-button{min-height:44px;padding:10px 12px}
}
@media(max-width:430px){.filter-row{grid-template-columns:1fr}.filter-field{grid-column:1/-1!important}.summary-row{grid-template-columns:1fr 1fr}.summary-item:nth-child(3){grid-column:1/-1}.summary-item strong{font-size:12px}.table-wrap{padding-left:9px;padding-right:9px}.table-wrap td>*{max-width:64%}}
</style>
