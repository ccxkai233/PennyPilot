<template>
  <article class="report-card" :class="{ 'is-compact': compact }">
    <header class="report-head">
      <div class="report-brand"><span class="report-brand-mark" aria-hidden="true">₱</span>PennyPilot · 收支报告</div>
      <h1 class="report-title">{{ report.periodLabel || '收支报告' }}</h1>
      <p class="report-meta">
        <span v-if="dateRange">{{ dateRange }}</span>
        <span v-if="scopeText">{{ scopeText }}</span>
        <span v-if="report.generatedAt">生成于 {{ formatDateTime(report.generatedAt) }}</span>
      </p>
    </header>

    <section v-if="hasTotals" class="report-stats" aria-label="收支总览">
      <div class="report-stat">
        <span class="report-stat-label"><i class="dot dot-income" aria-hidden="true"></i>收入</span>
        <strong class="report-stat-value">{{ money(summary.income_cents) }}</strong>
        <small class="report-stat-hint">{{ countText(summary.income_count) }}<template v-if="change('income_cents')"> · {{ change('income_cents') }}</template></small>
      </div>
      <div class="report-stat">
        <span class="report-stat-label"><i class="dot dot-expense" aria-hidden="true"></i>支出</span>
        <strong class="report-stat-value">{{ money(summary.expense_cents) }}</strong>
        <small class="report-stat-hint">{{ countText(summary.expense_count) }}<template v-if="change('expense_cents')"> · {{ change('expense_cents') }}</template></small>
      </div>
      <div class="report-stat is-net">
        <span class="report-stat-label"><i class="dot dot-net" aria-hidden="true"></i>净收支</span>
        <strong class="report-stat-value">{{ signedMoney(summary.net_cents) }}</strong>
        <small class="report-stat-hint">共 {{ summary.transaction_count || 0 }} 笔<template v-if="summary.previous"> · {{ summary.previous.transaction_count ? `上期 ${signedMoney(summary.previous.net_cents)}` : '上期无记录' }}</template></small>
      </div>
    </section>

    <section v-if="topExpenses.length" class="report-shares" aria-label="支出构成">
      <h2 class="report-section-title">支出构成</h2>
      <ol class="report-share-list">
        <li v-for="item in topExpenses" :key="item.name" class="report-share">
          <div class="report-share-row"><span class="report-share-name">{{ item.name }}</span><span class="report-share-value">{{ money(item.amount_cents) }}<em>{{ percent(item.share) }}</em></span></div>
          <div class="report-share-track" aria-hidden="true"><div class="report-share-bar" :style="{ width: `${Math.max(2, Math.round(item.share * 100))}%` }"></div></div>
        </li>
      </ol>
    </section>

    <section v-for="(block, index) in sections" :key="index" class="report-section" :class="{ 'is-advice': block.advice }">
      <h2 v-if="block.title" class="report-section-title">{{ block.title }}</h2>
      <template v-for="(part, partIndex) in block.parts" :key="partIndex">
        <p v-if="part.type === 'text'" class="report-text">{{ part.text }}</p>
        <ul v-else-if="part.type === 'bullets'" class="report-bullets"><li v-for="(line, lineIndex) in part.items" :key="lineIndex">{{ line }}</li></ul>
        <ol v-else class="report-numbered"><li v-for="(line, lineIndex) in part.items" :key="lineIndex">{{ line }}</li></ol>
      </template>
    </section>

    <footer class="report-foot">
      <span>数据来自 PennyPilot 账本{{ report.model ? ` · ${report.model} 生成` : ' · AI 生成' }}</span>
      <span>仅供参考，以账本流水为准</span>
    </footer>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import { formatDateTime, formatMoney } from '../api'

const props = defineProps({
  // { content, periodLabel, startDate, endDate, summary, generatedAt, model }
  report: { type: Object, required: true },
  compact: { type: Boolean, default: false },
})

const summary = computed(() => props.report?.summary || {})
const hasTotals = computed(() => Number.isFinite(Number(summary.value.income_cents)) || Number.isFinite(Number(summary.value.expense_cents)))
const topExpenses = computed(() => (summary.value.top_expense_categories || []).slice(0, 5))
const dateRange = computed(() => {
  const { startDate, endDate, periodLabel } = props.report || {}
  if (!startDate && !endDate) return ''
  const text = `${startDate || '最早记录'} 至 ${endDate || ''}`.trim()
  return String(periodLabel || '').includes(text) ? '' : text
})
const scopeText = computed(() => {
  const scope = summary.value.scope || {}
  const parts = [scope.account && `账户 ${scope.account}`, scope.category && `分类 ${scope.category}`, scope.partner && `往来 ${scope.partner}`, scope.direction === 'income' ? '仅收入' : scope.direction === 'expense' ? '仅支出' : '']
  return parts.filter(Boolean).join(' · ')
})

function money(cents) { return formatMoney(cents || 0, '¥') }
function signedMoney(cents) {
  const value = Number(cents || 0)
  return `${value > 0 ? '+' : value < 0 ? '−' : ''}${formatMoney(Math.abs(value), '¥')}`
}
function percent(share) { return `${Math.round((Number(share) || 0) * 1000) / 10}%` }
function countText(count) { return `${count || 0} 笔` }
function change(key) {
  const delta = summary.value.change?.[key]
  const previous = summary.value.previous?.[key]
  if (!Number.isFinite(Number(delta)) || !Number.isFinite(Number(previous))) return ''
  if (!previous) return delta ? '上期无记录' : ''
  const ratio = Math.round((delta / Math.abs(previous)) * 100)
  if (!ratio) return '与上期持平'
  return `较上期${ratio > 0 ? '↑' : '↓'} ${Math.abs(ratio)}%`
}

