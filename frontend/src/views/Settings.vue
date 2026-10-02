<template>
  <AppLayout title="设置" subtitle="管理分类与资金账户" :notice="notice">
    <MobileSettings
      v-if="isMobile"
      :active-tab="activeTab"
      :active-items="activeItems"
      :account-groups="accountGroups"
      :loading="loading"
      :error-message="errorMessage"
      :ai-config="aiConfig"
      :ai-config-error="aiConfigError"
      :config-saving="configSaving"
      :modal-open="modalOpen"
      :editing="editing"
      :form="form"
      :form-error="formError"
      :saving="saving"
      :set-active-tab="setActiveTab"
      :open-create="openCreate"
      :open-edit="openEdit"
      :remove-item="removeItem"
      :load-all="loadAll"
      :save-ai-config="saveAiConfig"
      :clear-ai-config="clearAiConfig"
      :close-modal="closeModal"
      :save-item="saveItem"
    />
    <template v-else>
    <section class="settings-tabs" role="tablist" aria-label="设置分类">
      <button type="button" role="tab" :aria-selected="activeTab === 'categories'" :class="{ active: activeTab === 'categories' }" @click="activeTab = 'categories'">收支分类</button>
      <button type="button" role="tab" :aria-selected="activeTab === 'methods'" :class="{ active: activeTab === 'methods' }" @click="activeTab = 'methods'">资金账户</button>
    </section>

    <section class="dictionary-panel panel">
      <div class="panel-head"><div><h2>{{ activeTab === 'categories' ? '收支分类' : '资金账户' }}</h2><p>{{ activeTab === 'categories' ? '按收入和支出分别维护常用分类。' : '维护现金、投资和信用卡/白条账户；记账时按账户性质自动处理余额。' }}</p></div><button class="primary" type="button" @click="openCreate">＋ 新增{{ activeTab === 'categories' ? '分类' : '账户' }}</button></div>
      <div v-if="loading" class="state"><span class="spinner dark"></span><p>正在加载…</p></div>
      <div v-else-if="errorMessage" class="state error-state"><p>{{ errorMessage }}</p><button class="outline-button" type="button" @click="loadAll">重试</button></div>
      <div v-else-if="activeItems.length === 0" class="state"><div class="empty-icon">▦</div><h3>还没有自定义{{ activeTab === 'categories' ? '分类' : '资金账户' }}</h3><p>新增一个项目，让记账更顺手。</p><button class="primary small" type="button" @click="openCreate">＋ 新增</button></div>
      <div v-else-if="activeTab === 'methods'" class="account-settings-groups">
        <section v-for="group in accountGroups" :key="group.role" class="account-settings-group">
          <header><span class="account-settings-group-icon" :class="`role-${group.role}`">{{ group.icon }}</span><strong>{{ group.label }}</strong><small>{{ group.items.length }} 个账户</small></header>
          <ul class="item-list">
            <li v-for="item in group.items" :key="item.id" :class="{ inactive: item.is_active === false }">
              <div class="item-leading"><span class="item-icon">{{ item.icon || '●' }}</span><div><strong>{{ item.name }}</strong><span class="direction-label"><span class="account-role-badge" :class="accountRoleClass(item)">{{ accountRoleLabel(item.account_role) }}</span></span></div></div>
              <div class="item-trailing"><span class="balance">{{ item.account_role === 'liability' ? '欠款' : '余额' }} {{ formatMoney(item.current_balance_cents ?? item.effective_balance_cents ?? item.balance_cents) }}</span><span v-if="item.is_active === false" class="inactive-label">已停用</span><button class="text-button" type="button" @click="openEdit(item)">编辑</button><button class="text-button danger" type="button" @click="removeItem(item)">停用</button></div>
            </li>
          </ul>
        </section>
      </div>
      <ul v-else class="item-list">
        <li v-for="item in activeItems" :key="item.id" :class="{ inactive: item.is_active === false }">
          <div class="item-leading"><span class="item-icon">{{ item.icon || '▦' }}</span><div><strong>{{ item.name }}</strong><span class="direction-label">{{ item.direction === 'income' ? '收入' : item.direction === 'expense' ? '支出' : '通用' }}</span></div></div>
          <div class="item-trailing"><span v-if="item.is_active === false" class="inactive-label">已停用</span><button class="text-button" type="button" @click="openEdit(item)">编辑</button><button class="text-button danger" type="button" @click="removeItem(item)">停用</button></div>
        </li>
      </ul>
    </section>

    <section class="ai-config-panel panel">
      <div class="panel-head"><div><h2>AI 接口配置</h2><p>主通道和备用通道都可单独配置接口格式、地址、模型和密钥；密钥不会在页面回显明文。</p></div><div class="config-status-stack"><span class="config-status" :class="aiConfig.configured ? 'configured' : 'not-configured'">主通道 {{ aiConfig.configured ? '已配置' : '未配置' }}</span><span class="config-status" :class="aiConfig.fallback_configured ? 'configured' : 'not-configured'">备用通道 {{ aiConfig.fallback_configured ? '已配置' : '未配置' }}</span></div></div>
      <form class="ai-config-form" @submit.prevent="saveAiConfig">
        <div class="config-block"><h3>主通道</h3><label>接口格式<select v-model="aiConfig.api_format"><option v-for="item in AI_API_FORMATS" :key="item.value" :value="item.value">{{ item.label }}</option></select><span class="format-hint">请求发往 {{ aiFormatInfo(aiConfig.api_format).endpoint }}</span></label><div class="config-grid"><label>接口地址（可选）<input v-model.trim="aiConfig.base_url" type="url" :placeholder="aiFormatInfo(aiConfig.api_format).urlPlaceholder" /></label><label>模型名称<input v-model.trim="aiConfig.model" maxlength="100" :placeholder="aiFormatInfo(aiConfig.api_format).modelPlaceholder" /></label></div><label>API Key <span class="label-hint">{{ aiConfig.key_hint || (aiConfig.configured ? '已保存（留空表示不修改）' : '尚未设置') }}</span><input v-model="aiConfig.api_key" type="password" autocomplete="new-password" placeholder="仅在修改时填写" /></label></div>
        <div class="config-block"><h3>备用通道</h3><label>接口格式<select v-model="aiConfig.fallback_api_format"><option v-for="item in AI_API_FORMATS" :key="item.value" :value="item.value">{{ item.label }}</option></select><span class="format-hint">请求发往 {{ aiFormatInfo(aiConfig.fallback_api_format).endpoint }}</span></label><div class="config-grid"><label>接口地址（可选）<input v-model.trim="aiConfig.fallback_base_url" type="url" :placeholder="aiFormatInfo(aiConfig.fallback_api_format).urlPlaceholder" /></label><label>模型名称<input v-model.trim="aiConfig.fallback_model" maxlength="100" :placeholder="aiFormatInfo(aiConfig.fallback_api_format).modelPlaceholder" /></label></div><label>API Key <span class="label-hint">{{ aiConfig.fallback_key_hint || (aiConfig.fallback_configured ? '已保存（留空表示不修改）' : '尚未设置') }}</span><input v-model="aiConfig.fallback_api_key" type="password" autocomplete="new-password" placeholder="仅在修改时填写" /></label></div>
        <div v-if="aiConfigError" class="form-error" role="alert">{{ aiConfigError }}</div>
        <div class="config-actions"><button class="primary" type="submit" :disabled="configSaving"><span v-if="configSaving" class="spinner"></span>{{ configSaving ? '保存中…' : '保存 AI 配置' }}</button><button v-if="aiConfig.configured" class="outline-button danger-outline" type="button" :disabled="configSaving" @click="clearAiConfig">清除配置</button></div>
      </form>
    </section>

    <Teleport to="body">
      <div v-if="modalOpen" class="modal-backdrop" @click.self="closeModal">
        <section class="modal" role="dialog" aria-modal="true" :aria-labelledby="editing ? 'dictionary-edit-title' : 'dictionary-create-title'">
          <div class="modal-header"><div><h2 :id="editing ? 'dictionary-edit-title' : 'dictionary-create-title'">{{ editing ? '编辑' : '新增' }}{{ activeTab === 'categories' ? '分类' : '资金账户' }}</h2><p>保存后会立即出现在记账表单中</p></div><button class="modal-close" type="button" aria-label="关闭" @click="closeModal">×</button></div>
          <div v-if="formError" class="form-error" role="alert">{{ formError }}</div>
          <form class="dictionary-form" @submit.prevent="saveItem">
            <label>名称<input v-model.trim="form.name" required maxlength="80" :placeholder="activeTab === 'categories' ? '例如：餐饮、房租、销售收入' : '例如：支付宝、招商银行信用卡、基金账户'" /></label>
            <label>图标（可选）<input v-model.trim="form.icon" maxlength="4" placeholder="例如：🍜" /></label>
            <template v-if="activeTab === 'categories'">
              <label>适用方向<select v-model="form.direction" required><option value="expense">支出</option><option value="income">收入</option></select></label>
            </template>
            <template v-else>
              <label>账户性质<select v-model="form.account_role"><option value="cash">现金账户（支付宝/微信/银行/纸币）</option><option value="investment">投资账户（基金/股票/理财）</option><option value="liability">负债账户（信用卡/花呗/白条）</option></select></label>
              <p class="field-hint">所有资金账户都会自动维护余额；负债账户余额表示欠款，投资账户余额表示当前投入或持仓金额。</p>
              <label>{{ form.account_role === 'liability' ? '当前欠款' : form.account_role === 'investment' ? '当前投入/持仓' : '当前余额' }}（元）<input v-model="form.balance" inputmode="decimal" pattern="^[0-9]*([.][0-9]{0,2})?$" placeholder="0.00" /></label>
            </template>
            <label>排序<input v-model.number="form.sort_order" type="number" min="0" max="9999" /></label>
            <div class="modal-actions"><button class="outline-button" type="button" @click="closeModal">取消</button><button class="primary" type="submit" :disabled="saving"><span v-if="saving" class="spinner"></span>{{ saving ? '保存中…' : '保存' }}</button></div>
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
import MobileSettings from './MobileSettings.vue'
import { groupAccounts } from '../accountRoles'
import { aiApi, ApiError, amountToCents, categoriesApi, centsToAmount, formatMoney, paymentMethodsApi } from '../api'
import { AI_API_FORMATS, aiFormatInfo } from '../aiFormats'

