<template>
  <div class="mobile-partners">
    <section class="mobile-partner-filter panel" aria-label="往来账户筛选">
      <label class="mobile-search"><span>搜索账户</span><input v-model.trim="filters.search" type="search" placeholder="名称、联系人或备注" /></label>
      <div class="mobile-filter-row"><label><span>类型</span><select v-model="filters.type"><option value="">全部类型</option><option value="supplier">供应商</option><option value="customer">客户</option></select></label><label><span>状态</span><select v-model="filters.status"><option value="active">启用</option><option value="">全部</option><option value="archived">已归档</option></select></label></div>
      <button type="button" class="mobile-reset" @click="resetFilters">重置筛选</button>
    </section>

    <section class="mobile-partner-list panel" aria-labelledby="mobile-partner-list-title">
      <header class="mobile-list-head"><div><h2 id="mobile-partner-list-title">账户列表</h2><p>未结算余额</p></div><span class="mobile-count">{{ filteredPartners.length }} 个账户</span></header>
      <div v-if="loading" class="mobile-state"><span class="mobile-spinner"></span><p>正在加载往来账户…</p></div>
      <div v-else-if="errorMessage" class="mobile-state mobile-error"><p>{{ errorMessage }}</p><button type="button" class="mobile-outline" @click="loadPartners">重试</button></div>
      <div v-else-if="!filteredPartners.length" class="mobile-state"><div class="mobile-empty-icon">♧</div><h3>{{ partners.length ? '没有匹配的账户' : '还没有往来账户' }}</h3><p>{{ partners.length ? '试试调整筛选条件。' : '新增一个客户或供应商，开始追踪资金往来。' }}</p><button type="button" class="mobile-primary" @click="openCreate">＋ 新增账户</button></div>
      <div v-else class="mobile-partner-cards">
        <article v-for="partner in filteredPartners" :key="partner.id" class="mobile-partner-card" :class="{ archived: isArchived(partner) }" @click="openDetail(partner)">
          <header class="mobile-partner-card-head"><div class="mobile-avatar" :class="typeClass(partner)">{{ typeIcon(partner) }}</div><div class="mobile-partner-title"><h3>{{ partnerName(partner) }}</h3><span>{{ typeLabel(partner) }}</span></div><span class="mobile-status" :class="isArchived(partner) ? 'archived-status' : 'active-status'">{{ isArchived(partner) ? '已归档' : '启用' }}</span></header>
          <p v-if="contactText(partner)" class="mobile-contact">⌁ {{ contactText(partner) }}</p>
          <a v-if="websiteUrl(partner) && websiteHref(partner)" class="mobile-website" :href="websiteHref(partner)" target="_blank" rel="noopener noreferrer" @click.stop>↗ {{ websiteUrl(partner) }}</a>
          <p v-if="legacyEmail(partner)" class="mobile-legacy-email">邮箱：{{ legacyEmail(partner) }}</p>
          <div class="mobile-balance-grid"><div><span>未结算余额</span><strong :class="balanceClass(unsettledCents(partner), partnerType(partner) === 'customer')">{{ formatMoney(unsettledCents(partner)) }}</strong></div></div>
          <footer class="mobile-card-footer"><small>更新于 {{ formatDateTime(partner.updated_at || partner.created_at) }}</small><div><button type="button" class="mobile-text-button" @click.stop="openEdit(partner)">编辑</button><button type="button" class="mobile-text-button danger" @click.stop="toggleArchive(partner)">{{ isArchived(partner) ? '恢复' : '归档' }}</button></div></footer>
        </article>
      </div>
    </section>

    <div v-if="modalOpen" class="mobile-sheet-backdrop" @click.self="closeModal">
      <section class="mobile-sheet" role="dialog" aria-modal="true" :aria-labelledby="editing ? 'mobile-partner-edit-title' : 'mobile-partner-create-title'">
        <header class="mobile-sheet-head"><div><h2 :id="editing ? 'mobile-partner-edit-title' : 'mobile-partner-create-title'">{{ editing ? '编辑往来账户' : '新增往来账户' }}</h2><p>未结算余额按元填写，系统按分保存</p></div><button type="button" class="mobile-close" aria-label="关闭" @click="closeModal">×</button></header>
        <div v-if="formError" class="mobile-form-error" role="alert">{{ formError }}</div>
        <form class="mobile-partner-form" @submit.prevent="savePartner">
          <label>账户名称<input v-model.trim="form.name" required maxlength="120" placeholder="例如：华东供应链、王先生" /></label>
          <label>账户类型<select v-model="form.type" required><option value="supplier">供应商</option><option value="customer">客户</option></select></label>
          <div class="mobile-form-grid"><label>联系人<input v-model.trim="form.contact" maxlength="100" placeholder="可选" /></label><label>电话<input v-model.trim="form.phone" maxlength="40" inputmode="tel" placeholder="可选" /></label></div>
          <label>网址<input v-model.trim="form.website" maxlength="2048" type="url" inputmode="url" placeholder="https://example.com" /></label>
          <label>未结算余额（元）<input v-model.trim="form.unsettled_balance" :disabled="Boolean(editing)" inputmode="decimal" placeholder="0.00" /></label>
          <p v-if="editing" class="mobile-field-hint">账户余额请在详情中的“记录未结算余额”里调整。</p>
          <label>备注（可选）<textarea v-model.trim="form.notes" maxlength="1000" rows="3" placeholder="记录合作约定、结算周期等"></textarea></label>
          <footer class="mobile-sheet-actions"><button type="button" class="mobile-outline" @click="closeModal">取消</button><button type="submit" class="mobile-primary" :disabled="saving"><span v-if="saving" class="mobile-spinner light"></span>{{ saving ? '保存中…' : '保存账户' }}</button></footer>
        </form>
      </section>
    </div>

    <div v-if="detailOpen && selectedPartner" class="mobile-sheet-backdrop mobile-detail-backdrop" @click.self="closeDetail">
      <section class="mobile-sheet mobile-detail-sheet" role="dialog" aria-modal="true" aria-labelledby="mobile-partner-detail-title">
        <header class="mobile-sheet-head"><div><h2 id="mobile-partner-detail-title">{{ partnerName(selectedPartner) }}</h2><p>{{ typeLabel(selectedPartner) }} · 往来流水</p></div><button type="button" class="mobile-close" aria-label="关闭详情" @click="closeDetail">×</button></header>
        <div class="mobile-detail-summary"><div><span>未结算余额</span><strong :class="balanceClass(unsettledCents(selectedPartner), partnerType(selectedPartner) === 'customer')">{{ formatMoney(unsettledCents(selectedPartner)) }}</strong></div></div>
        <div v-if="websiteUrl(selectedPartner) || legacyEmail(selectedPartner)" class="mobile-detail-contact">
          <a v-if="websiteUrl(selectedPartner) && websiteHref(selectedPartner)" :href="websiteHref(selectedPartner)" target="_blank" rel="noopener noreferrer">网址：{{ websiteUrl(selectedPartner) }}</a>
          <span v-if="legacyEmail(selectedPartner)">历史邮箱：{{ legacyEmail(selectedPartner) }}</span>
        </div>
        <div class="mobile-detail-actions"><router-link class="mobile-outline" :to="{ path: '/transactions', query: { partner_id: String(selectedPartner.id || '') } }" @click="closeDetail">查看关联现金收支</router-link><router-link class="mobile-outline mobile-ai-partner-link" :to="{ path: '/ai', query: { partner_id: String(selectedPartner.id || '') } }" @click="closeDetail">✦ AI 记账</router-link><button type="button" class="mobile-primary" @click="openLedgerEntry">＋ 记录未结算余额</button></div>
        <div v-if="ledgerLoading" class="mobile-state compact"><span class="mobile-spinner"></span><p>正在加载流水…</p></div>
        <div v-else-if="ledgerError" class="mobile-state compact mobile-error"><p>{{ ledgerError }}</p><button type="button" class="mobile-outline" @click="loadLedger">重试</button></div>
        <div v-else-if="!ledger.length" class="mobile-state compact"><div class="mobile-empty-icon">↔</div><h3>暂无往来流水</h3><p>记录未结算余额后会显示在这里。</p></div>
        <div v-else class="mobile-ledger-cards"><article v-for="entry in ledger" :key="entry.id || `${entry.occurred_at}-${entry.amount_cents}`" class="mobile-ledger-card"><div class="mobile-ledger-head"><span class="mobile-ledger-type">{{ ledgerTypeLabel(entry) }}</span><time>{{ formatDateTime(entry.occurred_at || entry.occurred_time || entry.created_at) }}</time></div><div class="mobile-ledger-line"><span>本次变动</span><strong :class="ledgerDelta(entry) >= 0 ? 'income-text' : 'expense-text'">{{ ledgerDelta(entry) >= 0 ? '+' : '−' }}{{ formatMoney(Math.abs(ledgerDelta(entry)), '') }}</strong></div><div class="mobile-ledger-line"><span>变动后余额</span><b>{{ formatMoney(entry.balance_after_cents ?? entry.after_balance_cents ?? entry.balance_cents ?? 0) }}</b></div><p v-if="entry.notes || entry.note" class="mobile-ledger-note">{{ entry.notes || entry.note }}</p><footer><button v-if="entry.status !== 'reversed' && !entry.reversed_entry_id && !entry.reversal_of_id" type="button" class="mobile-text-button danger" @click="reverseLedgerEntry(entry)">冲正</button><span v-else class="mobile-reversed">已冲正</span></footer></article></div>
      </section>
    </div>

    <div v-if="ledgerEntryOpen && selectedPartner" class="mobile-sheet-backdrop mobile-ledger-backdrop" @click.self="closeLedgerEntry">
      <section class="mobile-sheet" role="dialog" aria-modal="true" aria-labelledby="mobile-ledger-entry-title">
        <header class="mobile-sheet-head"><div><h2 id="mobile-ledger-entry-title">记录未结算余额</h2><p>{{ partnerName(selectedPartner) }} · 余额与流水会原子更新</p></div><button type="button" class="mobile-close" aria-label="关闭" @click="closeLedgerEntry">×</button></header>
        <div v-if="ledgerFormError" class="mobile-form-error" role="alert">{{ ledgerFormError }}</div>
        <form class="mobile-partner-form" @submit.prevent="saveLedgerEntry">
          <label>未结算余额（元）<input v-model.trim="ledgerForm.balance" inputmode="decimal" required placeholder="0.00" /></label>
          <label>发生时间<input v-model="ledgerForm.occurred_at" type="datetime-local" required /></label>
          <label>备注（可选）<textarea v-model.trim="ledgerForm.notes" rows="3" maxlength="500" placeholder="说明这次变动"></textarea></label>
          <footer class="mobile-sheet-actions"><button type="button" class="mobile-outline" @click="closeLedgerEntry">取消</button><button type="submit" class="mobile-primary" :disabled="ledgerSaving"><span v-if="ledgerSaving" class="mobile-spinner light"></span>{{ ledgerSaving ? '保存中…' : '确认记录' }}</button></footer>
        </form>
      </section>
    </div>
  </div>
