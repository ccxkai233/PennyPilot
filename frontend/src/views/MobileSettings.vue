<template>
  <div class="mobile-settings-page">
    <nav class="mobile-settings-tabs" role="tablist" aria-label="设置分类">
      <button type="button" role="tab" :aria-selected="activeTab === 'categories'" :class="{ active: activeTab === 'categories' }" @click="setActiveTab('categories')">收支分类</button>
      <button type="button" role="tab" :aria-selected="activeTab === 'methods'" :class="{ active: activeTab === 'methods' }" @click="setActiveTab('methods')">资金账户</button>
    </nav>

    <section class="mobile-settings-group">
      <div class="mobile-settings-group-head">
        <div>
          <p class="mobile-settings-eyebrow">常用字典</p>
          <h2>{{ activeTab === 'categories' ? '收支分类' : '资金账户' }}</h2>
          <p>{{ activeTab === 'categories' ? '按收入和支出维护常用分类。' : '维护现金、投资和负债账户。' }}</p>
        </div>
        <button class="mobile-settings-primary" type="button" @click="openCreate">＋ 新增</button>
      </div>
      <div v-if="loading" class="mobile-settings-state"><span class="mobile-settings-spinner dark"></span><p>正在加载…</p></div>
      <div v-else-if="errorMessage" class="mobile-settings-state is-error"><p>{{ errorMessage }}</p><button class="mobile-settings-secondary" type="button" @click="loadAll">重试</button></div>
      <div v-else-if="activeItems.length === 0" class="mobile-settings-state"><div class="mobile-settings-empty-icon">▦</div><h3>还没有自定义{{ activeTab === 'categories' ? '分类' : '资金账户' }}</h3><p>新增一个项目，让记账更顺手。</p><button class="mobile-settings-primary" type="button" @click="openCreate">＋ 新增</button></div>
      <div v-else-if="activeTab === 'methods'" class="mobile-settings-account-groups">
        <section v-for="group in accountGroups" :key="group.role" class="mobile-settings-account-group">
          <header><span class="mobile-settings-role-icon" :class="`role-${group.role}`">{{ group.icon }}</span><strong>{{ group.label }}</strong><small>{{ group.items.length }} 个</small></header>
          <ul class="mobile-settings-items">
            <li v-for="item in group.items" :key="item.id" :class="{ inactive: item.is_active === false }">
              <div class="mobile-settings-item-main"><span class="mobile-settings-icon">{{ item.icon || '●' }}</span><div><strong>{{ item.name }}</strong><span>{{ accountRoleLabel(item.account_role) }}</span></div></div>
              <div class="mobile-settings-item-meta"><span class="mobile-settings-balance">{{ item.account_role === 'liability' ? '欠款' : '余额' }} {{ formatMoney(item.current_balance_cents ?? item.effective_balance_cents ?? item.balance_cents) }}</span><span v-if="item.is_active === false" class="mobile-settings-inactive">已停用</span><button class="mobile-settings-action" type="button" @click="openEdit(item)">编辑</button><button class="mobile-settings-action danger" type="button" @click="removeItem(item)">停用</button></div>
            </li>
          </ul>
        </section>
      </div>
      <ul v-else class="mobile-settings-items">
        <li v-for="item in activeItems" :key="item.id" :class="{ inactive: item.is_active === false }">
          <div class="mobile-settings-item-main">
            <span class="mobile-settings-icon">{{ item.icon || '▦' }}</span>
            <div><strong>{{ item.name }}</strong><span>{{ item.direction === 'income' ? '收入' : item.direction === 'expense' ? '支出' : '通用' }}</span></div>
          </div>
          <div class="mobile-settings-item-meta">
            <span v-if="item.is_active === false" class="mobile-settings-inactive">已停用</span>
            <button class="mobile-settings-action" type="button" @click="openEdit(item)">编辑</button>
            <button class="mobile-settings-action danger" type="button" @click="removeItem(item)">停用</button>
          </div>
        </li>
      </ul>
    </section>

    <section class="mobile-settings-group mobile-settings-ai">
      <div class="mobile-settings-group-head compact">
        <div>
          <p class="mobile-settings-eyebrow">服务连接</p>
          <h2>AI 接口配置</h2>
          <p>主通道和备用通道都可单独配置，密钥不会在页面回显。</p>
        </div>
        <div class="mobile-settings-config-stack"><span class="mobile-settings-config-status" :class="aiConfig.configured ? 'configured' : 'not-configured'">主通道 {{ aiConfig.configured ? '已配置' : '未配置' }}</span><span class="mobile-settings-config-status" :class="aiConfig.fallback_configured ? 'configured' : 'not-configured'">备用通道 {{ aiConfig.fallback_configured ? '已配置' : '未配置' }}</span></div>
      </div>
      <form class="mobile-settings-ai-form" @submit.prevent="saveAiConfig">
        <section class="mobile-settings-config-block"><h3>主通道</h3><label>接口格式<select v-model="aiConfig.api_format"><option v-for="item in AI_API_FORMATS" :key="item.value" :value="item.value">{{ item.label }}</option></select><span class="mobile-settings-hint">请求发往 {{ aiFormatInfo(aiConfig.api_format).endpoint }}</span></label><label>接口地址（可选）<input v-model.trim="aiConfig.base_url" type="url" :placeholder="aiFormatInfo(aiConfig.api_format).urlPlaceholder" /></label><label>模型名称<input v-model.trim="aiConfig.model" maxlength="100" :placeholder="aiFormatInfo(aiConfig.api_format).modelPlaceholder" /></label><label>API Key <span class="mobile-settings-hint">{{ aiConfig.key_hint || (aiConfig.configured ? '已保存（留空表示不修改）' : '尚未设置') }}</span><input v-model="aiConfig.api_key" type="password" autocomplete="new-password" placeholder="仅在修改时填写" /></label></section>
        <section class="mobile-settings-config-block"><h3>备用通道</h3><label>接口格式<select v-model="aiConfig.fallback_api_format"><option v-for="item in AI_API_FORMATS" :key="item.value" :value="item.value">{{ item.label }}</option></select><span class="mobile-settings-hint">请求发往 {{ aiFormatInfo(aiConfig.fallback_api_format).endpoint }}</span></label><label>接口地址（可选）<input v-model.trim="aiConfig.fallback_base_url" type="url" :placeholder="aiFormatInfo(aiConfig.fallback_api_format).urlPlaceholder" /></label><label>模型名称<input v-model.trim="aiConfig.fallback_model" maxlength="100" :placeholder="aiFormatInfo(aiConfig.fallback_api_format).modelPlaceholder" /></label><label>API Key <span class="mobile-settings-hint">{{ aiConfig.fallback_key_hint || (aiConfig.fallback_configured ? '已保存（留空表示不修改）' : '尚未设置') }}</span><input v-model="aiConfig.fallback_api_key" type="password" autocomplete="new-password" placeholder="仅在修改时填写" /></label></section>
        <p v-if="aiConfigError" class="mobile-settings-error" role="alert">{{ aiConfigError }}</p>
        <div class="mobile-settings-form-actions">
          <button class="mobile-settings-primary" type="submit" :disabled="configSaving"><span v-if="configSaving" class="mobile-settings-spinner"></span>{{ configSaving ? '保存中…' : '保存 AI 配置' }}</button>
          <button v-if="aiConfig.configured" class="mobile-settings-secondary danger" type="button" :disabled="configSaving" @click="clearAiConfig">清除配置</button>
        </div>
      </form>
    </section>

    <Teleport to="body">
      <div v-if="modalOpen" class="mobile-settings-sheet-backdrop" @click.self="closeModal">
        <section class="mobile-settings-sheet" role="dialog" aria-modal="true" :aria-labelledby="editing ? 'mobile-settings-edit-title' : 'mobile-settings-create-title'">
          <div class="mobile-settings-sheet-handle" aria-hidden="true"></div>
          <div class="mobile-settings-sheet-head">
            <div><p class="mobile-settings-eyebrow">设置项目</p><h2 :id="editing ? 'mobile-settings-edit-title' : 'mobile-settings-create-title'">{{ editing ? '编辑' : '新增' }}{{ activeTab === 'categories' ? '分类' : '资金账户' }}</h2><p>保存后会立即出现在记账表单中</p></div>
            <button class="mobile-settings-close" type="button" aria-label="关闭" @click="closeModal">×</button>
          </div>
          <p v-if="formError" class="mobile-settings-error" role="alert">{{ formError }}</p>
          <form class="mobile-settings-sheet-form" @submit.prevent="saveItem">
            <label>名称<input v-model.trim="form.name" required maxlength="80" :placeholder="activeTab === 'categories' ? '例如：餐饮、房租、销售收入' : '例如：支付宝、招商银行信用卡、基金账户'" /></label>
            <label>图标（可选）<input v-model.trim="form.icon" maxlength="4" placeholder="例如：🍜" /></label>
            <label v-if="activeTab === 'categories'">适用方向<select v-model="form.direction" required><option value="expense">支出</option><option value="income">收入</option></select></label>
            <template v-else>
              <label>账户性质<select v-model="form.account_role"><option value="cash">现金账户</option><option value="investment">投资账户</option><option value="liability">负债账户</option></select></label>
              <p class="mobile-settings-field-hint">所有资金账户都会自动维护余额；负债余额表示欠款，投资余额表示当前投入或持仓。</p>
              <label>{{ form.account_role === 'liability' ? '当前欠款' : form.account_role === 'investment' ? '当前投入/持仓' : '当前余额' }}（元）<input v-model="form.balance" inputmode="decimal" pattern="^[0-9]*([.][0-9]{0,2})?$" placeholder="0.00" /></label>
            </template>
            <label>排序<input v-model.number="form.sort_order" type="number" min="0" max="9999" /></label>
            <div class="mobile-settings-sheet-actions">
              <button class="mobile-settings-secondary" type="button" :disabled="saving" @click="closeModal">取消</button>
              <button class="mobile-settings-primary" type="submit" :disabled="saving"><span v-if="saving" class="mobile-settings-spinner"></span>{{ saving ? '保存中…' : '保存' }}</button>
            </div>
          </form>
        </section>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { AI_API_FORMATS, aiFormatInfo } from '../aiFormats'
