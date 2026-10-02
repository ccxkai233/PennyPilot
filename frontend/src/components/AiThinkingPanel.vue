<template>
  <div class="ai-thinking" :class="{ 'is-active': active }">
    <button type="button" class="ai-thinking-head" :aria-expanded="open" @click="emit('update:open', !open)">
      <span v-if="active" class="ai-thinking-dots" aria-hidden="true"><i></i><i></i><i></i></span>
      <span v-else class="ai-thinking-done" aria-hidden="true">✓</span>
      <span class="ai-thinking-title">{{ active ? (stage || 'AI 正在思考…') : '思考过程' }}</span>
      <span class="ai-thinking-time">{{ seconds }} 秒</span>
      <span class="ai-thinking-toggle">{{ open ? '收起' : '展开' }}</span>
    </button>
    <div v-show="open" ref="body" class="ai-thinking-body" role="log" @scroll="trackPinned">
      <div v-if="!entries.length" class="ai-thinking-entry is-step">正在连接 AI…</div>
      <div v-for="(entry, index) in entries" :key="index" class="ai-thinking-entry" :class="`is-${entry.kind}`">
        <span v-if="entry.kind === 'step'" class="ai-thinking-at">{{ entry.at }}s</span>
        <span v-else class="ai-thinking-label">{{ entry.kind === 'reasoning' ? '思考摘要' : '模型输出' }}</span>
        <span class="ai-thinking-text">{{ displayText(entry) }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue'

const props = defineProps({
  // [{ kind: 'step' | 'reasoning' | 'output', text, at }]
  entries: { type: Array, default: () => [] },
  seconds: { type: Number, default: 0 },
  stage: { type: String, default: '' },
  active: { type: Boolean, default: false },
  open: { type: Boolean, default: true },
})
const emit = defineEmits(['update:open'])
const body = ref(null)
// Follow the newest line unless the reader scrolled up to look at something.
let pinned = true

function trackPinned() {
  const element = body.value
  if (element) pinned = element.scrollHeight - element.scrollTop - element.clientHeight < 24
}
function scrollToLatest() {
  nextTick(() => {
    const element = body.value
    if (element && pinned) element.scrollTop = element.scrollHeight
  })
}
// Reasoning summaries arrive as markdown headings separated by blank lines.
function displayText(entry) {
  return entry.kind === 'reasoning' ? String(entry.text || '').replace(/\*\*/g, '').replace(/\n{2,}/g, '\n').trim() : entry.text
}

watch(() => `${props.entries.length}:${props.entries[props.entries.length - 1]?.text?.length || 0}`, scrollToLatest)
watch(() => props.open, (open) => { if (open) { pinned = true; scrollToLatest() } })
</script>

<style scoped>
.ai-thinking{flex:1;min-width:0;max-width:560px;border:1px solid #dbe6f5;border-radius:12px;background:#f8fbff;overflow:hidden}
.ai-thinking-head{display:flex;align-items:center;gap:8px;width:100%;min-height:44px;padding:8px 12px;border:0;background:transparent;color:#61728a;font:inherit;font-size:12px;text-align:left;cursor:pointer}
.ai-thinking-head:focus-visible{outline:2px solid #3b82f6;outline-offset:-2px}
.ai-thinking-title{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#3f5068;font-weight:600}
.ai-thinking-time{color:#8a97aa;font-variant-numeric:tabular-nums;white-space:nowrap}
.ai-thinking-toggle{color:#2563eb;white-space:nowrap}
.ai-thinking-done{display:grid;place-items:center;flex:0 0 16px;width:16px;height:16px;border-radius:50%;background:#e7f8f0;color:#12845e;font-size:10px}
.ai-thinking-dots{display:inline-flex;align-items:center;gap:3px;flex:0 0 auto}
.ai-thinking-dots i{width:5px;height:5px;border-radius:50%;background:#6f9ae6;animation:ai-thinking-pulse 1.1s infinite ease-in-out}
.ai-thinking-dots i:nth-child(2){animation-delay:.15s}
.ai-thinking-dots i:nth-child(3){animation-delay:.3s}
.ai-thinking-body{display:grid;gap:6px;max-height:176px;overflow-y:auto;overscroll-behavior:contain;padding:9px 12px 11px;border-top:1px solid #e6eef9;color:#61728a;font-size:12px;line-height:1.55}
.ai-thinking-entry{min-width:0;overflow-wrap:anywhere}
.ai-thinking-entry.is-step{color:#7c8ba1}
.ai-thinking-at{display:inline-block;min-width:32px;color:#a3afc0;font-variant-numeric:tabular-nums}
.ai-thinking-label{display:block;margin-bottom:2px;color:#8a97aa;font-size:11px}
.ai-thinking-entry.is-reasoning .ai-thinking-text{display:block;padding-left:9px;border-left:2px solid #bcd3f7;color:#3f5068;white-space:pre-wrap}
.ai-thinking-entry.is-output .ai-thinking-text{display:block;padding:7px 9px;border-radius:8px;background:#eef3fa;color:#6b7a90;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:11px;white-space:pre-wrap;word-break:break-all}
@keyframes ai-thinking-pulse{0%,60%,100%{opacity:.35;transform:translateY(0)}30%{opacity:1;transform:translateY(-2px)}}
@media (prefers-reduced-motion:reduce){.ai-thinking-dots i{animation:none}}
</style>