</template>

<script setup>
import { toRefs } from 'vue'
import { formatDateTime, formatMoney } from '../api'

const props = defineProps({
  partners: { type: Array, default: () => [] },
  filteredPartners: { type: Array, default: () => [] },
  filters: { type: Object, required: true },
  loading: { type: Boolean, default: false },
  errorMessage: { type: String, default: '' },
  modalOpen: { type: Boolean, default: false },
  detailOpen: { type: Boolean, default: false },
  ledgerEntryOpen: { type: Boolean, default: false },
  editing: { type: Object, default: null },
  selectedPartner: { type: Object, default: null },
  ledger: { type: Array, default: () => [] },
  ledgerLoading: { type: Boolean, default: false },
  ledgerError: { type: String, default: '' },
  saving: { type: Boolean, default: false },
  formError: { type: String, default: '' },
  form: { type: Object, required: true },
  ledgerForm: { type: Object, required: true },
  ledgerSaving: { type: Boolean, default: false },
  ledgerFormError: { type: String, default: '' },
  selectedPartnerLedgerOptions: { type: Array, default: () => [] },
  partnerName: { type: Function, required: true },
  partnerType: { type: Function, required: true },
  typeLabel: { type: Function, required: true },
  typeIcon: { type: Function, required: true },
  typeClass: { type: Function, required: true },
  isArchived: { type: Function, required: true },
  contactText: { type: Function, required: true },
  websiteUrl: { type: Function, default: () => '' },
  websiteHref: { type: Function, default: () => '' },
  legacyEmail: { type: Function, default: () => '' },
  prepaidCents: { type: Function, required: true },
  creditLimitCents: { type: Function, required: true },
  creditUsedCents: { type: Function, required: true },
  balanceClass: { type: Function, required: true },
  ledgerTypeLabel: { type: Function, required: true },
  ledgerDelta: { type: Function, required: true },
  resetFilters: { type: Function, required: true },
  loadPartners: { type: Function, required: true },
  openCreate: { type: Function, required: true },
  openEdit: { type: Function, required: true },
  toggleArchive: { type: Function, required: true },
  openDetail: { type: Function, required: true },
  closeModal: { type: Function, required: true },
  closeDetail: { type: Function, required: true },
  loadLedger: { type: Function, required: true },
  openLedgerEntry: { type: Function, required: true },
  closeLedgerEntry: { type: Function, required: true },
  savePartner: { type: Function, required: true },
  saveLedgerEntry: { type: Function, required: true },
  reverseLedgerEntry: { type: Function, required: true },
})
const {
  partners, filteredPartners, filters, loading, errorMessage, modalOpen, detailOpen, ledgerEntryOpen, editing,
  selectedPartner, ledger, ledgerLoading, ledgerError, saving, formError, form, ledgerForm, ledgerSaving, ledgerFormError,
  partnerName, partnerType, typeLabel, typeIcon, typeClass, isArchived, contactText, prepaidCents, creditLimitCents,
  creditUsedCents, balanceClass, ledgerTypeLabel, ledgerDelta, websiteUrl, websiteHref, legacyEmail, resetFilters, loadPartners, openCreate, openEdit,
  toggleArchive, openDetail, closeModal, closeDetail, loadLedger, openLedgerEntry, closeLedgerEntry, savePartner,
  saveLedgerEntry, reverseLedgerEntry,
} = toRefs(props)

