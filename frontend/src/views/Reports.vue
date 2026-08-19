<template>
  <AppLayout title="财务分析" subtitle="收支趋势、往来健康度与经营建议" :notice="notice">
    <template #actions><router-link class="secondary-link" to="/ai">✦ AI 记账</router-link><router-link class="outline-link" to="/settings">配置 AI</router-link></template>
    <MobileReports
      v-if="isMobile"
      :form="form"
      :report="report"
      :report-title="reportTitle"
      :report-date="reportDate"
      :report-text="reportText"
      :metrics="metrics"
      :sections="sections"
      :history="history"
      :analyzing="analyzing"
      :history-loading="historyLoading"
      :history-error="historyError"
      :generate="generate"
      :load-history="loadHistory"
      :show-history="showHistory"
    />
    <template v-else>
    <section class="analysis-control panel">
      <div><h2>生成分析报告</h2><p>选择周期后，AI 会基于你的汇总数据生成分析；报告会保存到历史记录。</p></div>
      <div class="control-row"><label>分析周期<select v-model="form.period"><option value="day">今天</option><option value="week">本周</option><option value="month">本月</option><option value="custom">自定义</option></select></label><template v-if="form.period === 'custom'"><label>开始日期<input v-model="form.start_date" type="date" /></label><label>结束日期<input v-model="form.end_date" type="date" /></label></template><button class="primary" type="button" :disabled="analyzing" @click="generate"><span v-if="analyzing" class="spinner"></span>{{ analyzing ? '分析中…' : '生成 AI 分析' }}</button></div>
    </section>
    <section v-if="report" class="report-panel panel">
      <div class="panel-title"><div><h2>{{ reportTitle }}</h2><p>{{ reportDate }}</p></div><span class="report-badge">AI 报告</span></div>
      <div class="report-body"><div v-if="metrics.length" class="metric-grid"><div v-for="metric in metrics" :key="metric.label" class="metric"><span>{{ metric.label }}</span><strong>{{ metric.value }}</strong><small v-if="metric.hint">{{ metric.hint }}</small></div></div><div v-if="sections.length" class="insight-grid"><article v-for="section in sections" :key="section.title" class="insight"><h3>{{ section.title }}</h3><p>{{ section.text }}</p><ul v-if="section.items.length"><li v-for="item in section.items" :key="item">{{ item }}</li></ul></article></div><div v-if="!metrics.length && !sections.length" class="plain-report">{{ reportText }}</div></div>
    </section>
    <section class="history panel"><div class="panel-title"><div><h2>分析历史</h2><p>可回看之前生成的报告</p></div><button class="text-button" type="button" @click="loadHistory">刷新</button></div><div v-if="historyLoading" class="state compact"><span class="spinner dark"></span><p>正在加载…</p></div><div v-else-if="historyError" class="state compact error-state"><p>{{ historyError }}</p></div><div v-else-if="!history.length" class="state compact"><p>还没有分析历史，先生成一份报告吧。</p></div><ul v-else class="history-list"><li v-for="item in history" :key="item.id || item.created_at"><div><strong>{{ item.period || '自定义周期' }}</strong><span>{{ formatDateTime(item.created_at || item.generated_at) }}</span></div><button class="text-button" type="button" @click="showHistory(item)">查看</button></li></ul></section>
    </template>
  </AppLayout>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import AppLayout from '../components/AppLayout.vue'
import { useViewport } from '../composables/useViewport'
import MobileReports from './MobileReports.vue'
import { aiApi, ApiError, formatDateTime, formatMoney } from '../api'

const { isMobile } = useViewport()

