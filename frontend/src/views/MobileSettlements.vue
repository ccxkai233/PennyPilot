<template>
  <div class="mobile-settlements">
    <section class="mobile-settlement-picker">
      <div class="mobile-settlement-picker-head">
        <div>
          <p class="mobile-eyebrow">每日结算</p>
          <h2>{{ monthLabel }}</h2>
          <p class="mobile-muted">选择日期查看快照，或生成新的日结</p>
        </div>
        <div class="mobile-month-actions">
          <button type="button" aria-label="上个月" @click="monthChange(-1)">‹</button>
          <button type="button" aria-label="下个月" @click="monthChange(1)">›</button>
        </div>
      </div>

      <div class="mobile-date-strip" role="listbox" aria-label="结算日期">
        <button
          v-for="day in monthDays"
          :key="day.iso"
          type="button"
          class="mobile-date-cell"
          :class="{ selected: day.iso === selectedDate, today: day.iso === todayIso, settled: Boolean(day.snapshot) && !day.snapshot.is_live, live: day.snapshot?.is_live }"
          :aria-selected="day.iso === selectedDate"
          @click="selectDate(day.iso)"
        >
          <span>{{ day.day }}</span>
          <small>{{ shortWeekday(day.iso) }}</small>
          <i v-if="day.snapshot" :aria-label="day.snapshot.is_live ? '今日进行中' : '已结算'"></i>
        </button>
      </div>

      <div class="mobile-settlement-actions">
        <button type="button" class="mobile-quiet-button" @click="goCurrentMonth">回到本月</button>
        <button type="button" class="mobile-quiet-button" :disabled="loading" @click="loadSnapshots">刷新数据</button>
        <button type="button" class="mobile-quiet-button accent" :disabled="recalculateLoading" @click="openRecalculate">重算历史</button>
      </div>
    </section>

    <p v-if="errorMessage" class="mobile-settlement-error" role="alert">{{ errorMessage }} <button type="button" @click="loadSnapshots">重试</button></p>

    <section class="mobile-settlement-detail">
      <div v-if="detailLoading" class="mobile-settlement-state"><span class="mobile-spinner"></span><p>正在加载日结详情…</p></div>
      <div v-else-if="detailError" class="mobile-settlement-state mobile-error"><p>{{ detailError }}</p><button type="button" class="mobile-outline" @click="loadDetail(selectedDate)">重试</button></div>
      <template v-else-if="selectedSnapshot">
        <header class="mobile-detail-head">
          <div>
            <p class="mobile-eyebrow">{{ selectedSnapshot.is_live ? '今日实时收支' : '日结快照' }}</p>
            <h2>{{ dateLabel(selectedSnapshot.settlement_date) }}</h2>
            <time>{{ formatDateTime(selectedSnapshot.settled_at || selectedSnapshot.executed_at || selectedSnapshot.created_at) }}</time>
          </div>
          <span class="mobile-status" :class="{ live: selectedSnapshot.is_live, recalculated: selectedSnapshot.is_recalculated }">{{ selectedSnapshot.is_live ? '实时预览' : selectedSnapshot.is_recalculated ? '已重算' : '已锁定' }}</span>
        </header>

        <div class="mobile-net-card" :class="{ negative: selectedSnapshot.net_cents < 0 }">
          <span>当日净收支</span>
          <strong>{{ signedMoney(selectedSnapshot.net_cents) }}</strong>
          <small>收入 − 支出</small>
        </div>

        <div class="mobile-settlement-metrics">
          <div><span>收入</span><strong class="income-text">{{ formatMoney(selectedSnapshot.income_cents) }}</strong></div>
          <div><span>支出</span><strong class="expense-text">{{ formatMoney(selectedSnapshot.expense_cents) }}</strong></div>
          <div><span>总资产口径</span><strong>{{ formatMoney(selectedSnapshot.total_assets_cents) }}</strong></div>
        </div>

        <div class="mobile-account-section">
          <div class="mobile-section-head"><div><h3>往来账户快照</h3><small>当前未结算余额 · 当日结算金额</small></div><span>{{ accounts.length }} 个账户</span></div>
          <div v-if="!accounts.length" class="mobile-inline-empty">当日没有往来账户明细。</div>
          <div v-else class="mobile-account-cards">
            <article v-for="account in accounts" :key="account.key" class="mobile-account-card">
              <header><div><strong>{{ account.name }}</strong><small>{{ account.typeLabel }}</small></div><b :class="account.settlement_cents >= 0 ? 'income-text' : 'expense-text'">{{ signedMoney(account.settlement_cents) }}</b></header>
              <div class="mobile-account-lines">
                <div><span>当前未结算余额</span><strong>{{ formatMoney(account.unsettled_cents) }}</strong></div>
                <div><span>当日结算金额</span><strong :class="account.settlement_cents >= 0 ? 'income-text' : 'expense-text'">{{ signedMoney(account.settlement_cents) }}</strong></div>
              </div>
            </article>
          </div>
        </div>
        <p v-if="selectedSnapshot.notes" class="mobile-snapshot-note">备注：{{ selectedSnapshot.notes }}</p>
      </template>
      <div v-else class="mobile-settlement-state mobile-empty-state">
        <div class="mobile-empty-icon">▣</div>
        <h3>{{ selectedDate ? dateLabel(selectedDate) : '选择一个日期' }}</h3>
        <p>{{ selectedDate ? (isFuture(selectedDate) ? '未来日期不能生成日结。' : selectedDate === todayIso ? '今日尚未结束，暂无正式日结。' : '该日期还没有快照。') : '从上方日期条选择日期查看详情。' }}</p>
        <button v-if="selectedDate && canGenerate(selectedDate)" type="button" class="mobile-primary" :disabled="runLoading" @click="runSelected">{{ runLoading ? '生成中…' : '生成该日日结' }}</button>
      </div>
    </section>

    <section class="mobile-settlement-history">
      <header class="mobile-section-head">
        <div><p class="mobile-eyebrow">可追溯记录</p><h2>历史快照</h2></div>
        <span>{{ snapshotCount }} 份快照{{ snapshots.some((item) => item.is_live) ? ' · 今日实时' : '' }}</span>
      </header>
      <div v-if="loading" class="mobile-settlement-state compact"><span class="mobile-spinner"></span><p>正在加载…</p></div>
      <div v-else-if="!sortedSnapshots.length" class="mobile-settlement-state compact"><p>暂无日结记录。</p></div>
      <div v-else class="mobile-history-list">
        <button v-for="snapshot in sortedSnapshots" :key="snapshot.id || snapshot.settlement_date" type="button" class="mobile-history-card" :class="{ active: snapshot.settlement_date === selectedDate }" @click="selectDate(snapshot.settlement_date)">
          <span class="mobile-history-date"><strong>{{ shortDate(snapshot.settlement_date) }}</strong><small>{{ shortWeekday(snapshot.settlement_date) }}</small></span>
          <span><small>净收支</small><b :class="snapshot.net_cents >= 0 ? 'income-text' : 'expense-text'">{{ signedMoney(snapshot.net_cents) }}</b></span>
          <span class="mobile-history-status">{{ snapshot.is_live ? '实时' : snapshot.is_recalculated ? '重算' : '已锁定' }}</span>
        </button>
      </div>
    </section>

    <div v-if="recalculateOpen" class="mobile-sheet-backdrop" @click.self="closeRecalculate">
      <section class="mobile-sheet" role="dialog" aria-modal="true" aria-labelledby="mobile-recalculate-title">
        <header class="mobile-sheet-head">
          <div><p class="mobile-eyebrow">批量更新</p><h2 id="mobile-recalculate-title">重算历史日结</h2><p>从选定日期开始重新生成快照。</p></div>
          <button type="button" class="mobile-close" aria-label="关闭" @click="closeRecalculate">×</button>
        </header>
        <label class="mobile-date-label">起始日期<input :value="recalcDate" type="date" :max="yesterdayIso" @input="setRecalcDate($event.target.value)" /></label>
        <p class="mobile-warning">重算会更新快照内容并保留重算标记，不会删除原始流水。</p>
        <p v-if="recalculateError" class="mobile-form-error" role="alert">{{ recalculateError }}</p>
        <footer class="mobile-sheet-actions"><button type="button" class="mobile-outline" :disabled="recalculateLoading" @click="closeRecalculate">取消</button><button type="button" class="mobile-primary" :disabled="recalculateLoading || !recalcDate" @click="recalculate">{{ recalculateLoading ? '重算中…' : '确认重算' }}</button></footer>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, toRefs } from 'vue'