const { isMobile } = useViewport()
const { confirmDialog, requestConfirm, resolveConfirm } = useConfirmDialog()

const activeTab = ref('categories')
const categories = ref([])
const paymentMethods = ref([])
const loading = ref(false)
const saving = ref(false)
const errorMessage = ref('')
const formError = ref('')
const modalOpen = ref(false)
const editing = ref(null)
const notice = ref(null)
const form = reactive({ name: '', icon: '', direction: 'expense', account_role: 'cash', balance: '', sort_order: 0 })
const aiConfig = reactive({ api_format: 'openai', base_url: '', model: '', api_key: '', configured: false, key_hint: '', fallback_api_format: 'openai', fallback_base_url: '', fallback_model: '', fallback_api_key: '', fallback_configured: false, fallback_key_hint: '' })
const configSaving = ref(false)
const aiConfigError = ref('')
const activeItems = computed(() => activeTab.value === 'categories' ? categories.value : paymentMethods.value)
const accountGroups = computed(() => groupAccounts(paymentMethods.value))

function setActiveTab(tab) { activeTab.value = tab }

function accountRoleLabel(role) { return ({ cash: '现金', liability: '负债', investment: '投资' })[String(role || 'cash')] || '现金' }
function accountRoleClass(item) { return `role-${String(item?.account_role || 'cash')}` }