const form = reactive({ period: 'month', start_date: '', end_date: '' })
const report = ref(null)
const history = ref([])
const analyzing = ref(false)
const historyLoading = ref(false)
const historyError = ref('')
const notice = ref(null)
const reportTitle = computed(() => report.value?.title || report.value?.period_label || `本${form.period === 'month' ? '月' : form.period === 'week' ? '周' : '期'} AI 分析`)
const reportDate = computed(() => formatDateTime(report.value?.created_at || report.value?.generated_at || new Date()))
const reportText = computed(() => String(report.value?.content || report.value?.report || report.value?.summary || report.value?.text || '暂无文字分析。'))
const metrics = computed(() => {
  const raw = report.value?.metrics || report.value?.summary_metrics || report.value?.data_summary?.metrics || report.value?.data_summary || []
  if (Array.isArray(raw)) return raw.map((item) => ({ label: item.label || item.name || '指标', value: item.value ?? item.amount ?? '—', hint: item.hint || item.change || '' }))
  if (raw && typeof raw === 'object') return Object.entries(raw).filter(([, value]) => value === null || ['string', 'number', 'boolean'].includes(typeof value)).slice(0, 6).map(([label, value]) => ({ label: ({ transaction_count: '交易笔数', income_cents: '收入', expense_cents: '支出', net_cents: '净收支' })[label] || label, value: label.endsWith('_cents') ? formatMoney(value) : value, hint: '' }))
  return []
})
const sections = computed(() => {
  const categoryData = report.value?.data_summary?.categories
  const partnerData = report.value?.data_summary?.partner_health
  const raw = report.value?.sections || report.value?.insights || report.value?.recommendations || (categoryData ? [{ title: '分类结构', text: '本周期各分类金额概览。', items: Object.entries(categoryData).slice(0, 6).map(([name, value]) => `${name}：收入 ${formatMoney(value.income_cents || 0)}，支出 ${formatMoney(value.expense_cents || 0)}`) }] : [])
  let result = []
  if (Array.isArray(raw)) result = raw.map((item, index) => typeof item === 'string' ? { title: `洞察 ${index + 1}`, text: item, items: [] } : { title: item.title || item.name || `洞察 ${index + 1}`, text: item.text || item.summary || item.content || '', items: Array.isArray(item.items) ? item.items : Array.isArray(item.points) ? item.points : [] })
  else if (raw && typeof raw === 'object') result = Object.entries(raw).map(([title, value]) => ({ title, text: typeof value === 'string' ? value : value?.summary || value?.text || '', items: Array.isArray(value?.items) ? value.items : [] }))
  if (Array.isArray(partnerData) && partnerData.length) {
    result.push({
      title: '往来账户健康度',
      text: '当前授信占用、预存余额与本周期流水汇总。',
      items: partnerData.slice(0, 8).map((item) => `${item.name || '往来单位'}：预存 ${formatMoney(item.prepaid_balance_cents || 0)}，授信 ${formatMoney(item.credit_used_cents || 0)} / ${formatMoney(item.credit_limit_cents || 0)}，本期 ${item.period_ledger_count || 0} 笔`),
    })
  }
  return result
})

async function generate() {
  if (form.period === 'custom' && (!form.start_date || !form.end_date)) { notice.value = { type: 'error', message: '请选择自定义周期的开始和结束日期。' }; return }
  analyzing.value = true; notice.value = null
  try { report.value = await aiApi.analyze({ period: form.period, start_date: form.start_date || undefined, end_date: form.end_date || undefined, save_history: true }); notice.value = { type: 'success', message: 'AI 分析报告已生成。' }; await loadHistory() }
  catch (error) { notice.value = { type: 'error', message: error instanceof ApiError ? error.message : '分析失败，请检查 AI 配置。' } }
  finally { analyzing.value = false }
}
async function loadHistory() { historyLoading.value = true; historyError.value = ''; try { history.value = await aiApi.history({ limit: 20 }) } catch (error) { historyError.value = error instanceof ApiError ? error.message : '历史记录加载失败。' } finally { historyLoading.value = false } }
async function showHistory(item) {
  if (!item?.id) { report.value = item?.report || item; return }
  try { report.value = await aiApi.report(item.id) } catch { report.value = item?.report || item }
}
onMounted(loadHistory)
</script>

