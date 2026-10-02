<template>
  <div class="mobile-reports-page">
    <section class="mobile-report-card mobile-report-charts">
      <div class="mobile-report-section-head">
        <div><p class="mobile-report-eyebrow">本月图表</p><h2>本月收支</h2></div>
        <button class="mobile-report-quiet" type="button" :disabled="monthLoading" @click="loadMonthSummary">刷新</button>
      </div>
      <div v-if="monthLoading && !monthSummary" class="mobile-report-state"><span class="mobile-report-spinner dark"></span><p>正在加载本月数据…</p></div>
      <div v-else-if="monthError" class="mobile-report-state is-error"><p>{{ monthError }}</p><button class="mobile-report-view" type="button" @click="loadMonthSummary">重试</button></div>
      <div v-else-if="monthSummary" class="mobile-report-chart-list">
        <p class="mobile-report-chart-summary">{{ monthRange.start }} 至 {{ monthRange.end }}</p>
        <article class="mobile-report-chart"><h3>每日收支趋势</h3><CashflowTrendChart :daily="monthSummary.daily || {}" :start-date="monthRange.start" :end-date="monthRange.end" /></article>
        <article class="mobile-report-chart"><h3>分类占比</h3><CategoryDonutChart :categories="monthSummary.categories || {}" /></article>
      </div>
    </section>

    <section class="mobile-report-card mobile-report-control">
      <div class="mobile-report-heading">
        <p class="mobile-report-eyebrow">经营洞察</p>
        <h2>生成分析报告</h2>
        <p>选择一个周期，AI 会基于汇总数据给出摘要和建议。</p>
      </div>
      <form class="mobile-report-form" @submit.prevent="generate">
        <label>分析周期<select v-model="form.period"><option value="day">今天</option><option value="week">本周</option><option value="month">本月</option><option value="year">本年</option><option value="all">全部</option><option value="custom">自定义</option></select></label>
        <template v-if="form.period === 'custom'">
          <label>开始日期<input v-model="form.start_date" type="date" /></label>
          <label>结束日期<input v-model="form.end_date" type="date" /></label>
        </template>
        <button class="mobile-report-primary" type="submit" :disabled="analyzing"><span v-if="analyzing" class="mobile-report-spinner"></span>{{ analyzing ? '分析中…' : '生成 AI 分析' }}</button>
      </form>
    </section>

    <section v-if="report" class="mobile-report-card mobile-report-result">
      <div class="mobile-report-result-head">
        <div>
          <p class="mobile-report-eyebrow">最新报告</p>
          <h2>{{ reportTitle }}</h2>
          <time>{{ reportDate }}</time>
        </div>
        <span class="mobile-report-badge">AI 报告</span>
      </div>
      <div v-if="metrics.length" class="mobile-report-metrics">
        <article v-for="metric in metrics" :key="metric.label" class="mobile-report-metric">
          <span>{{ metric.label }}</span>
          <strong>{{ metric.value }}</strong>
          <small v-if="metric.hint">{{ metric.hint }}</small>
        </article>
      </div>
      <div v-if="sections.length" class="mobile-report-insights">
        <article v-for="section in sections" :key="section.title" class="mobile-report-insight">
          <h3>{{ section.title }}</h3>
          <p>{{ section.text }}</p>
          <ul v-if="section.items.length"><li v-for="item in section.items" :key="item">{{ item }}</li></ul>
        </article>
      </div>
      <p v-if="!metrics.length && !sections.length" class="mobile-report-plain">{{ reportText }}</p>
    </section>

    <section class="mobile-report-card mobile-report-history">
      <div class="mobile-report-section-head">
        <div><p class="mobile-report-eyebrow">可追溯</p><h2>分析历史</h2></div>
        <button class="mobile-report-quiet" type="button" @click="loadHistory">刷新</button>
      </div>
      <div v-if="historyLoading" class="mobile-report-state"><span class="mobile-report-spinner dark"></span><p>正在加载…</p></div>
      <div v-else-if="historyError" class="mobile-report-state is-error"><p>{{ historyError }}</p></div>
      <div v-else-if="!history.length" class="mobile-report-state"><p>还没有分析历史，先生成一份报告吧。</p></div>
      <ul v-else class="mobile-report-history-list">
        <li v-for="item in history" :key="item.id || item.created_at">
          <div class="mobile-report-history-copy">
            <strong>{{ periodLabels[item.period] || item.period || '自定义周期' }}</strong>
            <time>{{ formatDateTime(item.created_at || item.generated_at) }}</time>
          </div>
          <button class="mobile-report-view" type="button" @click="showHistory(item)">查看报告</button>
        </li>
      </ul>
    </section>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import CashflowTrendChart from '../components/CashflowTrendChart.vue'
