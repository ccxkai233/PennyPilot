<template>
  <div ref="root" class="trend-chart">
    <div class="trend-legend" aria-label="图例">
      <span class="legend-item"><i class="swatch income"></i>收入<strong>{{ formatMoney(incomeTotal) }}</strong></span>
      <span class="legend-item"><i class="swatch expense"></i>支出<strong>{{ formatMoney(expenseTotal) }}</strong></span>
      <span class="legend-item net">净收支<strong :class="net >= 0 ? 'income-text' : 'expense-text'">{{ net >= 0 ? '+' : '' }}{{ formatMoney(net) }}</strong></span>
    </div>
    <div v-if="!hasData" class="trend-empty">{{ emptyText }}</div>
    <div v-else class="trend-plot">
      <svg :viewBox="`0 0 ${width} ${height}`" :width="width" :height="height" role="img" :aria-label="`每日收支柱状图，共 ${days.length} 天`" @mouseleave="hover = -1">
        <g class="grid">
          <line v-for="tick in ticks" :key="tick" :x1="padding.left" :x2="width - padding.right" :y1="scaleY(tick)" :y2="scaleY(tick)" />
          <text v-for="tick in ticks" :key="`t-${tick}`" :x="padding.left - 6" :y="scaleY(tick) + 3" text-anchor="end" class="axis-text">{{ compactYuan(tick) }}</text>
        </g>
        <g v-for="(day, index) in days" :key="day.date" class="band" :class="{ 'is-hover': hover === index, 'is-future': day.future }">
          <rect class="band-hit" :x="bandX(index)" :y="padding.top" :width="bandWidth" :height="plotHeight" @mouseenter="hover = index" @touchstart.passive="hover = index" />
          <rect v-if="hover === index" class="band-highlight" :x="bandX(index)" :y="padding.top" :width="bandWidth" :height="plotHeight" />
          <path v-if="day.income" class="bar income" :d="barPath(barX(index, 0), scaleY(day.income), barWidth, baseline - scaleY(day.income))" />
          <path v-if="day.expense" class="bar expense" :d="barPath(barX(index, 1), scaleY(day.expense), barWidth, baseline - scaleY(day.expense))" />
          <text v-if="showLabel(index)" :x="bandX(index) + bandWidth / 2" :y="height - 6" text-anchor="middle" class="axis-text" :class="{ 'is-today': day.today }">{{ day.label }}</text>
        </g>
        <line class="baseline" :x1="padding.left" :x2="width - padding.right" :y1="baseline" :y2="baseline" />
        <g v-if="peak" class="peak-label">
          <text :x="Math.min(Math.max(barX(peak.index, peak.series) + barWidth / 2, padding.left + 24), width - padding.right - 24)" :y="scaleY(peak.value) - 6" text-anchor="middle" class="value-text">{{ compactYuan(peak.value) }}</text>
        </g>
      </svg>
      <div v-if="hover >= 0 && days[hover]" class="trend-tooltip" :style="tooltipStyle" role="status">
        <strong>{{ days[hover].date }}{{ days[hover].today ? ' · 今天' : '' }}</strong>
        <span><i class="swatch income"></i>收入 {{ formatMoney(days[hover].income) }}</span>
        <span><i class="swatch expense"></i>支出 {{ formatMoney(days[hover].expense) }}</span>
        <span class="tooltip-net">净收支 {{ days[hover].income - days[hover].expense >= 0 ? '+' : '' }}{{ formatMoney(days[hover].income - days[hover].expense) }} · {{ days[hover].count }} 笔</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { beijingDateAddDays, beijingDateIso, formatMoney } from '../api'

const props = defineProps({
  /** Map of YYYY-MM-DD → { income_cents, expense_cents, count }. */
  daily: { type: Object, default: () => ({}) },
  startDate: { type: String, required: true },
  endDate: { type: String, required: true },
  emptyText: { type: String, default: '本月还没有收支记录。' },
})

const root = ref(null)
const width = ref(640)
const height = 230
const padding = { top: 22, right: 12, bottom: 26, left: 52 }
const hover = ref(-1)
const todayIso = beijingDateIso(new Date())
let observer = null

const days = computed(() => {
  const result = []
  if (!/^\d{4}-\d{2}-\d{2}$/.test(props.startDate) || !/^\d{4}-\d{2}-\d{2}$/.test(props.endDate)) return result
  for (let cursor = props.startDate, guard = 0; cursor && cursor <= props.endDate && guard < 400; cursor = beijingDateAddDays(cursor, 1), guard += 1) {
    const bucket = props.daily?.[cursor] || {}
    result.push({
      date: cursor,
      label: String(Number(cursor.slice(8, 10))),
      income: Number(bucket.income_cents) || 0,
      expense: Number(bucket.expense_cents) || 0,
      count: Number(bucket.count) || 0,
      today: cursor === todayIso,
      future: cursor > todayIso,
    })
  }
  return result
})
const incomeTotal = computed(() => days.value.reduce((sum, day) => sum + day.income, 0))
const expenseTotal = computed(() => days.value.reduce((sum, day) => sum + day.expense, 0))
const net = computed(() => incomeTotal.value - expenseTotal.value)
const hasData = computed(() => days.value.some((day) => day.income || day.expense))
const maxValue = computed(() => Math.max(1, ...days.value.map((day) => Math.max(day.income, day.expense))))
const ticks = computed(() => niceTicks(maxValue.value, 4))
const topValue = computed(() => ticks.value[ticks.value.length - 1] || maxValue.value)
const plotHeight = height - padding.top - padding.bottom
const baseline = height - padding.bottom
const plotWidth = computed(() => Math.max(40, width.value - padding.left - padding.right))
const bandWidth = computed(() => plotWidth.value / Math.max(1, days.value.length))
const barWidth = computed(() => Math.max(2, Math.min(24, (bandWidth.value - 4) / 2 - 1)))
const peak = computed(() => {
  let best = null
  days.value.forEach((day, index) => {
    if (day.income > (best?.value || 0)) best = { index, series: 0, value: day.income }
    if (day.expense > (best?.value || 0)) best = { index, series: 1, value: day.expense }
  })
  return best
})
const tooltipStyle = computed(() => {
  if (hover.value < 0) return {}
  const x = bandX(hover.value) + bandWidth.value / 2
  const flip = x > width.value * 0.62
  return flip ? { right: `${Math.max(0, width.value - x + 8)}px`, top: '8px' } : { left: `${x + 8}px`, top: '8px' }
})