<style scoped>
.panel{background:#fff;border-radius:13px;box-shadow:0 2px 8px #243b5a0d}.analysis-control{margin-top:28px;padding:22px 24px;display:flex;align-items:flex-end;justify-content:space-between;gap:20px}.analysis-control h2,.panel-title h2{margin:0;color:#34435b;font-size:17px}.analysis-control p,.panel-title p{margin:6px 0 0;color:#8a97aa;font-size:12px}.control-row{display:flex;align-items:flex-end;gap:9px;flex-wrap:wrap}.control-row label{color:#7b8aa0;font-size:11px}.control-row select,.control-row input{display:block;margin-top:5px;height:37px;border:1px solid #dbe2ee;border-radius:8px;padding:0 9px;color:#44536a;background:#fff;font:inherit;font-size:12px}.primary{border:0;border-radius:8px;background:#2563eb;color:#fff;padding:10px 16px;font-size:13px;font-weight:600;cursor:pointer;white-space:nowrap}.primary:hover{background:#1d4ed8}.primary:disabled{opacity:.65;cursor:wait}.secondary-link,.outline-link{color:#2563eb;text-decoration:none;font-size:12px;font-weight:600;padding:10px 2px;white-space:nowrap}.outline-link{border:1px solid #d6dfec;border-radius:8px;padding:9px 11px;font-weight:500}.report-panel,.history{margin-top:18px;overflow:hidden}.panel-title{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;padding:20px 24px;border-bottom:1px solid #edf0f5}.report-badge{color:#2563eb;background:#edf4ff;border-radius:99px;padding:5px 8px;font-size:10px}.report-body{padding:20px 24px 24px}.metric-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:11px;margin-bottom:17px}.metric{border:1px solid #e8eef7;border-radius:10px;padding:13px}.metric span{display:block;color:#8c99ab;font-size:11px}.metric strong{display:block;color:#34435b;font-size:19px;margin-top:7px}.metric small{color:#8492a6;font-size:10px}.insight-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}.insight{border-radius:10px;background:#f8faff;padding:15px}.insight h3{margin:0;color:#4b5b74;font-size:14px}.insight p{margin:8px 0 0;color:#66758c;line-height:1.65;font-size:13px;white-space:pre-line}.insight ul{padding-left:18px;margin:8px 0 0;color:#6e7c91;font-size:12px;line-height:1.7}.plain-report{white-space:pre-wrap;color:#59677d;font-size:13px;line-height:1.8}.history{margin-bottom:25px}.text-button{border:0;background:transparent;color:#2563eb;font-size:12px;cursor:pointer;padding:4px}.history-list{list-style:none;padding:0 24px;margin:0}.history-list li{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:15px 0;border-bottom:1px solid #edf0f5}.history-list li:last-child{border-bottom:0}.history-list strong{display:block;color:#53627a;font-size:13px}.history-list span{display:block;color:#9ba6b5;font-size:10px;margin-top:4px}.state{min-height:140px;display:grid;place-content:center;justify-items:center;text-align:center;color:#8b98aa;padding:20px}.state p{font-size:13px}.state.compact{min-height:130px}.error-state{color:#ba4b53}.spinner{width:15px;height:15px;border:2px solid #ffffff66;border-top-color:#fff;border-radius:50%;animation:spin .7s linear infinite;display:inline-block;vertical-align:-3px;margin-right:5px}.spinner.dark{border-color:#dce7f8;border-top-color:#2563eb;margin-bottom:5px}@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:760px){.analysis-control{margin-top:20px;padding:18px 16px;display:block}.control-row{margin-top:15px}.control-row label{flex:1 1 calc(50% - 5px)}.control-row .primary{flex:1 1 100%}.panel-title,.report-body{padding-left:16px;padding-right:16px}.history-list{padding:0 16px}}
@media(max-width:760px){
  .secondary-link,.outline-link{display:inline-flex;align-items:center;min-height:40px;font-size:11px}
  .analysis-control{min-width:0}
  .analysis-control>div:first-child{min-width:0}
  .analysis-control h2,.analysis-control p{overflow-wrap:anywhere;line-height:1.5}
  .control-row{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));align-items:stretch;gap:10px;margin-top:16px;min-width:0}
  .control-row label{display:block;min-width:0;line-height:1.4}
  .control-row select,.control-row input{width:100%;min-width:0;height:44px;min-height:44px;font-size:16px}
  .control-row .primary{grid-column:1/-1;width:100%;min-height:44px}
  .panel-title{gap:8px}
  .panel-title>div{min-width:0}
  .panel-title h2,.panel-title p{overflow-wrap:anywhere;line-height:1.5}
  .report-badge{flex:0 0 auto;white-space:nowrap}
  .report-body{min-width:0}
  .metric-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}
  .metric{min-width:0;padding:12px}
  .metric strong{font-size:17px;overflow-wrap:anywhere;word-break:break-word}
  .metric small{display:block;overflow-wrap:anywhere;line-height:1.4}
  .insight-grid{grid-template-columns:1fr}
  .insight{min-width:0;padding:14px}
  .insight h3,.insight p,.insight li{overflow-wrap:anywhere;word-break:break-word}
  .insight p{line-height:1.6}
  .history-list{min-width:0}
  .history-list li{min-height:58px;align-items:center}
  .history-list li>div{min-width:0}
  .history-list strong,.history-list span{overflow-wrap:anywhere;word-break:break-word}
  .text-button{min-height:44px;min-width:44px;padding:10px 7px;display:inline-flex;align-items:center;justify-content:center}
}
@media(max-width:390px){
  .analysis-control,.panel-title,.report-body{padding-left:13px;padding-right:13px}
  .control-row{grid-template-columns:1fr;gap:9px}
  .control-row .primary{grid-column:auto}
  .metric-grid{grid-template-columns:1fr}
  .history-list{padding-left:13px;padding-right:13px}
  .secondary-link,.outline-link{font-size:10px;padding-left:4px;padding-right:4px}
}
</style>