import CategoryDonutChart from '../components/CategoryDonutChart.vue'
import { beijingDateIso, formatDateTime } from '../api'

const periodLabels = { day: '今日', week: '本周', month: '本月', year: '本年', all: '全部' }
const props = defineProps({
  form: { type: Object, required: true },
  report: { type: Object, default: null },
  reportTitle: { type: String, default: 'AI 分析' },
  reportDate: { type: String, default: '' },
  reportText: { type: String, default: '' },
  metrics: { type: Array, default: () => [] },
  sections: { type: Array, default: () => [] },
  history: { type: Array, default: () => [] },
  analyzing: { type: Boolean, default: false },
  historyLoading: { type: Boolean, default: false },
  historyError: { type: String, default: '' },
  generate: { type: Function, required: true },
  loadHistory: { type: Function, required: true },
  showHistory: { type: Function, required: true },
  monthSummary: { type: Object, default: null },
  monthLoading: { type: Boolean, default: false },
  monthError: { type: String, default: '' },
  loadMonthSummary: { type: Function, default: () => {} },
})
const todayIso = beijingDateIso(new Date())
const monthRange = computed(() => {
  const period = props.monthSummary?.period || {}
  return { start: period.start_date || `${todayIso.slice(0, 7)}-01`, end: period.end_date || todayIso }
})
</script>