function niceTicks(max, count) {
  const rough = max / count
  const magnitude = 10 ** Math.floor(Math.log10(rough))
  const residual = rough / magnitude
  const step = (residual >= 5 ? 10 : residual >= 2 ? 5 : residual >= 1 ? 2 : 1) * magnitude
  const result = []
  for (let value = 0; value <= max + step - 1; value += step) result.push(value)
  return result.length ? result : [0, max]
}
function scaleY(value) { return baseline - (value / (topValue.value || 1)) * plotHeight }
function bandX(index) { return padding.left + index * bandWidth.value }
function barX(index, series) {
  const inner = barWidth.value * 2 + 2
  const offset = (bandWidth.value - inner) / 2
  return bandX(index) + offset + series * (barWidth.value + 2)
}
function barPath(x, y, w, h, radius = 4) {
  const r = Math.min(radius, w / 2, h)
  if (h <= 0) return ''
  return `M${x} ${y + h} V${y + r} Q${x} ${y} ${x + r} ${y} H${x + w - r} Q${x + w} ${y} ${x + w} ${y + r} V${y + h} Z`
}
function showLabel(index) {
  const total = days.value.length
  if (total <= 12) return true
  const every = width.value < 420 ? 7 : 5
  return index === 0 || (index + 1) % every === 0
}
function compactYuan(cents) {
  const yuan = cents / 100
  if (Math.abs(yuan) >= 10000) return `${(yuan / 10000).toFixed(yuan % 10000 === 0 ? 0 : 1)}万`
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: yuan < 100 ? 2 : 0 }).format(yuan)
}

onMounted(() => {
  if (typeof ResizeObserver === 'undefined' || !root.value) return
  observer = new ResizeObserver((entries) => {
    const measured = Math.floor(entries[0]?.contentRect?.width || 0)
    if (measured > 0) width.value = Math.max(280, measured)
  })
  observer.observe(root.value)
})
onBeforeUnmount(() => observer?.disconnect())
</script>

<style scoped>
.trend-chart{--income:#12966a;--expense:#dc5a61;--grid:#edf1f6;--axis:#8d9aae;--ink:#34435b;min-width:0}
.trend-legend{display:flex;flex-wrap:wrap;gap:6px 18px;margin-bottom:10px;color:#6f7d92;font-size:12px}
.legend-item{display:inline-flex;align-items:center;gap:6px}
.legend-item strong{color:var(--ink);font-weight:600;font-variant-numeric:tabular-nums}
.legend-item.net{margin-left:auto}
.income-text{color:var(--income)!important}.expense-text{color:var(--expense)!important}
.swatch{display:inline-block;width:10px;height:10px;border-radius:3px}
.swatch.income{background:var(--income)}.swatch.expense{background:var(--expense)}
.trend-plot{position:relative}
svg{display:block;max-width:100%;height:auto;overflow:visible}
.grid line{stroke:var(--grid);stroke-width:1}
.baseline{stroke:#d5dce7;stroke-width:1}
.axis-text{fill:var(--axis);font-size:10px;font-variant-numeric:tabular-nums}
.axis-text.is-today{fill:#2563eb;font-weight:700}
.value-text{fill:var(--ink);font-size:10px;font-weight:600;font-variant-numeric:tabular-nums}
.bar.income{fill:var(--income)}.bar.expense{fill:var(--expense)}
.band-hit{fill:transparent;cursor:crosshair}
.band-highlight{fill:#2563eb0d;pointer-events:none}
.band.is-future .bar{opacity:.4}
.trend-empty{display:grid;place-items:center;min-height:180px;border:1px dashed #dbe2ee;border-radius:10px;color:#93a0b1;font-size:13px}
.trend-tooltip{position:absolute;z-index:3;display:grid;gap:3px;min-width:150px;padding:9px 11px;border:1px solid #e1e8f2;border-radius:9px;background:#fff;box-shadow:0 8px 22px #243b5a1f;color:#4b5b73;font-size:11px;pointer-events:none}
.trend-tooltip strong{color:var(--ink);font-size:11px}
.trend-tooltip span{display:inline-flex;align-items:center;gap:6px;font-variant-numeric:tabular-nums}
.tooltip-net{color:#8492a6}
@media(max-width:600px){.legend-item.net{margin-left:0;flex-basis:100%}}
</style>