// The model writes plain text: a 【title】 line, 【section】 headings, "•" bullets
// and "1." lists.  Turn that into blocks the template can style.
const sections = computed(() => {
  const lines = String(props.report?.content || '').replace(/\*\*/g, '').split(/\r?\n/)
  const blocks = []
  let current = null
  const ensure = () => { if (!current) { current = { title: '', advice: false, parts: [] }; blocks.push(current) } return current }
  const pushItem = (type, text) => {
    const block = ensure()
    const last = block.parts[block.parts.length - 1]
    if (last && last.type === type) last.items.push(text)
    else block.parts.push({ type, items: [text] })
  }
  for (const raw of lines) {
    const line = raw.trim()
    if (!line) continue
    const heading = line.match(/^【(.+?)】[:：]?$/) || line.match(/^#{1,3}\s+(.+)$/)
    if (heading) {
      const title = heading[1].trim()
      if (/报告$/.test(title) && !blocks.length) continue // the card header already shows the period
      current = { title, advice: /建议|提醒|总结/.test(title), parts: [] }
      blocks.push(current)
      continue
    }
    const bullet = line.match(/^[•·\-*]\s*(.+)$/)
    if (bullet) { pushItem('bullets', bullet[1]); continue }
    const numbered = line.match(/^\d+[.、)]\s*(.+)$/)
    if (numbered) { pushItem('numbered', numbered[1]); continue }
    ensure().parts.push({ type: 'text', text: line })
  }
  return blocks
})
</script>

<style scoped>
.report-card{--ink:#1d2a3d;--ink-2:#52627a;--ink-3:#8a97aa;--line:#e6ecf4;--surface:#fff;--accent:#2563eb;--accent-soft:#eaf1fd;--income:#12966a;--expense:#dc5a61;width:100%;max-width:640px;box-sizing:border-box;padding:26px 28px 20px;border-radius:18px;background:var(--surface);color:var(--ink);font-family:Inter,system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;font-size:13px;line-height:1.6;box-shadow:0 1px 0 #0b1b3308}
.report-head{padding-bottom:16px;border-bottom:1px solid var(--line)}
.report-brand{display:inline-flex;align-items:center;gap:7px;color:var(--accent);font-size:12px;font-weight:600;letter-spacing:.02em}
.report-brand-mark{display:grid;place-items:center;width:20px;height:20px;border-radius:6px;background:var(--accent);color:#fff;font-size:12px}
.report-title{margin:10px 0 0;font-size:24px;font-weight:700;letter-spacing:-.01em;line-height:1.25}
.report-meta{display:flex;flex-wrap:wrap;gap:4px 14px;margin:8px 0 0;color:var(--ink-3);font-size:12px}
.report-stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:18px}
.report-stat{min-width:0;display:grid;gap:3px;padding:12px 14px;border:1px solid var(--line);border-radius:12px;background:#fafcff}
.report-stat.is-net{background:var(--accent-soft);border-color:#d6e4fb}
.report-stat-label{display:inline-flex;align-items:center;gap:6px;color:var(--ink-2);font-size:12px}
.dot{width:8px;height:8px;border-radius:50%}.dot-income{background:var(--income)}.dot-expense{background:var(--expense)}.dot-net{background:var(--accent)}
.report-stat-value{font-size:19px;font-weight:700;font-variant-numeric:tabular-nums;letter-spacing:-.01em;overflow-wrap:anywhere}
.report-stat-hint{color:var(--ink-3);font-size:11px}
.report-shares{margin-top:20px}
.report-section-title{margin:0 0 8px;color:var(--ink);font-size:14px;font-weight:700}
.report-section-title::before{content:'';display:inline-block;width:3px;height:13px;margin-right:8px;border-radius:2px;background:var(--accent);vertical-align:-2px}
.report-share-list{list-style:none;margin:0;padding:0;display:grid;gap:8px}
.report-share-row{display:flex;justify-content:space-between;gap:12px;font-size:12px}
.report-share-name{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--ink-2)}
.report-share-value{flex:0 0 auto;font-variant-numeric:tabular-nums;color:var(--ink)}
.report-share-value em{margin-left:6px;color:var(--ink-3);font-style:normal}
.report-share-track{height:6px;margin-top:4px;border-radius:3px;background:#edf2f9;overflow:hidden}
.report-share-bar{height:100%;border-radius:3px;background:var(--accent)}
.report-section{margin-top:20px}
.report-section.is-advice{padding:14px 16px;border-radius:12px;background:#fbf8ef}
.report-section.is-advice .report-section-title::before{background:#d9a21b}
.report-text{margin:0 0 6px;color:var(--ink-2);overflow-wrap:anywhere}
.report-bullets,.report-numbered{margin:0 0 6px;padding-left:18px;color:var(--ink-2)}
.report-bullets li,.report-numbered li{margin:3px 0;overflow-wrap:anywhere}
.report-bullets li::marker{color:var(--accent)}
.report-numbered li::marker{color:var(--ink-3);font-variant-numeric:tabular-nums}
.report-foot{display:flex;justify-content:space-between;flex-wrap:wrap;gap:4px 12px;margin-top:22px;padding-top:12px;border-top:1px solid var(--line);color:var(--ink-3);font-size:11px}
.report-card.is-compact{padding:20px 16px 16px;border-radius:14px}
.report-card.is-compact .report-title{font-size:20px}
.report-card.is-compact .report-stats{grid-template-columns:1fr 1fr}
.report-card.is-compact .report-stat.is-net{grid-column:1/-1}
.report-card.is-compact .report-stat-value{font-size:17px}
</style>