import { formatDateTime, formatMoney } from '../api'

const props = defineProps({
  calendarMonth: { type: String, default: '' },
  monthLabel: { type: String, default: '' },
  calendarDays: { type: Array, default: () => [] },
  todayIso: { type: String, default: '' },
  selectedDate: { type: String, default: '' },
  snapshots: { type: Array, default: () => [] },
  snapshotCount: { type: Number, default: 0 },
  sortedSnapshots: { type: Array, default: () => [] },
  selectedSnapshot: { type: Object, default: null },
  accounts: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  detailLoading: { type: Boolean, default: false },
  errorMessage: { type: String, default: '' },
  detailError: { type: String, default: '' },
  runLoading: { type: Boolean, default: false },
  recalculateOpen: { type: Boolean, default: false },
  recalculateLoading: { type: Boolean, default: false },
  recalculateError: { type: String, default: '' },
  recalcDate: { type: String, default: '' },
  yesterdayIso: { type: String, default: '' },
  monthChange: { type: Function, required: true },
  goCurrentMonth: { type: Function, required: true },
  loadSnapshots: { type: Function, required: true },
  loadDetail: { type: Function, required: true },
  selectDate: { type: Function, required: true },
  runSelected: { type: Function, required: true },
  openRecalculate: { type: Function, required: true },
  closeRecalculate: { type: Function, required: true },
  recalculate: { type: Function, required: true },
  setRecalcDate: { type: Function, required: true },
  isFuture: { type: Function, required: true },
  canGenerate: { type: Function, required: true },
  dateLabel: { type: Function, required: true },
  shortDate: { type: Function, required: true },
  weekday: { type: Function, required: true },
  signedMoney: { type: Function, required: true },
})

