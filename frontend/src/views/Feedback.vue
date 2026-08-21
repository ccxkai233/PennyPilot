<template>
  <AppLayout title="意见反馈" subtitle="使用中遇到问题或有建议，随时在这里告诉我们" :notice="notice">
    <section class="feedback-form panel">
      <div class="panel-title"><div><h2>提交反馈</h2><p>我们会尽快查看，感谢你的反馈</p></div></div>
      <form @submit.prevent="submit">
        <div class="category-picker" role="radiogroup" aria-label="反馈类型">
          <button
            v-for="option in categoryOptions"
            :key="option.value"
            type="button"
            role="radio"
            :aria-checked="form.category === option.value"
            :class="{ selected: form.category === option.value }"
            @click="form.category = option.value"
          >
            <span aria-hidden="true">{{ option.icon }}</span>{{ option.label }}
          </button>
        </div>
        <label>反馈内容
          <textarea
            v-model.trim="form.content"
            rows="5"
            maxlength="2000"
            required
            placeholder="请描述你遇到的问题或建议，越具体越容易帮你解决…"
          ></textarea>
        </label>
        <label>联系方式（可选）
          <input v-model.trim="form.contact" type="text" maxlength="200" placeholder="微信 / 邮箱 / 手机号，方便我们跟进" />
        </label>
        <div v-if="formError" class="form-error" role="alert">{{ formError }}</div>
        <div class="form-actions">
          <button class="primary" type="submit" :disabled="submitting || !form.content">
            <span v-if="submitting" class="spinner"></span>{{ submitting ? '提交中…' : '提交反馈' }}
          </button>
        </div>
      </form>
    </section>

    <section class="feedback-history panel">
      <div class="panel-title"><div><h2>我的反馈记录</h2><p>最近提交的反馈</p></div><button class="text-button" type="button" @click="loadHistory">刷新</button></div>
      <div v-if="historyLoading" class="state"><span class="spinner dark"></span><p>正在加载…</p></div>
      <div v-else-if="historyError" class="state error-state"><p>{{ historyError }}</p><button class="outline-button" type="button" @click="loadHistory">重试</button></div>
      <div v-else-if="!history.length" class="state"><div class="empty-icon">✉</div><h3>还没有反馈记录</h3><p>有想法或遇到问题，随时在上方提交。</p></div>
      <ul v-else class="history-list">
        <li v-for="item in history" :key="item.id">
          <div class="history-icon">{{ categoryIcon(item.category) }}</div>
          <div class="history-content">
            <strong>{{ categoryLabel(item.category) }}</strong>
            <span>{{ formatDateTime(item.created_at) }}</span>
            <p>{{ item.content }}</p>
          </div>
        </li>
      </ul>
    </section>
  </AppLayout>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import AppLayout from '../components/AppLayout.vue'
import { ApiError, feedbackApi, formatDateTime } from '../api'

const categoryOptions = [
  { value: 'bug', label: '问题反馈', icon: '⚠' },
  { value: 'suggestion', label: '功能建议', icon: '✦' },
  { value: 'other', label: '其他', icon: '…' },
]

const form = reactive({ category: 'bug', content: '', contact: '' })
const formError = ref('')
const submitting = ref(false)
const notice = ref(null)
const history = ref([])
const historyLoading = ref(false)
const historyError = ref('')

function categoryLabel(value) {
  return categoryOptions.find((option) => option.value === value)?.label || '其他'
}
function categoryIcon(value) {
  return categoryOptions.find((option) => option.value === value)?.icon || '…'
}

async function loadHistory() {
  historyLoading.value = true
  historyError.value = ''
  try {
    history.value = await feedbackApi.list()
  } catch (error) {
    historyError.value = error instanceof ApiError ? error.message : '反馈记录加载失败。'
  } finally {
    historyLoading.value = false
  }
}

