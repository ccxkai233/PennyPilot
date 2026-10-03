<template>
  <Teleport to="body">
    <div v-if="open" class="report-preview-backdrop" :class="{ 'is-mobile': mobile }" @click.self="emit('close')">
      <section class="report-preview" role="dialog" aria-modal="true" aria-labelledby="report-preview-title">
        <header class="report-preview-head">
          <div><h2 id="report-preview-title">报告预览</h2><p>{{ report?.periodLabel || '收支报告' }}</p></div>
          <div class="report-preview-actions">
            <button class="report-preview-save" type="button" :disabled="saving || loading || !report" @click="saveImage"><span v-if="saving" class="report-preview-spinner"></span>{{ saving ? '正在生成…' : '保存为图片' }}</button>
            <button class="report-preview-close" type="button" aria-label="关闭预览" @click="emit('close')">×</button>
          </div>
        </header>
        <p v-if="error" class="report-preview-error" role="alert">{{ error }}</p>
        <div class="report-preview-body">
          <div v-if="loading" class="report-preview-state"><span class="report-preview-spinner dark"></span>正在读取报告…</div>
          <div v-else-if="report" ref="cardWrap" class="report-preview-card"><ReportCard :report="report" :compact="mobile" /></div>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue'
import { toPng } from 'html-to-image'
import ReportCard from './ReportCard.vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  report: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  mobile: { type: Boolean, default: false },
})
const emit = defineEmits(['close'])
const cardWrap = ref(null)
const saving = ref(false)
const error = ref('')

watch(() => props.open, (open) => {
  error.value = ''
  document.body.style.overflow = open ? 'hidden' : ''
})

function fileName() {
  const label = String(props.report?.periodLabel || '收支报告').replace(/[\\/:*?"<>|\s]+/g, '').replace(/至/g, '至')
  return `收支报告-${label || '未命名'}.png`
}

async function saveImage() {
  const node = cardWrap.value?.firstElementChild
  if (!node || saving.value) return
  saving.value = true; error.value = ''
  try {
    await nextTick()
    const dataUrl = await toPng(node, {
      pixelRatio: props.mobile ? 3 : 2,
      cacheBust: true,
      backgroundColor: '#ffffff',
      style: { boxShadow: 'none', margin: '0' },
    })
    const link = document.createElement('a')
    link.href = dataUrl
    link.download = fileName()
    link.rel = 'noopener'
    document.body.appendChild(link)
    link.click()
    link.remove()
  } catch (cause) {
    error.value = '生成图片失败，请稍后重试。'
    console.error(cause)
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.report-preview-backdrop{position:fixed;inset:0;z-index:120;display:grid;place-items:center;padding:24px;background:#0f1a2ccc;backdrop-filter:blur(3px)}
.report-preview{display:flex;flex-direction:column;width:min(720px,100%);max-height:100%;border-radius:18px;background:#f5f7fb;box-shadow:0 24px 64px #0a16304d;overflow:hidden}
.report-preview-head{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:14px 18px;border-bottom:1px solid #e3e9f2;background:#fff}
.report-preview-head h2{margin:0;color:#34435b;font-size:15px}
.report-preview-head p{margin:3px 0 0;color:#8a97aa;font-size:12px}
.report-preview-actions{display:flex;align-items:center;gap:8px;flex:0 0 auto}
.report-preview-save{display:inline-flex;align-items:center;gap:6px;min-height:38px;border:0;border-radius:9px;padding:0 15px;background:#2563eb;color:#fff;font:inherit;font-size:13px;font-weight:600;cursor:pointer}
.report-preview-save:disabled{opacity:.55;cursor:wait}
.report-preview-close{display:grid;place-items:center;width:38px;height:38px;border:1px solid #dbe2ee;border-radius:9px;background:#fff;color:#64748b;font-size:22px;line-height:1;cursor:pointer}
.report-preview-error{margin:0;padding:8px 18px;background:#fff3f3;color:#a83232;font-size:12px}
.report-preview-body{flex:1;min-height:0;overflow:auto;padding:20px}
.report-preview-card{display:flex;justify-content:center}
.report-preview-card :deep(.report-card){box-shadow:0 10px 32px #23436d22}
.report-preview-state{display:flex;align-items:center;justify-content:center;gap:8px;min-height:160px;color:#7c8ba1;font-size:13px}
.report-preview-spinner{width:14px;height:14px;border:2px solid #ffffff66;border-top-color:#fff;border-radius:50%;animation:report-preview-spin .7s linear infinite}
.report-preview-spinner.dark{border-color:#dce7f8;border-top-color:#2563eb}
@keyframes report-preview-spin{to{transform:rotate(360deg)}}
.report-preview-backdrop.is-mobile{padding:0;place-items:stretch}
.report-preview-backdrop.is-mobile .report-preview{width:100%;max-height:none;height:100%;border-radius:0}
.report-preview-backdrop.is-mobile .report-preview-head{padding:calc(10px + env(safe-area-inset-top,0px)) 14px 10px}
.report-preview-backdrop.is-mobile .report-preview-save{min-height:40px;padding:0 13px}
.report-preview-backdrop.is-mobile .report-preview-close{width:40px;height:40px}
.report-preview-backdrop.is-mobile .report-preview-body{padding:12px 12px calc(20px + env(safe-area-inset-bottom,0px))}
</style>
