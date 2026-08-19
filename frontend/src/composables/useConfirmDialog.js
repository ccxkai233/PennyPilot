import { reactive } from 'vue'

export function useConfirmDialog() {
  const confirmDialog = reactive({ open: false, eyebrow: '请确认操作', title: '', message: '', confirmLabel: '确认', tone: 'danger' })
  let resolver = null

  function requestConfirm(options = {}) {
    if (resolver) resolver(false)
    Object.assign(confirmDialog, {
      open: true,
      eyebrow: options.eyebrow || '请确认操作',
      title: options.title || '确认执行此操作？',
      message: options.message || '请确认是否继续。',
      confirmLabel: options.confirmLabel || '确认',
      tone: options.tone || 'danger',
    })
    return new Promise((resolve) => { resolver = resolve })
  }

  function resolveConfirm(result) {
    if (!confirmDialog.open) return
    confirmDialog.open = false
    const resolve = resolver
    resolver = null
    resolve?.(Boolean(result))
  }

  return { confirmDialog, requestConfirm, resolveConfirm }
}