function unsettledCents(item) {
  const direct = Number(item?.unsettled_balance_cents)
  if (Number.isFinite(direct)) return direct
  return partnerType.value(item) === 'customer' ? creditUsedCents.value(item) : prepaidCents.value(item)
}
</script>

<style scoped>
.mobile-partners{display:grid;gap:12px;margin-top:16px;min-width:0}.panel{background:#fff;border-radius:14px;box-shadow:0 2px 8px #243b5a0d}.mobile-partner-filter{padding:13px 14px}.mobile-partner-filter label{display:block;color:#7b8aa0;font-size:11px}.mobile-partner-filter label span{display:block;margin-bottom:5px}.mobile-partner-filter input,.mobile-partner-filter select{display:block;width:100%;min-height:44px;height:44px;border:1px solid #dbe2ee;border-radius:8px;padding:9px 10px;color:#44536a;background:#fff;font:inherit;font-size:16px;outline:0}.mobile-filter-row{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-top:11px}.mobile-reset{width:100%;min-height:44px;margin-top:10px;border:0;border-radius:8px;background:#f1f5fb;color:#64748b;font-size:13px}.mobile-list-head{display:flex;align-items:flex-start;justify-content:space-between;gap:8px;padding:16px;border-bottom:1px solid #edf0f5}.mobile-list-head h2{margin:0;color:#34435b;font-size:16px}.mobile-list-head p{margin:5px 0 0;color:#9aa6b7;font-size:11px}.mobile-count{color:#8996a9;font-size:11px;white-space:nowrap}.mobile-partner-cards{display:grid;gap:9px;padding:10px}.mobile-partner-card{min-width:0;padding:13px;border:1px solid #e7edf5;border-radius:11px;background:#fff}.mobile-partner-card.archived{opacity:.64}.mobile-partner-card:active{border-color:#9bbdf0}.mobile-partner-card-head{display:flex;align-items:center;gap:9px;min-width:0}.mobile-avatar{width:40px;height:40px;flex:0 0 40px;display:grid;place-items:center;border-radius:11px;font-size:15px;font-weight:700}.type-supplier{color:#995b18;background:#fff2d9}.type-customer{color:#176b59;background:#e3f8f0}.type-other{color:#52617a;background:#eef3fa}.mobile-partner-title{min-width:0;flex:1}.mobile-partner-title h3{margin:0;color:#33425b;font-size:15px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.mobile-partner-title span{display:block;margin-top:4px;color:#98a4b4;font-size:10px}.mobile-status{border-radius:99px;padding:5px 7px;font-size:10px;white-space:nowrap}.active-status{color:#14835e;background:#e7f8f0}.archived-status{color:#8e98a7;background:#f1f3f5}.mobile-contact{margin:11px 0 0;color:#8795a8;font-size:11px;line-height:1.45;overflow-wrap:anywhere}.mobile-balance-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;margin:11px 0 8px;padding:11px 0 9px;border-top:1px solid #edf0f5;border-bottom:1px solid #edf0f5}.mobile-balance-grid>div{min-width:0}.mobile-balance-grid span,.mobile-detail-summary span{display:block;margin-bottom:4px;color:#96a2b2;font-size:9px;white-space:nowrap}.mobile-balance-grid strong{display:block;color:#53627a;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.income-text{color:#128a63!important}.expense-text{color:#d25b62!important}.mobile-card-footer{display:flex;align-items:center;justify-content:space-between;gap:5px;color:#a0aaba;font-size:10px;line-height:1.4}.mobile-card-footer small{min-width:0;overflow-wrap:anywhere}.mobile-card-footer>div{display:flex;gap:3px;margin-left:auto}.mobile-text-button{min-width:44px;min-height:44px;padding:8px 9px;border:0;background:transparent;color:#2563eb;font-size:12px}.mobile-text-button.danger{color:#d05a61}.mobile-state{display:grid;place-content:center;justify-items:center;min-height:220px;padding:28px 16px;text-align:center;color:#8b98aa}.mobile-state.compact{min-height:160px}.mobile-state p{margin:0 0 14px;font-size:12px;line-height:1.5}.mobile-state h3{margin:10px 0 5px;color:#52617a;font-size:16px}.mobile-empty-icon{font-size:32px}.mobile-error p,.mobile-form-error{color:#b54e58}.mobile-primary,.mobile-outline{min-height:44px;display:inline-flex;align-items:center;justify-content:center;border-radius:8px;padding:9px 15px;font-size:13px;text-decoration:none;cursor:pointer}.mobile-primary{border:0;background:#2563eb;color:#fff;font-weight:600}.mobile-outline{border:1px solid #d6dfec;background:#fff;color:#52617a}.mobile-spinner{width:18px;height:18px;border:2px solid #dce7f8;border-top-color:#2563eb;border-radius:50%;animation:spin .7s linear infinite;margin-bottom:9px}.mobile-spinner.light{width:14px;height:14px;border-color:#ffffff66;border-top-color:#fff;margin:0 5px 0 0}.mobile-sheet-backdrop{position:fixed;inset:0;z-index:110;display:flex;align-items:flex-end;padding:8px 8px max(8px,env(safe-area-inset-bottom));background:#10213c66}.mobile-detail-backdrop{z-index:111}.mobile-ledger-backdrop{z-index:120}.mobile-sheet{width:100%;max-height:calc(100dvh - 16px);overflow:auto;border-radius:16px 16px 10px 10px;background:#fff;padding:20px 17px;box-shadow:0 -12px 50px #0c1c3540}.mobile-sheet-head{display:flex;align-items:flex-start;justify-content:space-between;gap:8px}.mobile-sheet-head h2{margin:0;color:#1e2a3d;font-size:19px;line-height:1.35;overflow-wrap:anywhere}.mobile-sheet-head p{margin:5px 0 0;color:#8996a9;font-size:11px;line-height:1.45}.mobile-close{min-width:44px;min-height:44px;border:0;border-radius:8px;background:transparent;color:#8b98aa;font-size:27px;line-height:1}.mobile-partner-form{margin-top:12px}.mobile-partner-form label{display:block;margin:13px 0;color:#59677d;font-size:13px;line-height:1.35}.mobile-partner-form input,.mobile-partner-form select,.mobile-partner-form textarea{display:block;width:100%;min-height:44px;margin-top:6px;border:1px solid #dbe2ee;border-radius:8px;padding:9px 10px;color:#44536a;background:#fff;font:inherit;font-size:16px;outline:0}.mobile-partner-form textarea{resize:vertical;line-height:1.45}.mobile-form-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px}.mobile-field-hint{margin:-3px 0 12px;color:#98a4b4;font-size:11px;line-height:1.5}.mobile-form-error{margin-top:12px;padding:10px 12px;border-radius:8px;background:#fff0f0;font-size:12px;line-height:1.5}.mobile-sheet-actions{display:flex;gap:8px;margin-top:19px}.mobile-sheet-actions>*{flex:1;min-height:44px}.mobile-detail-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin:16px 0 11px;padding:11px;border-radius:10px;background:#f7faff}.mobile-detail-summary>div{min-width:0}.mobile-detail-summary strong{display:block;color:#43536d;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.mobile-detail-actions{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px}.mobile-detail-actions>*{min-width:0;min-height:44px;justify-content:center;text-align:center}.mobile-ledger-cards{display:grid;gap:8px}.mobile-ledger-card{padding:10px 11px;border:1px solid #e7edf5;border-radius:10px;background:#fff}.mobile-ledger-head,.mobile-ledger-line{display:flex;align-items:center;justify-content:space-between;gap:10px;min-width:0}.mobile-ledger-head time{min-width:0;color:#8996a9;font-size:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.mobile-ledger-type{border-radius:99px;padding:5px 7px;color:#526d99;background:#eff4fb;font-size:10px;white-space:nowrap}.mobile-ledger-line{min-height:40px;border-top:1px solid #edf0f5;color:#8b98aa;font-size:11px}.mobile-ledger-line:first-of-type{margin-top:7px}.mobile-ledger-line strong,.mobile-ledger-line b{font-size:13px;overflow-wrap:anywhere;text-align:right}.mobile-ledger-note{margin:7px 0 0;color:#7d8ba0;font-size:11px;line-height:1.5;overflow-wrap:anywhere}.mobile-ledger-card footer{display:flex;justify-content:flex-end;margin-top:3px;border-top:1px solid #edf0f5}.mobile-reversed{min-height:44px;display:inline-flex;align-items:center;color:#9da6b3;font-size:11px}.mobile-detail-actions .mobile-outline{text-decoration:none}.mobile-detail-actions .mobile-primary{border:0}
@media(max-width:430px){.mobile-filter-row{grid-template-columns:1fr}.mobile-form-grid{grid-template-columns:1fr;gap:0}.mobile-detail-actions{grid-template-columns:1fr}.mobile-balance-grid strong{font-size:11px}.mobile-card-footer{align-items:flex-end;flex-wrap:wrap}.mobile-card-footer>div{width:100%;justify-content:flex-end;margin-left:0}}
.mobile-website{display:block;margin-top:7px;color:#2563eb;font-size:11px;line-height:1.45;overflow-wrap:anywhere;text-decoration:none}.mobile-website:hover{text-decoration:underline}.mobile-legacy-email{margin:5px 0 0;color:#9a7a45;font-size:10px;line-height:1.45;overflow-wrap:anywhere}.mobile-detail-contact{display:grid;gap:4px;margin:0 0 12px;padding:10px 11px;border-radius:9px;background:#f8faff;color:#6f8098;font-size:11px;line-height:1.45;overflow-wrap:anywhere}.mobile-detail-contact a{color:#2563eb;text-decoration:none;overflow-wrap:anywhere}.mobile-detail-contact a:hover{text-decoration:underline}.mobile-detail-contact span{color:#8f7650}
.mobile-balance-grid,.mobile-detail-summary{grid-template-columns:1fr}
</style>
