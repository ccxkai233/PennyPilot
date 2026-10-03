<template>
  <span class="date-segment" :class="{ 'is-invalid': editing && text && !preview }">
    <input
      ref="input"
      v-model="text"
      type="text"
      inputmode="numeric"
      autocomplete="off"
      :placeholder="placeholder"
      :aria-label="label"
      @focus="editing = true"
      @mouseup="selectSegmentAtCaret"
      @keydown="onKeydown"
      @beforeinput="onBeforeInput"
      @input="onInput"
      @blur="commit"
    />
    <small v-if="editing && text && !canonical" class="date-segment-hint">{{ preview ? `识别为 ${preview}` : '无法识别，试试 20261001 或 10-1' }}</small>
    <small v-else-if="pending" class="date-segment-hint is-pending">按回车应用</small>
  </span>
</template>

<script setup>
// A date box that edits like a native date field (click a segment, type to
// replace it, the caret moves on by itself) but also accepts loose input such
// as 202610 or 10-1, which is normalized when the value is committed.
import { computed, nextTick, ref, watch } from 'vue'
import { normalizeDateInput } from '../dateInput'

const props = defineProps({
  modelValue: { type: String, default: '' },
  edge: { type: String, default: 'start' },
  label: { type: String, default: '日期' },
  placeholder: { type: String, default: '如 20261001 / 202610' },
  // 'enter': the value is only applied on Enter, so each keystroke does not
  // trigger a query; 'change' also applies on blur and segment completion.
  applyOn: { type: String, default: 'change' },
})
const emit = defineEmits(['update:modelValue'])

const CANONICAL = /^(\d{4})-(\d{2})-(\d{2})$/
const SEGMENTS = [{ start: 0, end: 4, length: 4 }, { start: 5, end: 7, length: 2 }, { start: 8, end: 10, length: 2 }]
const input = ref(null)
const text = ref(props.modelValue)
const editing = ref(false)
// Digits typed into the current segment since it was selected.
let buffer = ''
let activeSegment = -1

watch(() => props.modelValue, (value) => { text.value = value })
const canonical = computed(() => CANONICAL.test(text.value))
const preview = computed(() => normalizeDateInput(text.value, { edge: props.edge }))
const pending = computed(() => props.applyOn === 'enter' && canonical.value && text.value !== props.modelValue)

function selectSegment(index) {
  const segment = SEGMENTS[index]
  if (!segment || !canonical.value) return
  activeSegment = index
  buffer = ''
  nextTick(() => input.value?.setSelectionRange(segment.start, segment.end))
}
function segmentAt(position) {
  return SEGMENTS.findIndex((segment) => position >= segment.start && position <= segment.end)
}
function selectSegmentAtCaret() {
  if (!canonical.value) return
  // The browser places the caret after mouseup; read it on the next frame.
  requestAnimationFrame(() => {
    const element = input.value
    if (!element || document.activeElement !== element || element.selectionStart !== element.selectionEnd) return
    const index = segmentAt(element.selectionStart)
    selectSegment(index >= 0 ? index : 2)
  })
}
function replaceSegment(index, value) {
  const segment = SEGMENTS[index]
  text.value = text.value.slice(0, segment.start) + value.padStart(segment.length, '0') + text.value.slice(segment.end)
}
function stepSegment(index, delta) {
  const parts = text.value.split('-').map(Number)
  if (index === 0) parts[0] = Math.min(2100, Math.max(1970, parts[0] + delta))
  else if (index === 1) parts[1] = ((parts[1] - 1 + delta + 12) % 12) + 1
  else parts[2] = ((parts[2] - 1 + delta + 31) % 31) + 1
  text.value = normalizeDateInput(`${parts[0]}-${parts[1]}-${parts[2]}`, { edge: props.edge }) || text.value
  selectSegment(index)
}
function typeDigit(digit) {
  const segment = SEGMENTS[activeSegment]
  buffer = (buffer + digit).slice(-segment.length)
  replaceSegment(activeSegment, buffer)
  // Move on once the segment cannot take another digit (native-field feel).
  const done = buffer.length === segment.length || (activeSegment === 1 && Number(buffer) > 1) || (activeSegment === 2 && Number(buffer) > 3)
  if (!done) { const current = activeSegment; nextTick(() => input.value?.setSelectionRange(SEGMENTS[current].start, SEGMENTS[current].end)); return }
  text.value = normalizeDateInput(text.value, { edge: props.edge }) || text.value
  if (activeSegment < 2) selectSegment(activeSegment + 1)
  else { commit(false); selectSegment(2) }
}
function inSegmentMode() {
  const element = input.value
  const segment = SEGMENTS[activeSegment]
  return Boolean(element && segment && canonical.value && element.selectionStart === segment.start && element.selectionEnd === segment.end)
}
function onBeforeInput(event) {
  const type = event.inputType || ''
  if (type === 'insertText' || type === 'insertCompositionText') {
    const data = String(event.data ?? '')
    // The box takes digits only; separators are never typed.
    if (!/^\d+$/.test(data)) { event.preventDefault(); return }
    if (!inSegmentMode()) return
    event.preventDefault()
    for (const digit of data) { if (activeSegment >= 0) typeDigit(digit) }
    return
  }
  if (type === 'insertFromPaste' || type === 'insertFromDrop') {
    const data = String(event.data ?? event.dataTransfer?.getData('text') ?? '')
    if (!/^[\d\-/.年月日\s]*$/.test(data)) event.preventDefault()
    return
  }
  if (type.startsWith('delete') && canonical.value) {
    // Deleting never touches a separator: it steps to the neighbouring segment.
    event.preventDefault()
    if (activeSegment < 0) { selectSegment(2); return }
    buffer = ''
    selectSegment(type === 'deleteContentForward' ? Math.min(2, activeSegment + 1) : Math.max(0, activeSegment - 1))
  }
}
function onKeydown(event) {
  if (event.key === 'Enter') { event.preventDefault(); commit(true, true); input.value?.blur(); return }
  if (!canonical.value || activeSegment < 0) return
  if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); selectSegment(Math.min(2, Math.max(0, activeSegment + (event.key === 'ArrowRight' ? 1 : -1)))); return }
  if (event.key === 'ArrowUp' || event.key === 'ArrowDown') { event.preventDefault(); stepSegment(activeSegment, event.key === 'ArrowUp' ? 1 : -1); return }
  if (event.key === 'Tab') { if (activeSegment < 2 && !event.shiftKey) { event.preventDefault(); selectSegment(activeSegment + 1) } else if (activeSegment > 0 && event.shiftKey) { event.preventDefault(); selectSegment(activeSegment - 1) } }
}
function onInput() {
  // Free typing (paste, select-all, a cleared box) leaves segment mode.
  activeSegment = -1
  buffer = ''
}
function commit(leave = true, apply = props.applyOn !== 'enter') {
  const normalized = normalizeDateInput(text.value, { edge: props.edge })
  text.value = normalized
  if (leave) { editing.value = false; activeSegment = -1; buffer = '' }
  if (apply && normalized !== props.modelValue) emit('update:modelValue', normalized)
}
</script>

<style scoped>
.date-segment { position: relative; display: block; }
.date-segment input { width: 100%; }
.date-segment-hint { position: absolute; left: 0; top: 100%; margin-top: 4px; padding: 3px 8px; border-radius: 6px; background: #eaf2ff; color: #2563eb; font-size: 11px; white-space: nowrap; z-index: 3; }
.date-segment.is-invalid .date-segment-hint { background: #fff4da; color: #8a6924; }
.date-segment-hint.is-pending { background: #fff4da; color: #8a6924; }
</style>
