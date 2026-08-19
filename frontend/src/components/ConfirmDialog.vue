<template>
  <Teleport to="body">
    <Transition name="confirm-dialog-fade">
      <div v-if="open" ref="backdrop" class="confirm-dialog-backdrop" tabindex="-1" @click.self="$emit('cancel')" @keydown.esc.prevent="$emit('cancel')">
        <section class="confirm-dialog" role="alertdialog" aria-modal="true" :aria-labelledby="titleId" :aria-describedby="messageId">
          <div class="confirm-dialog-handle" aria-hidden="true"></div>
          <div class="confirm-dialog-body">
            <span class="confirm-dialog-icon" :class="`is-${tone}`" aria-hidden="true">{{ tone === 'danger' ? '!' : '?' }}</span>
            <div class="confirm-dialog-copy">
              <p>{{ eyebrow }}</p>
              <h2 :id="titleId">{{ title }}</h2>
              <span :id="messageId">{{ message }}</span>
            </div>
          </div>
          <div class="confirm-dialog-actions">
            <button type="button" class="confirm-dialog-secondary" @click="$emit('cancel')">取消</button>
            <button ref="confirmButton" type="button" class="confirm-dialog-primary" :class="`is-${tone}`" @click="$emit('confirm')">{{ confirmLabel }}</button>
          </div>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  eyebrow: { type: String, default: '请确认操作' },
  title: { type: String, required: true },
  message: { type: String, required: true },
  confirmLabel: { type: String, default: '确认' },
  tone: { type: String, default: 'danger' },
})

defineEmits(['cancel', 'confirm'])

const backdrop = ref(null)
const confirmButton = ref(null)
const uid = Math.random().toString(36).slice(2, 9)
const titleId = `confirm-dialog-title-${uid}`
const messageId = `confirm-dialog-message-${uid}`

watch(() => props.open, (open) => {
  if (!open) return
  nextTick(() => (confirmButton.value || backdrop.value)?.focus())
})
</script>

<style scoped>
.confirm-dialog-backdrop{position:fixed;inset:0;z-index:300;display:grid;place-items:center;padding:18px;background:rgba(16,33,60,.46);backdrop-filter:blur(2px);outline:0}.confirm-dialog{width:min(430px,100%);overflow:hidden;border:1px solid rgba(220,229,241,.9);border-radius:16px;background:#fff;box-shadow:0 26px 80px rgba(12,28,53,.3)}.confirm-dialog-handle{display:none}.confirm-dialog-body{display:grid;grid-template-columns:42px minmax(0,1fr);gap:13px;padding:24px 24px 20px}.confirm-dialog-icon{display:grid;place-items:center;width:42px;height:42px;border-radius:13px;background:#edf4ff;color:#2563eb;font-size:18px;font-weight:800}.confirm-dialog-icon.is-danger{background:#fff0f0;color:#cf525a}.confirm-dialog-copy{min-width:0}.confirm-dialog-copy p{margin:0 0 4px;color:#8795a9;font-size:11px;letter-spacing:.04em}.confirm-dialog-copy h2{margin:0;color:#293950;font-size:18px;line-height:1.4;overflow-wrap:anywhere}.confirm-dialog-copy>span{display:block;margin-top:7px;color:#748298;font-size:13px;line-height:1.65;overflow-wrap:anywhere}.confirm-dialog-actions{display:flex;justify-content:flex-end;gap:9px;padding:15px 24px 18px;border-top:1px solid #edf1f6;background:#fbfcfe}.confirm-dialog-actions button{display:inline-flex;align-items:center;justify-content:center;min-width:92px;min-height:42px;border-radius:9px;padding:9px 15px;font:inherit;font-size:13px;font-weight:600;cursor:pointer}.confirm-dialog-secondary{border:1px solid #d7e1ee;background:#fff;color:#56677f}.confirm-dialog-primary{border:0;background:#2563eb;color:#fff}.confirm-dialog-primary.is-danger{background:#d85a62}.confirm-dialog-secondary:hover,.confirm-dialog-secondary:focus-visible{border-color:#8bb3ed;color:#2563eb;outline:0}.confirm-dialog-primary:hover,.confirm-dialog-primary:focus-visible{filter:brightness(.94);outline:3px solid rgba(37,99,235,.15)}.confirm-dialog-primary.is-danger:focus-visible{outline-color:rgba(216,90,98,.18)}
.confirm-dialog-fade-enter-active,.confirm-dialog-fade-leave-active{transition:opacity .16s ease}.confirm-dialog-fade-enter-active .confirm-dialog,.confirm-dialog-fade-leave-active .confirm-dialog{transition:transform .18s ease,opacity .16s ease}.confirm-dialog-fade-enter-from,.confirm-dialog-fade-leave-to{opacity:0}.confirm-dialog-fade-enter-from .confirm-dialog,.confirm-dialog-fade-leave-to .confirm-dialog{transform:translateY(7px) scale(.985);opacity:0}
@media(max-width:640px){.confirm-dialog-backdrop{place-items:end center;padding:8px 8px max(8px,env(safe-area-inset-bottom))}.confirm-dialog{width:100%;border-radius:17px 17px 10px 10px}.confirm-dialog-handle{display:block;width:38px;height:4px;margin:8px auto 0;border-radius:99px;background:#d7e0ec}.confirm-dialog-body{grid-template-columns:38px minmax(0,1fr);gap:11px;padding:17px 16px 16px}.confirm-dialog-icon{width:38px;height:38px;border-radius:11px}.confirm-dialog-copy h2{font-size:17px}.confirm-dialog-copy>span{font-size:12px}.confirm-dialog-actions{display:grid;grid-template-columns:1fr 1fr;gap:8px;padding:13px 16px calc(14px + env(safe-area-inset-bottom))}.confirm-dialog-actions button{min-width:0;min-height:46px;font-size:14px}}
@media(prefers-reduced-motion:reduce){.confirm-dialog-fade-enter-active,.confirm-dialog-fade-leave-active,.confirm-dialog-fade-enter-active .confirm-dialog,.confirm-dialog-fade-leave-active .confirm-dialog{transition:none}}
</style>