async function submit() {
  if (!form.content) return
  formError.value = ''
  submitting.value = true
  try {
    const created = await feedbackApi.create({
      category: form.category,
      content: form.content,
      contact: form.contact || null,
    })
    history.value = [created, ...history.value]
    form.content = ''
    form.contact = ''
    notice.value = { type: 'success', message: '反馈已提交，感谢你的帮助！' }
  } catch (error) {
    formError.value = error instanceof ApiError ? error.message : '提交失败，请稍后重试。'
  } finally {
    submitting.value = false
  }
}

onMounted(loadHistory)
</script>

<style scoped>
.panel { background: #fff; border-radius: 13px; box-shadow: 0 2px 8px #243b5a0d; padding: 22px; margin-top: 20px; }
.panel-title { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 16px; }
.panel-title h2 { margin: 0; color: #17202f; font-size: 17px; }
.panel-title p { margin: 4px 0 0; color: #8794a8; font-size: 12px; }
form { display: grid; gap: 14px; }
label { display: grid; gap: 6px; font-size: 13px; color: #52617a; }
textarea, input[type="text"] { border: 1px solid #dde4ee; border-radius: 8px; padding: 10px 12px; font-size: 14px; color: #17202f; resize: vertical; }
textarea:focus, input:focus { outline: none; border-color: #93b8f5; }
.category-picker { display: flex; flex-wrap: wrap; gap: 8px; }
.category-picker button { display: flex; align-items: center; gap: 6px; border: 1px solid #dde4ee; border-radius: 999px; background: #fff; color: #52617a; padding: 8px 16px; font-size: 13px; cursor: pointer; }
.category-picker button.selected { border-color: #2563eb; background: #edf4ff; color: #2563eb; font-weight: 600; }
.form-error { color: #a83232; background: #fff0f0; padding: 8px 12px; border-radius: 8px; font-size: 13px; }
.form-actions { display: flex; justify-content: flex-end; }
.primary { display: inline-flex; align-items: center; gap: 8px; border: 0; border-radius: 8px; background: #2563eb; color: #fff; padding: 10px 22px; font-size: 13px; font-weight: 600; cursor: pointer; }
.primary:disabled { opacity: .6; cursor: not-allowed; }
.text-button { border: 0; background: transparent; color: #2563eb; font-size: 12px; cursor: pointer; }
.outline-button { border: 1px solid #dde4ee; background: #fff; border-radius: 8px; padding: 8px 16px; font-size: 13px; color: #52617a; cursor: pointer; }
.spinner { width: 14px; height: 14px; border: 2px solid #ffffff66; border-top-color: #fff; border-radius: 50%; display: inline-block; animation: spin .7s linear infinite; }
.spinner.dark { width: 20px; height: 20px; border: 2px solid #dde4ee; border-top-color: #2563eb; }
@keyframes spin { to { transform: rotate(360deg); } }
.state { display: grid; justify-items: center; text-align: center; gap: 8px; padding: 32px 12px; color: #8794a8; }
.state.error-state p { color: #a83232; }
.state h3 { margin: 0; color: #33425b; font-size: 15px; }
.state p { margin: 0; font-size: 13px; }
.empty-icon { width: 46px; height: 46px; display: grid; place-items: center; border-radius: 14px; background: #edf4ff; color: #2563eb; font-size: 21px; }
.history-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; }
.history-list li { display: flex; gap: 12px; padding: 12px; border: 1px solid #edf0f5; border-radius: 10px; }
.history-icon { flex: 0 0 34px; width: 34px; height: 34px; display: grid; place-items: center; border-radius: 10px; background: #edf4ff; color: #2563eb; font-size: 15px; }
.history-content { min-width: 0; display: grid; gap: 2px; }
.history-content strong { color: #17202f; font-size: 13px; }
.history-content span { color: #8794a8; font-size: 11px; }
.history-content p { margin: 4px 0 0; color: #52617a; font-size: 13px; white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