import { formatMoney } from '../api'

function accountRoleLabel(role) { return ({ cash: '现金', liability: '负债', investment: '投资' })[String(role || 'cash')] || '现金' }

defineProps({
  activeTab: { type: String, default: 'categories' },
  activeItems: { type: Array, default: () => [] },
  accountGroups: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  errorMessage: { type: String, default: '' },
  aiConfig: { type: Object, required: true },
  aiConfigError: { type: String, default: '' },
  configSaving: { type: Boolean, default: false },
  modalOpen: { type: Boolean, default: false },
  editing: { type: Object, default: null },
  form: { type: Object, required: true },
  formError: { type: String, default: '' },
  saving: { type: Boolean, default: false },
  setActiveTab: { type: Function, required: true },
  openCreate: { type: Function, required: true },
  openEdit: { type: Function, required: true },
  removeItem: { type: Function, required: true },
  loadAll: { type: Function, required: true },
  saveAiConfig: { type: Function, required: true },
  clearAiConfig: { type: Function, required: true },
  closeModal: { type: Function, required: true },
  saveItem: { type: Function, required: true },
})
</script>

<style scoped>
.mobile-settings-account-groups{display:grid}.mobile-settings-account-group+ .mobile-settings-account-group{border-top:8px solid #f3f6fa}.mobile-settings-account-group>header{display:flex;align-items:center;gap:8px;min-height:43px;padding:8px 16px;background:#fafbfd;border-bottom:1px solid #edf1f6}.mobile-settings-account-group>header strong{color:#405169;font-size:12px}.mobile-settings-account-group>header small{color:#9aa6b7;font-size:10px}.mobile-settings-role-icon{display:grid;place-items:center;width:26px;height:26px;border-radius:8px;font-size:11px;font-weight:700}.mobile-settings-role-icon.role-cash{color:#2563eb;background:#edf4ff}.mobile-settings-role-icon.role-investment{color:#12845e;background:#e7f8f0}.mobile-settings-role-icon.role-liability{color:#c84d54;background:#fff0f0}
.mobile-settings-page{display:grid;gap:14px;margin-top:18px;padding-bottom:18px}.mobile-settings-tabs{display:grid;grid-template-columns:1fr 1fr;gap:5px;padding:4px;border-radius:12px;background:#eaf0f8}.mobile-settings-tabs button{min-height:44px;border:0;border-radius:9px;background:transparent;color:#7c8ba1;font-size:13px;cursor:pointer}.mobile-settings-tabs button.active{background:#fff;color:#2563eb;box-shadow:0 1px 5px #263b6114;font-weight:600}.mobile-settings-group{background:#fff;border:1px solid #e7edf6;border-radius:16px;box-shadow:0 4px 16px #243b5a0a;overflow:hidden}.mobile-settings-group-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;padding:17px 16px;border-bottom:1px solid #edf1f6}.mobile-settings-group-head>div{min-width:0}.mobile-settings-group-head.compact{align-items:flex-start}.mobile-settings-eyebrow{margin:0 0 4px;color:#7e8da4;font-size:11px;letter-spacing:.03em}.mobile-settings-group-head h2{margin:0;color:#26364e;font-size:17px;line-height:1.4;overflow-wrap:anywhere}.mobile-settings-group-head p:last-child{margin:6px 0 0;color:#8a97aa;font-size:12px;line-height:1.55;overflow-wrap:anywhere}.mobile-settings-primary,.mobile-settings-secondary{display:inline-flex;align-items:center;justify-content:center;min-height:46px;border-radius:10px;padding:10px 14px;font-size:13px;font-weight:600;cursor:pointer}.mobile-settings-primary{flex:0 0 auto;border:0;background:#2563eb;color:#fff}.mobile-settings-secondary{border:1px solid #d7e1ee;background:#fff;color:#50617a}.mobile-settings-primary:disabled,.mobile-settings-secondary:disabled{opacity:.58;cursor:wait}.mobile-settings-state{min-height:190px;display:grid;place-content:center;justify-items:center;padding:24px 16px;color:#8b98aa;text-align:center;font-size:13px}.mobile-settings-state p{margin:0 0 13px;line-height:1.5}.mobile-settings-state.is-error{color:#b54e58}.mobile-settings-empty-icon{font-size:32px;color:#7194cc}.mobile-settings-state h3{margin:8px 0 6px;color:#52617a;font-size:16px}.mobile-settings-items{list-style:none;margin:0;padding:0 16px}.mobile-settings-items li{display:grid;gap:10px;padding:14px 0;border-bottom:1px solid #edf1f6}.mobile-settings-items li:last-child{border-bottom:0}.mobile-settings-item-main{display:flex;align-items:center;gap:11px;min-width:0}.mobile-settings-item-main>div{min-width:0}.mobile-settings-icon{display:grid;place-items:center;flex:0 0 38px;width:38px;height:38px;border-radius:11px;background:#edf4ff;color:#2563eb;font-size:18px}.mobile-settings-item-main strong{display:block;color:#42516a;font-size:14px;line-height:1.4;overflow-wrap:anywhere;word-break:break-word}.mobile-settings-item-main span:not(.mobile-settings-icon){display:block;margin-top:3px;color:#98a4b4;font-size:11px}.mobile-settings-item-meta{display:flex;align-items:center;flex-wrap:wrap;gap:4px 8px;min-width:0}.mobile-settings-balance{margin-right:auto;color:#718096;font-size:12px;overflow-wrap:anywhere}.mobile-settings-inactive{color:#9da6b3;font-size:11px}.mobile-settings-action{display:inline-flex;align-items:center;justify-content:center;min-width:44px;min-height:44px;padding:9px 7px;border:0;border-radius:9px;background:#f5f8fc;color:#2563eb;font-size:12px;cursor:pointer}.mobile-settings-action.danger{color:#d65b62}.mobile-settings-items li.inactive{opacity:.65}.mobile-settings-config-status{display:inline-flex;align-items:center;min-height:27px;padding:4px 9px;border-radius:99px;font-size:11px;white-space:nowrap}.configured{color:#12845e;background:#e7f8f0}.not-configured{color:#8b98aa;background:#f1f3f5}.mobile-settings-ai-form{display:grid;gap:11px;padding:16px}.mobile-settings-ai-form label,.mobile-settings-sheet-form label{display:block;color:#53637a;font-size:12px;line-height:1.45}.mobile-settings-ai-form input,.mobile-settings-ai-form select,.mobile-settings-sheet-form input,.mobile-settings-sheet-form select{display:block;width:100%;min-height:46px;margin-top:6px;border:1px solid #dbe4f0;border-radius:10px;padding:10px 11px;background:#fff;color:#3f5068;font:inherit;font-size:16px;outline:0}.mobile-settings-ai-form input:focus,.mobile-settings-ai-form select:focus,.mobile-settings-sheet-form input:focus,.mobile-settings-sheet-form select:focus{border-color:#3b82f6}.mobile-settings-hint{display:inline-block;margin-top:3px;color:#99a5b5;font-size:11px;line-height:1.4;overflow-wrap:anywhere}.mobile-settings-error{margin:0;padding:10px 11px;border-radius:9px;background:#fff0f0;color:#a83232;font-size:12px;line-height:1.55;overflow-wrap:anywhere}.mobile-settings-field-hint{margin:0;color:#8a97aa;font-size:12px;line-height:1.55}.mobile-settings-form-actions{display:grid;gap:8px;margin-top:2px}.mobile-settings-form-actions .danger{color:#c8555d}.mobile-settings-spinner{display:inline-block;width:15px;height:15px;margin-right:5px;border:2px solid #ffffff66;border-top-color:#fff;border-radius:50%;animation:mobile-settings-spin .7s linear infinite;vertical-align:-3px}.mobile-settings-spinner.dark{margin:0;border-color:#dce7f8;border-top-color:#2563eb}@keyframes mobile-settings-spin{to{transform:rotate(360deg)}}.mobile-settings-sheet-backdrop{position:fixed;inset:0;z-index:100;display:flex;align-items:flex-end;justify-content:center;overflow-y:auto;padding:12px;background:#10213c66;-webkit-overflow-scrolling:touch}.mobile-settings-sheet{width:min(560px,100%);max-height:calc(100vh - 24px);max-height:calc(100dvh - 24px);overflow-y:auto;overscroll-behavior:contain;padding:8px 16px calc(14px + env(safe-area-inset-bottom));border-radius:18px 18px 10px 10px;background:#fff;box-shadow:0 -15px 60px #0c1c3560}.mobile-settings-sheet-handle{width:38px;height:4px;margin:0 auto 12px;border-radius:99px;background:#d6dfec}.mobile-settings-sheet-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}.mobile-settings-sheet-head>div{min-width:0}.mobile-settings-sheet-head h2{margin:0;color:#1e2a3d;font-size:20px;line-height:1.4;overflow-wrap:anywhere}.mobile-settings-sheet-head p:last-child{margin:5px 0 0;color:#8996a9;font-size:12px;line-height:1.5}.mobile-settings-close{display:grid;place-items:center;flex:0 0 44px;width:44px;height:44px;margin:-7px -7px 0 0;border:0;border-radius:9px;background:transparent;color:#8b98aa;font-size:26px;cursor:pointer}.mobile-settings-close:hover,.mobile-settings-close:focus-visible{background:#f1f5fb;color:#2563eb}.mobile-settings-sheet-form{display:grid;gap:11px;margin-top:15px}.mobile-settings-check{display:flex!important;align-items:center;gap:9px;min-height:44px}.mobile-settings-check input{width:20px;height:20px;min-height:20px;margin:0;accent-color:#2563eb}.mobile-settings-sheet-actions{position:sticky;bottom:0;display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:5px;padding:12px 0 2px;border-top:1px solid #edf1f6;background:linear-gradient(to bottom,#fff 0%,#fff 80%,#ffffffed 100%)}.mobile-settings-sheet-actions>*{min-height:46px}
@media(max-width:380px){.mobile-settings-group-head,.mobile-settings-sheet-head{padding-left:13px;padding-right:13px}.mobile-settings-ai-form,.mobile-settings-items{padding-left:13px;padding-right:13px}.mobile-settings-sheet{padding-left:13px;padding-right:13px}.mobile-settings-sheet-actions{grid-template-columns:1fr}.mobile-settings-action{min-width:44px}.mobile-settings-item-meta{gap:4px 6px}}
.mobile-settings-config-stack{display:grid;gap:5px;justify-items:end;flex:0 0 auto}.mobile-settings-config-block{display:grid;gap:11px;padding:13px;border:1px solid #e1e9f3;border-radius:12px;background:linear-gradient(145deg,#fcfdff,#f7faff)}.mobile-settings-config-block h3{display:flex;align-items:center;gap:7px;margin:0;color:#405169;font-size:13px}.mobile-settings-config-block h3:before{content:"";width:7px;height:7px;border-radius:50%;background:#3b82f6;box-shadow:0 0 0 4px #3b82f614}.mobile-settings-config-block+ .mobile-settings-config-block h3:before{background:#7c8ba1;box-shadow:0 0 0 4px #7c8ba114}.mobile-settings-config-block label{margin:0}.mobile-settings-ai-form input:focus{box-shadow:0 0 0 3px #3b82f612}
@media(max-width:420px){.mobile-settings-group-head.compact{display:grid}.mobile-settings-config-stack{display:flex;justify-content:flex-start;flex-wrap:wrap}}
@media(max-width:380px){.mobile-settings-config-block{padding:12px}}
</style>