<style scoped>
.mobile-reports-page{display:grid;gap:14px;margin-top:18px;padding-bottom:18px}.mobile-report-card{background:#fff;border:1px solid #e7edf6;border-radius:16px;box-shadow:0 4px 16px #243b5a0a;overflow:hidden}.mobile-report-control{padding:19px 16px 16px}.mobile-report-heading{min-width:0}.mobile-report-eyebrow{margin:0 0 4px;color:#7e8da4;font-size:11px;letter-spacing:.03em}.mobile-report-heading h2,.mobile-report-result-head h2,.mobile-report-section-head h2{margin:0;color:#26364e;font-size:18px;line-height:1.35;overflow-wrap:anywhere}.mobile-report-heading>p:last-child{margin:7px 0 0;color:#8a97aa;font-size:12px;line-height:1.55;overflow-wrap:anywhere}.mobile-report-form{display:grid;gap:11px;margin-top:16px}.mobile-report-form label{display:block;color:#53637a;font-size:12px;line-height:1.45}.mobile-report-form input,.mobile-report-form select{display:block;width:100%;min-height:46px;margin-top:6px;border:1px solid #dbe4f0;border-radius:10px;padding:10px 11px;background:#fff;color:#3f5068;font:inherit;font-size:16px;outline:0}.mobile-report-form input:focus,.mobile-report-form select:focus{border-color:#3b82f6}.mobile-report-primary{display:inline-flex;align-items:center;justify-content:center;width:100%;min-height:46px;margin-top:2px;border:0;border-radius:10px;background:#2563eb;color:#fff;font-size:14px;font-weight:600;cursor:pointer}.mobile-report-primary:disabled{opacity:.6;cursor:wait}.mobile-report-result{padding-bottom:16px}.mobile-report-result-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;padding:17px 16px 14px;border-bottom:1px solid #edf1f6}.mobile-report-result-head>div{min-width:0}.mobile-report-result-head time{display:block;margin-top:6px;color:#9aa6b5;font-size:10px}.mobile-report-badge{display:inline-flex;align-items:center;min-height:27px;padding:4px 8px;border-radius:99px;background:#edf4ff;color:#2563eb;font-size:10px;white-space:nowrap}.mobile-report-metrics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px;padding:15px 16px 0}.mobile-report-metric{min-width:0;padding:12px;border:1px solid #e8eef7;border-radius:11px;background:#fbfcff}.mobile-report-metric span{display:block;color:#8b99ab;font-size:11px;line-height:1.4;overflow-wrap:anywhere}.mobile-report-metric strong{display:block;margin-top:6px;color:#34435b;font-size:18px;line-height:1.3;overflow-wrap:anywhere;word-break:break-word}.mobile-report-metric small{display:block;margin-top:4px;color:#8492a6;font-size:10px;line-height:1.4;overflow-wrap:anywhere}.mobile-report-insights{display:grid;gap:10px;padding:15px 16px 0}.mobile-report-insight{min-width:0;padding:14px;border-radius:11px;background:#f8faff}.mobile-report-insight h3{margin:0;color:#4b5b74;font-size:14px;line-height:1.4;overflow-wrap:anywhere}.mobile-report-insight p{margin:7px 0 0;color:#66758c;font-size:13px;line-height:1.65;white-space:pre-line;overflow-wrap:anywhere;word-break:break-word}.mobile-report-insight ul{margin:8px 0 0;padding-left:18px;color:#6e7c91;font-size:12px;line-height:1.7}.mobile-report-insight li{overflow-wrap:anywhere;word-break:break-word}.mobile-report-plain{margin:0;padding:17px 16px 19px;color:#59677d;font-size:13px;line-height:1.8;white-space:pre-wrap;overflow-wrap:anywhere}.mobile-report-history{margin-bottom:8px}.mobile-report-section-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;padding:16px;border-bottom:1px solid #edf1f6}.mobile-report-section-head>div{min-width:0}.mobile-report-section-head h2{font-size:16px}.mobile-report-quiet,.mobile-report-view{display:inline-flex;align-items:center;justify-content:center;min-height:42px;border-radius:9px;cursor:pointer;font-size:12px}.mobile-report-quiet{flex:0 0 auto;padding:8px;border:0;background:#f1f5fb;color:#2563eb}.mobile-report-state{min-height:120px;display:grid;place-content:center;justify-items:center;padding:20px 16px;color:#8997aa;text-align:center;font-size:13px}.mobile-report-state p{margin:0;line-height:1.5}.mobile-report-state.is-error{color:#b54e58}.mobile-report-history-list{list-style:none;margin:0;padding:0 16px}.mobile-report-history-list li{display:flex;align-items:center;justify-content:space-between;gap:10px;min-width:0;padding:14px 0;border-bottom:1px solid #edf1f6}.mobile-report-history-list li:last-child{border-bottom:0}.mobile-report-history-copy{min-width:0}.mobile-report-history-copy strong{display:block;color:#506078;font-size:13px;line-height:1.45;overflow-wrap:anywhere}.mobile-report-history-copy time{display:block;margin-top:4px;color:#9ba6b6;font-size:10px}.mobile-report-view{flex:0 0 auto;padding:8px 10px;border:1px solid #d7e1ee;background:#fff;color:#2563eb;white-space:nowrap}.mobile-report-spinner{display:inline-block;width:15px;height:15px;margin-right:5px;border:2px solid #ffffff66;border-top-color:#fff;border-radius:50%;animation:mobile-report-spin .7s linear infinite;vertical-align:-3px}.mobile-report-spinner.dark{margin:0;border-color:#dce7f8;border-top-color:#2563eb}@keyframes mobile-report-spin{to{transform:rotate(360deg)}}
.mobile-report-chart-list{display:grid;gap:12px;padding:14px 16px 16px}.mobile-report-chart-summary{margin:0;color:#8a97aa;font-size:11px}.mobile-report-chart{min-width:0;padding:13px;border:1px solid #e8eef7;border-radius:12px}.mobile-report-chart h3{margin:0 0 10px;color:#4b5b74;font-size:14px}.mobile-report-state .mobile-report-view{margin-top:10px}
@media(max-width:380px){.mobile-report-control{padding-left:13px;padding-right:13px}.mobile-report-result-head,.mobile-report-section-head{padding-left:13px;padding-right:13px}.mobile-report-metrics,.mobile-report-insights{padding-left:13px;padding-right:13px}.mobile-report-plain{padding-left:13px;padding-right:13px}.mobile-report-history-list{padding-left:13px;padding-right:13px}.mobile-report-history-list li{align-items:flex-start;flex-direction:column;gap:8px}.mobile-report-view{width:100%}}
</style>