function resetForm() { Object.assign(form, { name: '', icon: '', direction: 'expense', account_role: 'cash', balance: '', sort_order: activeItems.value.length }) }
function openCreate() { editing.value = null; formError.value = ''; resetForm(); modalOpen.value = true }
function openEdit(item) {
  editing.value = item; formError.value = ''
  Object.assign(form, { name: item.name || '', icon: item.icon || '', direction: item.direction || 'expense', account_role: item.account_role || 'cash', balance: centsToAmount(item.current_balance_cents ?? item.effective_balance_cents ?? item.balance_cents ?? 0), sort_order: item.sort_order ?? item.sort ?? 0 })
  modalOpen.value = true
}
function closeModal() { if (!saving.value) modalOpen.value = false }

async function loadAll() {
  loading.value = true; errorMessage.value = ''
  const [categoryResult, methodResult] = await Promise.allSettled([categoriesApi.list(), paymentMethodsApi.list()])
  if (categoryResult.status === 'fulfilled') categories.value = categoryResult.value
  if (methodResult.status === 'fulfilled') paymentMethods.value = methodResult.value
  const failure = [categoryResult, methodResult].find((result) => result.status === 'rejected')
  if (failure) errorMessage.value = failure.reason instanceof ApiError ? failure.reason.message : '设置数据加载失败。'
  loading.value = false
  await loadAiConfig()
}