const { monthLabel, calendarDays, todayIso, selectedDate, snapshots, snapshotCount, sortedSnapshots, selectedSnapshot, accounts, loading, detailLoading, errorMessage, detailError, runLoading, recalculateOpen, recalculateLoading, recalculateError, recalcDate, yesterdayIso, monthChange, goCurrentMonth, loadSnapshots, loadDetail, selectDate, runSelected, openRecalculate, closeRecalculate, recalculate, setRecalcDate, isFuture, canGenerate, dateLabel, shortDate, weekday, signedMoney } = toRefs(props)
const monthDays = computed(() => calendarDays.value.filter((item) => item.inMonth))
function shortWeekday(value) {
  return String(weekday.value(value) || '').replace(/^星期/, '周')
}
</script>

<style scoped>
.mobile-date-cell.live i{background:#2563eb!important}.mobile-status.live{color:#2563eb!important;background:#edf4ff!important}.mobile-section-head small{display:block;margin-top:4px;color:#9aa6b5;font-size:10px}
.mobile-settlements{display:grid;gap:12px;margin-top:2px;padding-bottom:10px;min-width:0}.mobile-settlement-picker,.mobile-settlement-detail,.mobile-settlement-history{background:#fff;border:1px solid #e7edf5;border-radius:16px;box-shadow:0 4px 16px #243b5a0b;overflow:hidden}.mobile-settlement-picker{padding:16px}.mobile-settlement-picker-head,.mobile-detail-head,.mobile-section-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}.mobile-settlement-picker-head>div,.mobile-detail-head>div,.mobile-section-head>div{min-width:0}.mobile-eyebrow{margin:0 0 4px;color:#7e8da4;font-size:10px;letter-spacing:.04em}.mobile-settlement-picker h2,.mobile-detail-head h2,.mobile-section-head h2{margin:0;color:#26364e;font-size:18px;line-height:1.35;overflow-wrap:anywhere}.mobile-muted{margin:5px 0 0;color:#8d9aad;font-size:11px;line-height:1.45}.mobile-month-actions{display:flex;gap:5px}.mobile-month-actions button{width:44px;height:44px;border:1px solid #dce5f1;border-radius:10px;background:#fff;color:#52617a;font-size:24px;line-height:1;cursor:pointer}.mobile-month-actions button:active,.mobile-month-actions button:focus-visible{border-color:#9bbdf0;background:#f1f6ff;color:#2563eb}.mobile-date-strip{display:flex;gap:7px;overflow-x:auto;margin:15px -5px 0;padding:2px 5px 7px;scrollbar-width:none;overscroll-behavior-x:contain}.mobile-date-strip::-webkit-scrollbar{display:none}.mobile-date-cell{position:relative;display:flex;flex:0 0 48px;flex-direction:column;align-items:center;justify-content:center;gap:3px;min-height:64px;border:1px solid #e5ebf4;border-radius:11px;background:#fff;color:#64748b;cursor:pointer}.mobile-date-cell span{font-size:16px;font-weight:700;line-height:1}.mobile-date-cell small{font-size:10px;color:#9aa6b5}.mobile-date-cell.today span{display:grid;place-items:center;width:27px;height:27px;border-radius:50%;background:#edf4ff;color:#2563eb}.mobile-date-cell.selected{border-color:#2563eb;background:#2563eb;color:#fff;box-shadow:0 4px 10px #2563eb30}.mobile-date-cell.selected small{color:#dce9ff}.mobile-date-cell.selected.today span{background:#fff;color:#2563eb}.mobile-date-cell i{position:absolute;right:7px;top:7px;width:5px;height:5px;border-radius:50%;background:#29a477}.mobile-date-cell.selected i{background:#a7f3d0}.mobile-settlement-actions{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin-top:10px}.mobile-quiet-button{min-height:42px;border:1px solid #e0e7f0;border-radius:9px;background:#f8faff;color:#52617a;font-size:11px;white-space:nowrap;cursor:pointer}.mobile-quiet-button.accent{color:#2563eb;background:#f0f6ff}.mobile-quiet-button:disabled{opacity:.55;cursor:wait}.mobile-settlement-error{margin:0;padding:11px 12px;border-radius:10px;background:#fff0f0;color:#b54e58;font-size:12px;line-height:1.5}.mobile-settlement-error button{margin-left:5px;border:0;background:transparent;color:#2563eb;font:inherit;font-weight:600}.mobile-settlement-detail{padding:16px}.mobile-detail-head{padding-bottom:13px;border-bottom:1px solid #edf1f6}.mobile-detail-head time{display:block;margin-top:5px;color:#9aa6b5;font-size:10px}.mobile-status{display:inline-flex;align-items:center;min-height:27px;padding:4px 8px;border-radius:99px;background:#e8f8f0;color:#17825d;font-size:10px;white-space:nowrap}.mobile-status.recalculated{background:#f2eafd;color:#8058a8}.mobile-net-card{display:flex;flex-direction:column;gap:5px;margin-top:14px;padding:16px;border-radius:13px;background:linear-gradient(135deg,#edf5ff,#f8fbff);border:1px solid #dbe9fc}.mobile-net-card.negative{background:linear-gradient(135deg,#fff3f3,#fffafa);border-color:#f6d8da}.mobile-net-card span{color:#70819a;font-size:11px}.mobile-net-card strong{color:#2563eb;font-size:29px;line-height:1.1;overflow-wrap:anywhere}.mobile-net-card.negative strong{color:#d25b62}.mobile-net-card small{color:#95a2b4;font-size:10px}.mobile-settlement-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin-top:9px}.mobile-settlement-metrics>div{min-width:0;padding:10px;border:1px solid #e8eef7;border-radius:10px;background:#fbfcff}.mobile-settlement-metrics span{display:block;color:#8b99ab;font-size:9px;white-space:nowrap}.mobile-settlement-metrics strong{display:block;margin-top:5px;color:#44546d;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.income-text{color:#128a63!important}.expense-text{color:#d25b62!important}.mobile-account-section{margin-top:16px}.mobile-section-head{align-items:center;padding-bottom:9px}.mobile-section-head h3{margin:0;color:#4b5b73;font-size:14px}.mobile-section-head span,.mobile-section-head>span{color:#98a4b4;font-size:10px;white-space:nowrap}.mobile-account-cards{display:grid;gap:8px}.mobile-account-card{padding:11px;border:1px solid #e7edf5;border-radius:11px;background:#fff}.mobile-account-card header{display:flex;align-items:flex-start;justify-content:space-between;gap:8px}.mobile-account-card header>div{min-width:0}.mobile-account-card header strong{display:block;color:#3f5068;font-size:13px;overflow-wrap:anywhere}.mobile-account-card header small{display:block;margin-top:3px;color:#98a4b4;font-size:10px}.mobile-account-card header>b{font-size:13px;white-space:nowrap}.mobile-account-lines{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin-top:10px;padding-top:9px;border-top:1px solid #edf1f6}.mobile-account-lines span{display:block;color:#98a4b4;font-size:9px;white-space:nowrap}.mobile-account-lines strong{display:block;margin-top:4px;color:#52617a;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.mobile-account-note,.mobile-snapshot-note{margin:8px 0 0;color:#7d8ba0;font-size:10px;line-height:1.5;overflow-wrap:anywhere}.mobile-snapshot-note{padding-top:11px;border-top:1px solid #edf1f6}.mobile-inline-empty{padding:20px 10px;border:1px dashed #dce5f0;border-radius:10px;color:#9aa6b5;text-align:center;font-size:11px}.mobile-settlement-state{display:grid;place-content:center;justify-items:center;min-height:210px;padding:25px 10px;text-align:center;color:#8b98aa}.mobile-settlement-state.compact{min-height:120px}.mobile-settlement-state h3{margin:10px 0 5px;color:#52617a;font-size:16px}.mobile-settlement-state p{margin:0 0 14px;font-size:12px;line-height:1.55}.mobile-empty-icon{font-size:31px;color:#a7b8d0}.mobile-error{color:#b54e58}.mobile-primary,.mobile-outline{min-height:44px;display:inline-flex;align-items:center;justify-content:center;border-radius:9px;padding:9px 14px;font-size:12px;cursor:pointer}.mobile-primary{border:0;background:#2563eb;color:#fff;font-weight:600}.mobile-outline{border:1px solid #d6dfec;background:#fff;color:#52617a}.mobile-spinner{display:inline-block;width:18px;height:18px;margin-bottom:9px;border:2px solid #dce7f8;border-top-color:#2563eb;border-radius:50%;animation:mobile-settlement-spin .7s linear infinite}@keyframes mobile-settlement-spin{to{transform:rotate(360deg)}}.mobile-settlement-history{margin-bottom:0}.mobile-settlement-history>.mobile-section-head{padding:16px;border-bottom:1px solid #edf1f6}.mobile-settlement-history>.mobile-section-head h2{font-size:16px}.mobile-history-list{display:grid;gap:8px;padding:10px}.mobile-history-card{display:grid;grid-template-columns:1.15fr 1fr auto;align-items:center;gap:8px;width:100%;min-width:0;padding:11px;border:1px solid #e7edf5;border-radius:11px;background:#fff;text-align:left;color:#52617a;cursor:pointer}.mobile-history-card.active{border-color:#9bbdf0;background:#f5f9ff}.mobile-history-card>span:not(.mobile-history-date){min-width:0}.mobile-history-card small{display:block;margin-bottom:4px;color:#9aa6b5;font-size:9px}.mobile-history-card b{display:block;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.mobile-history-date strong{display:block;color:#34435b;font-size:13px}.mobile-history-date small{margin:3px 0 0}.mobile-history-status{color:#8b98aa;font-size:10px;white-space:nowrap}.mobile-sheet-backdrop{position:fixed;inset:0;z-index:120;display:flex;align-items:flex-end;padding:8px 8px max(8px,env(safe-area-inset-bottom));background:#10213c66}.mobile-sheet{width:100%;max-height:calc(100dvh - 16px);overflow:auto;border-radius:16px 16px 10px 10px;background:#fff;padding:20px 17px;box-shadow:0 -12px 50px #0c1c3540}.mobile-sheet-head{display:flex;align-items:flex-start;justify-content:space-between;gap:8px}.mobile-sheet-head h2{margin:0;color:#1e2a3d;font-size:19px;line-height:1.35}.mobile-sheet-head p{margin:5px 0 0;color:#8996a9;font-size:11px;line-height:1.45}.mobile-close{min-width:44px;min-height:44px;border:0;border-radius:8px;background:transparent;color:#8b98aa;font-size:27px;line-height:1}.mobile-date-label{display:block;margin-top:16px;color:#59677d;font-size:13px}.mobile-date-label input{display:block;width:100%;min-height:46px;margin-top:6px;border:1px solid #dbe2ee;border-radius:9px;padding:9px 10px;color:#44536a;background:#fff;font:inherit;font-size:16px}.mobile-warning{margin:13px 0 0;padding:11px;border-radius:9px;background:#fff8e8;color:#936b1b;font-size:11px;line-height:1.6}.mobile-form-error{margin-top:11px;padding:10px 11px;border-radius:8px;background:#fff0f0;color:#a83232;font-size:12px;line-height:1.5}.mobile-sheet-actions{display:flex;gap:8px;margin-top:19px}.mobile-sheet-actions>*{flex:1;min-height:44px}@media(max-width:380px){.mobile-settlement-picker,.mobile-settlement-detail{padding:13px}.mobile-settlement-picker-head h2,.mobile-detail-head h2{font-size:17px}.mobile-month-actions button{width:42px;height:42px}.mobile-date-cell{flex-basis:45px;min-height:60px}.mobile-settlement-actions{gap:5px}.mobile-quiet-button{font-size:10px;padding-left:5px;padding-right:5px}.mobile-settlement-metrics strong{font-size:11px}.mobile-account-lines{gap:5px}.mobile-history-card{grid-template-columns:1fr auto}.mobile-history-card>span:nth-child(2){text-align:right}.mobile-history-status{grid-column:1/-1;text-align:right;margin-top:-4px}}
.mobile-account-lines{grid-template-columns:repeat(2,minmax(0,1fr))}
</style>
