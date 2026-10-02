<template>
  <div class="donut-chart">
    <div class="donut-toolbar">
      <div class="donut-toggle" role="group" aria-label="收支方向">
        <button type="button" :class="{ selected: direction === 'expense' }" @click="direction = 'expense'">支出</button>
        <button type="button" :class="{ selected: direction === 'income' }" @click="direction = 'income'">收入</button>
      </div>
      <span class="donut-total">共 {{ slices.length ? formatMoney(total) : '¥ 0.00' }} · {{ count }} 笔</span>
    </div>
    <div v-if="!slices.length" class="donut-empty">{{ direction === 'expense' ? '本月暂无支出记录。' : '本月暂无收入记录。' }}</div>
    <div v-else class="donut-body">
      <svg viewBox="0 0 200 200" class="donut-svg" role="img" :aria-label="`${direction === 'expense' ? '支出' : '收入'}分类占比环形图`" @mouseleave="active = -1">
        <g v-for="(slice, index) in slices" :key="slice.name">
          <path :d="arcPath(slice)" :fill="slice.color" class="slice" :class="{ 'is-dim': active >= 0 && active !== index, 'is-active': active === index }" @mouseenter="active = index" @touchstart.passive="active = index" />
        </g>
        <text x="100" y="94" text-anchor="middle" class="center-label">{{ active >= 0 ? slices[active].name : (direction === 'expense' ? '支出合计' : '收入合计') }}</text>
        <text x="100" y="114" text-anchor="middle" class="center-value">{{ active >= 0 ? percent(slices[active].share) : compactYuan(total) }}</text>
        <text v-if="active >= 0" x="100" y="130" text-anchor="middle" class="center-sub">{{ formatMoney(slices[active].amount) }}</text>
      </svg>
      <ul class="donut-legend">
        <li v-for="(slice, index) in slices" :key="slice.name" :class="{ 'is-active': active === index }" @mouseenter="active = index" @mouseleave="active = -1">
          <i class="swatch" :style="{ background: slice.color }"></i>
          <span class="legend-name">{{ slice.name }}</span>
          <span class="legend-amount">{{ formatMoney(slice.amount) }}</span>
          <span class="legend-share">{{ percent(slice.share) }}</span>
        </li>
      </ul>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { formatMoney } from '../api'

const props = defineProps({
  /** Map of category name → { income_cents, expense_cents, count }. */
  categories: { type: Object, default: () => ({}) },
  initialDirection: { type: String, default: 'expense' },
  maxSlices: { type: Number, default: 6 },
})

// Fixed categorical order (validated: adjacent-pair CVD ΔE ≥ 8, normal ≥ 15).
// Slot colors follow the entity's rank order in this chart only; the
// legend always names every slice so identity never depends on hue alone.
const PALETTE = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#4a3aa7', '#e34948', '#0d366b']
const OTHER_COLOR = '#a3adbc'
const direction = ref(props.initialDirection === 'income' ? 'income' : 'expense')
const active = ref(-1)
const key = computed(() => (direction.value === 'income' ? 'income_cents' : 'expense_cents'))
const entries = computed(() => Object.entries(props.categories || {})
  .map(([name, data]) => ({ name, amount: Number(data?.[key.value]) || 0, count: Number(data?.count) || 0 }))
  .filter((item) => item.amount > 0)
  .sort((a, b) => b.amount - a.amount))
const total = computed(() => entries.value.reduce((sum, item) => sum + item.amount, 0))
const count = computed(() => entries.value.reduce((sum, item) => sum + item.count, 0))
const slices = computed(() => {
  const list = entries.value
  const head = list.length > props.maxSlices ? list.slice(0, props.maxSlices - 1) : list
  const rest = list.slice(head.length)
  const result = head.map((item, index) => ({ ...item, color: PALETTE[index % PALETTE.length], share: item.amount / (total.value || 1) }))
  if (rest.length) {
    const amount = rest.reduce((sum, item) => sum + item.amount, 0)
    result.push({ name: `其他（${rest.length} 类）`, amount, count: rest.reduce((sum, item) => sum + item.count, 0), color: OTHER_COLOR, share: amount / (total.value || 1) })
  }
  let cursor = 0
  return result.map((slice) => {
    const start = cursor
    cursor += slice.share
    return { ...slice, start, end: cursor }
  })
})