async function loadAiConfig() {
  try {
    const payload = await aiApi.config()
    Object.assign(aiConfig, { api_format: aiFormatInfo(payload?.api_format).value, fallback_api_format: aiFormatInfo(payload?.fallback_api_format).value, base_url: payload?.base_url || '', model: payload?.model || '', api_key: '', configured: Boolean(payload?.configured || payload?.api_key_set || payload?.api_key_configured || payload?.has_api_key), key_hint: payload?.api_key_hint || payload?.api_key_masked || payload?.key_hint || '', fallback_base_url: payload?.fallback_base_url || '', fallback_model: payload?.fallback_model || '', fallback_api_key: '', fallback_configured: Boolean(payload?.fallback_configured || payload?.fallback_api_key_set || payload?.fallback_api_key_configured || payload?.has_fallback_api_key), fallback_key_hint: payload?.fallback_api_key_hint || payload?.fallback_api_key_masked || payload?.fallback_key_hint || '' })
  } catch (error) {
    // Older deployments do not expose AI configuration yet; keep the form
    // available so the user can retry after upgrading the backend.
    if (!(error instanceof ApiError && [404, 405].includes(error.status))) aiConfigError.value = error instanceof ApiError ? error.message : 'AI 配置加载失败。'
  }
}

async function saveAiConfig() {
  aiConfigError.value = ''
  if (!aiConfig.model) { aiConfigError.value = '请输入模型名称。'; return }
  configSaving.value = true
  try {
    const data = { api_format: aiConfig.api_format, base_url: aiConfig.base_url || null, model: aiConfig.model, fallback_api_format: aiConfig.fallback_api_format, fallback_base_url: aiConfig.fallback_base_url || null, fallback_model: aiConfig.fallback_model || null }
    if (aiConfig.api_key) data.api_key = aiConfig.api_key
    if (aiConfig.fallback_api_key) data.fallback_api_key = aiConfig.fallback_api_key
    const payload = await aiApi.saveConfig(data)
    aiConfig.api_key = ''; aiConfig.fallback_api_key = ''; aiConfig.configured = Boolean(payload?.configured || payload?.api_key_set || payload?.api_key_configured || aiConfig.configured || data.api_key); aiConfig.key_hint = payload?.api_key_hint || payload?.api_key_masked || payload?.key_hint || aiConfig.key_hint; aiConfig.fallback_configured = Boolean(payload?.fallback_configured || payload?.fallback_api_key_set || payload?.fallback_api_key_configured || aiConfig.fallback_configured || data.fallback_api_key); aiConfig.fallback_key_hint = payload?.fallback_api_key_hint || payload?.fallback_api_key_masked || payload?.fallback_key_hint || aiConfig.fallback_key_hint; notice.value = { type: 'success', message: 'AI 配置已保存。' }
  } catch (error) { aiConfigError.value = error instanceof ApiError ? error.message : 'AI 配置保存失败。' }
  finally { configSaving.value = false }
}

async function clearAiConfig() {
  if (!await requestConfirm({ eyebrow: 'AI 接口配置', title: '清除 AI 接口配置？', message: '主通道和备用通道的已保存密钥与模型配置都会被清除。', confirmLabel: '确认清除' })) return
  configSaving.value = true; aiConfigError.value = ''
  try { await aiApi.clearConfig(); Object.assign(aiConfig, { api_format: 'openai', fallback_api_format: 'openai', base_url: '', model: '', api_key: '', configured: false, key_hint: '', fallback_base_url: '', fallback_model: '', fallback_api_key: '', fallback_configured: false, fallback_key_hint: '' }); notice.value = { type: 'success', message: 'AI 配置已清除。' } }
  catch (error) { aiConfigError.value = error instanceof ApiError ? error.message : 'AI 配置清除失败。' }
  finally { configSaving.value = false }
}