const RADIUS = 82
const INNER = 54
const GAP = 0.012 // fraction of the circle kept as a surface gap between slices
function polar(radius, fraction) {
  const angle = fraction * Math.PI * 2 - Math.PI / 2
  return [100 + radius * Math.cos(angle), 100 + radius * Math.sin(angle)]
}
function arcPath(slice) {
  const gap = slices.value.length > 1 ? Math.min(GAP, (slice.end - slice.start) / 3) : 0
  const start = slice.start + gap / 2
  const end = slice.end - gap / 2
  if (end - start >= 0.9999) {
    return `M${polar(RADIUS, 0).join(' ')} A${RADIUS} ${RADIUS} 0 1 1 ${polar(RADIUS, 0.5).join(' ')} A${RADIUS} ${RADIUS} 0 1 1 ${polar(RADIUS, 0).join(' ')} M${polar(INNER, 0).join(' ')} A${INNER} ${INNER} 0 1 0 ${polar(INNER, 0.5).join(' ')} A${INNER} ${INNER} 0 1 0 ${polar(INNER, 0).join(' ')} Z`
  }
  const large = end - start > 0.5 ? 1 : 0
  const [ox, oy] = polar(RADIUS, start)
  const [ex, ey] = polar(RADIUS, end)
  const [ix, iy] = polar(INNER, end)
  const [sx, sy] = polar(INNER, start)
  return `M${ox} ${oy} A${RADIUS} ${RADIUS} 0 ${large} 1 ${ex} ${ey} L${ix} ${iy} A${INNER} ${INNER} 0 ${large} 0 ${sx} ${sy} Z`
}
function percent(share) { return `${(share * 100).toFixed(share * 100 >= 10 ? 0 : 1)}%` }
function compactYuan(cents) {
  const yuan = cents / 100
  if (Math.abs(yuan) >= 100000) return `${(yuan / 10000).toFixed(1)}万`
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: yuan >= 1000 ? 0 : 2 }).format(yuan)
}
</script>

<style scoped>
.donut-chart{min-width:0}
.donut-toolbar{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px}
.donut-toggle{display:inline-grid;grid-template-columns:1fr 1fr;gap:3px;padding:3px;border-radius:9px;background:#f1f5fb}
.donut-toggle button{min-width:56px;border:0;border-radius:7px;padding:6px 10px;background:transparent;color:#7c8ba1;font-size:12px;cursor:pointer}
.donut-toggle button.selected{background:#fff;color:#2563eb;box-shadow:0 1px 5px #263b6114;font-weight:600}
.donut-total{color:#6f7d92;font-size:12px;font-variant-numeric:tabular-nums}
.donut-empty{display:grid;place-items:center;min-height:180px;border:1px dashed #dbe2ee;border-radius:10px;color:#93a0b1;font-size:13px}
.donut-body{display:grid;grid-template-columns:minmax(150px,190px) minmax(0,1fr);align-items:center;gap:14px}
.donut-svg{display:block;width:100%;max-width:190px;height:auto;margin:0 auto}
.slice{transition:opacity .15s;cursor:pointer}
.slice.is-dim{opacity:.35}
.center-label{fill:#8492a6;font-size:11px}
.center-value{fill:#34435b;font-size:20px;font-weight:700}
.center-sub{fill:#6f7d92;font-size:11px;font-variant-numeric:tabular-nums}
.donut-legend{list-style:none;margin:0;padding:0;display:grid;gap:4px;min-width:0}
.donut-legend li{display:grid;grid-template-columns:10px minmax(0,1fr) auto 44px;align-items:center;gap:8px;padding:5px 7px;border-radius:7px;color:#53627a;font-size:12px;cursor:default}
.donut-legend li.is-active{background:#f4f7fc}
.swatch{display:inline-block;width:10px;height:10px;border-radius:3px}
.legend-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.legend-amount{color:#34435b;font-weight:600;font-variant-numeric:tabular-nums;white-space:nowrap}
.legend-share{color:#8492a6;text-align:right;font-variant-numeric:tabular-nums}
@media(max-width:600px){.donut-body{grid-template-columns:1fr}.donut-svg{max-width:170px}}
</style>