async function saveItem() {
  formError.value = ''
  if (!form.name) { formError.value = '请输入名称。'; return }
  let data
  if (activeTab.value === 'categories') data = { name: form.name, icon: form.icon || null, direction: form.direction || 'expense', sort_order: Number(form.sort_order) || 0 }
  else {
    const balance = amountToCents(form.balance || '0')
    if (!Number.isInteger(balance) || balance < 0) { formError.value = '余额格式不正确。'; return }
    data = { name: form.name, icon: form.icon || null, account_role: form.account_role || 'cash', track_balance: true, current_balance_cents: balance, sort_order: Number(form.sort_order) || 0 }
  }
  saving.value = true
  try {
    if (editing.value) {
      if (activeTab.value === 'categories') await categoriesApi.update(editing.value.id, data)
      else await paymentMethodsApi.update(editing.value.id, data)
    } else {
      if (activeTab.value === 'categories') await categoriesApi.create(data)
      else await paymentMethodsApi.create(data)
    }
    modalOpen.value = false; notice.value = { type: 'success', message: '设置已保存。' }; await loadAll()
  } catch (error) { formError.value = error instanceof ApiError ? error.message : '保存失败，请稍后重试。' }
  finally { saving.value = false }
}

async function removeItem(item) {
  if (!await requestConfirm({ eyebrow: activeTab.value === 'categories' ? '收支分类' : '资金账户', title: `停用“${item.name}”？`, message: '停用后不会再出现在新建表单中，已有历史记录不会被删除。', confirmLabel: '确认停用' })) return
  try {
    if (activeTab.value === 'categories') await categoriesApi.remove(item.id)
    else await paymentMethodsApi.remove(item.id)
    notice.value = { type: 'success', message: `“${item.name}”已停用。` }; await loadAll()
  } catch (error) { notice.value = { type: 'error', message: error instanceof ApiError ? error.message : '操作失败。' } }
}

watch(activeTab, () => { formError.value = '' })
onMounted(loadAll)
</script>

<style scoped>
.account-settings-groups{display:grid}.account-settings-group+ .account-settings-group{border-top:8px solid #f3f6fa}.account-settings-group>header{display:flex;align-items:center;gap:8px;min-height:43px;padding:8px 24px;background:#fafbfd;border-bottom:1px solid #edf0f5}.account-settings-group>header strong{color:#405169;font-size:12px}.account-settings-group>header small{color:#9aa6b7;font-size:10px}.account-settings-group-icon{display:grid;place-items:center;width:25px;height:25px;border-radius:8px;font-size:11px;font-weight:700}
.panel { background: #fff; border-radius: 13px; box-shadow: 0 2px 8px #243b5a0d; }.settings-tabs { display: flex; gap: 6px; margin-top: 29px; border-bottom: 1px solid #e6ebf3; }.settings-tabs button { border: 0; border-bottom: 2px solid transparent; background: transparent; color: #8290a6; padding: 11px 16px; cursor: pointer; font-size: 13px; }.settings-tabs button.active { color: #2563eb; border-bottom-color: #2563eb; font-weight: 600; }.dictionary-panel { margin-top: 21px; overflow: hidden; }.ai-config-panel { margin-top: 18px; overflow: hidden; }.panel-head { display: flex; align-items: center; justify-content: space-between; gap: 15px; padding: 21px 24px; border-bottom: 1px solid #edf0f5; }.panel-head h2 { color: #34435b; margin: 0; font-size: 17px; }.panel-head p { color: #8a97aa; margin: 6px 0 0; font-size: 12px; }.config-status { border-radius: 99px; padding: 5px 9px; font-size: 11px; white-space: nowrap; }.config-status-stack { display: grid; gap: 6px; justify-items: end; }.config-block { display: grid; gap: 10px; padding: 14px 16px; margin-bottom: 14px; border: 1px solid #edf1f6; border-radius: 12px; background: #fbfdff; }.config-block h3 { margin: 0; color: #405169; font-size: 13px; }.configured { color: #12845e; background: #e7f8f0; }.not-configured { color: #8b98aa; background: #f1f3f5; }.ai-config-form { padding: 18px 24px 23px; }.config-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }.ai-config-form label { display: block; color: #59677d; font-size: 13px; margin: 0 0 15px; }.format-hint { display: block; margin-top: 6px; color: #99a5b5; font-size: 11px; line-height: 1.4; overflow-wrap: anywhere; }
.ai-config-form input, .ai-config-form select { display: block; width: 100%; margin-top: 7px; border: 1px solid #dbe2ee; border-radius: 8px; padding: 10px 11px; color: #44536a; background: #fff; font: inherit; font-size: 13px; outline: none; }.ai-config-form input:focus, .ai-config-form select:focus { border-color: #3b82f6; }.label-hint { color: #99a5b5; font-size: 11px; margin-left: 5px; }.config-actions { display: flex; justify-content: flex-end; align-items: center; gap: 10px; }.danger-outline { color: #c8555d; }.primary { border: 0; border-radius: 8px; background: #2563eb; color: #fff; padding: 10px 16px; font-size: 13px; font-weight: 600; cursor: pointer; white-space: nowrap; }.primary:hover { background: #1d4ed8; }.primary:disabled { opacity: .65; cursor: wait; }.small { padding: 10px 17px; }.item-list { list-style: none; padding: 0 24px; margin: 0; }.item-list li { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 16px 0; border-bottom: 1px solid #edf0f5; }.item-list li:last-child { border-bottom: 0; }.item-leading { display: flex; align-items: center; gap: 13px; min-width: 0; }.item-icon { width: 36px; height: 36px; display: grid; place-items: center; border-radius: 10px; background: #edf4ff; color: #2563eb; font-size: 18px; }.item-leading strong { display: block; color: #42516a; font-size: 14px; font-weight: 600; }.direction-label { display: flex; align-items: center; gap: 6px; color: #98a4b4; font-size: 11px; margin-top: 4px; }.account-role-badge { display: inline-flex; align-items: center; border-radius: 99px; padding: 2px 6px; font-size: 10px; line-height: 1.4; }.role-cash { color: #2563eb; background: #edf4ff; }.role-liability { color: #c84d54; background: #fff0f0; }.role-investment { color: #12845e; background: #e7f8f0; }.field-hint { margin: -5px 0 10px; color: #8a97aa; font-size: 12px; line-height: 1.5; }.item-trailing { display: flex; align-items: center; gap: 13px; color: #718096; font-size: 12px; }.balance { white-space: nowrap; }.inactive-label { color: #9da6b3; }.inactive { opacity: .65; }.text-button { border: 0; background: transparent; padding: 3px 2px; color: #2563eb; font-size: 12px; cursor: pointer; }.text-button.danger { color: #d65b62; }.state { min-height: 290px; display: grid; place-content: center; justify-items: center; text-align: center; color: #8b98aa; padding: 30px; }.state h3 { color: #52617a; margin: 14px 0 6px; font-size: 16px; }.state p { margin: 0 0 17px; font-size: 13px; }.empty-icon { font-size: 33px; }.error-state p { color: #ba4b53; }.outline-button { border: 1px solid #d6dfec; border-radius: 8px; background: #fff; color: #52617a; padding: 9px 16px; cursor: pointer; font-size: 13px; }.outline-button:hover { border-color: #3b82f6; color: #2563eb; }.spinner { width: 18px; height: 18px; border: 2px solid #dce7f8; border-top-color: #2563eb; border-radius: 50%; animation: spin .7s linear infinite; }.spinner.dark { margin-bottom: 10px; }.modal-backdrop { position: fixed; inset: 0; z-index: 100; display: grid; place-items: center; padding: 18px; background: #10213c66; }.modal { width: min(490px, 100%); max-height: min(700px, calc(100vh - 36px)); overflow: auto; background: #fff; border-radius: 16px; box-shadow: 0 24px 80px #0c1c3560; padding: 26px; }.modal-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }.modal-header h2 { margin: 0; color: #1e2a3d; font-size: 21px; }.modal-header p { color: #8996a9; margin: 6px 0 0; font-size: 12px; }.modal-close { border: 0; background: transparent; color: #8b98aa; font-size: 26px; line-height: 1; cursor: pointer; }.form-error { margin-top: 17px; color: #a83232; background: #fff0f0; border-radius: 8px; padding: 10px 12px; font-size: 13px; }.dictionary-form { margin-top: 17px; }.dictionary-form label { display: block; color: #59677d; font-size: 13px; margin: 15px 0; }.dictionary-form input, .dictionary-form select { display: block; width: 100%; margin-top: 7px; border: 1px solid #dbe2ee; border-radius: 8px; padding: 10px 11px; color: #44536a; background: #fff; font: inherit; font-size: 13px; outline: none; }.dictionary-form input:focus, .dictionary-form select:focus { border-color: #3b82f6; }.check-row { display: flex !important; align-items: center; gap: 7px; }.check-row input { width: auto; margin: 0; }.modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 22px; }.modal-actions .primary { min-width: 90px; }.modal-actions .spinner { display: inline-block; width: 14px; height: 14px; border-color: #ffffff66; border-top-color: #fff; vertical-align: -2px; }
@keyframes spin { to { transform: rotate(360deg); } }
@media(max-width:600px){.panel-head{padding:17px 16px;align-items:flex-start}.panel-head .primary{padding:9px 10px;font-size:12px}.ai-config-form{padding:17px 16px 20px}.config-grid{grid-template-columns:1fr;gap:0}.item-list{padding:0 16px}.item-list li{align-items:flex-start}.item-trailing{flex-wrap:wrap;justify-content:flex-end;gap:8px}.balance{width:100%;text-align:right}.modal{padding:21px 17px}}
@media(max-width:600px){
  .settings-tabs{margin-top:20px;gap:0;overflow-x:auto;overscroll-behavior-x:contain;-webkit-overflow-scrolling:touch}
  .settings-tabs button{min-height:44px;flex:1 0 auto;padding:11px 14px;white-space:nowrap}
  .panel-head{gap:10px}
  .panel-head>div:first-child{min-width:0;flex:1}
  .panel-head h2,.panel-head p{overflow-wrap:anywhere;line-height:1.5}
  .panel-head .primary{min-height:44px;display:inline-flex;align-items:center;justify-content:center;flex:0 0 auto}
  .config-status{flex:0 0 auto}
  .ai-config-form{min-width:0}
  .ai-config-form input,.ai-config-form select{min-height:44px;font-size:16px}
  .label-hint{display:inline-block;margin:3px 0 0 0;line-height:1.4;overflow-wrap:anywhere}
  .config-actions{flex-direction:column;align-items:stretch;gap:8px}
  .config-actions>*{width:100%;min-height:44px}
  .item-list{min-width:0}
  .item-list li{min-width:0}
  .item-leading{min-width:0}
  .item-leading>div{min-width:0}
  .item-leading strong,.direction-label{overflow-wrap:anywhere;word-break:break-word}
  .item-trailing{min-width:0}
  .balance{max-width:100%;overflow-wrap:anywhere;white-space:normal}
  .text-button,.outline-button{min-height:44px;min-width:44px;padding:10px 7px;display:inline-flex;align-items:center;justify-content:center}
  .modal-backdrop{align-items:flex-end;overflow-y:auto;padding:12px;padding-bottom:max(12px,env(safe-area-inset-bottom));-webkit-overflow-scrolling:touch}
  .modal{width:100%;max-height:calc(100vh - 24px);max-height:calc(100dvh - 24px);overflow-y:auto;overscroll-behavior:contain;padding:20px 16px calc(14px + env(safe-area-inset-bottom));border-radius:16px 16px 10px 10px}
  .modal-header{min-width:0}
  .modal-header>div{min-width:0}
  .modal-header h2,.modal-header p{overflow-wrap:anywhere;line-height:1.5}
  .modal-close{width:44px;height:44px;min-width:44px;display:grid;place-items:center;flex:0 0 44px;margin:-8px -8px 0 0}
  .dictionary-form{min-width:0}
  .dictionary-form label{line-height:1.45}
  .dictionary-form input,.dictionary-form select{min-height:44px;font-size:16px}
  .check-row{min-height:44px}
  .check-row input{width:20px;height:20px;min-height:20px;flex:0 0 20px}
  .modal-actions{position:sticky;bottom:0;z-index:1;margin-top:18px;padding:12px 0 2px;background:linear-gradient(to bottom,#fff 0%,#fff 78%,#ffffffee 100%);border-top:1px solid #edf0f5}
  .modal-actions>*{flex:1;min-height:44px}
}
@media(max-width:430px){
  .panel-head{flex-wrap:wrap}
  .dictionary-panel>.panel-head .primary{width:100%}
  .ai-config-panel>.panel-head{align-items:flex-start}
  .ai-config-panel>.panel-head .config-status{margin-left:auto}
  .item-list li{display:grid;grid-template-columns:1fr;gap:9px}
  .item-trailing{width:100%;justify-content:flex-start;gap:4px 8px}
  .item-trailing .balance{width:auto;margin-right:auto}
}
@media(max-width:360px){
  .settings-tabs button{padding-left:11px;padding-right:11px;font-size:12px}
  .panel-head,.ai-config-form,.item-list{padding-left:13px;padding-right:13px}
  .modal{padding-left:13px;padding-right:13px}
}
</style>
