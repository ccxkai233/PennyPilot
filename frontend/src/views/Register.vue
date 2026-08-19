<template>
  <main class="login-page">
    <section class="login-card" aria-labelledby="register-title">
      <div class="brand"><div class="brand-mark">₱</div><div><h1>PennyPilot</h1><p>智能记账，掌控每一笔</p></div></div>
      <h2 id="register-title">创建账户</h2>
      <p class="muted">注册后即可开始记录收支</p>
      <div v-if="errorMessage" class="form-error" role="alert">{{ errorMessage }}</div>
      <form @submit.prevent="submit">
        <label>用户名
          <input v-model.trim="form.username" autocomplete="username" minlength="2" maxlength="100" required placeholder="例如：小明" :disabled="loading" />
        </label>
        <label>密码
          <input v-model="form.password" type="password" autocomplete="new-password" minlength="8" required placeholder="至少 8 位字符" :disabled="loading" />
        </label>
        <label>确认密码
          <input v-model="form.confirmPassword" type="password" autocomplete="new-password" minlength="8" required placeholder="再次输入密码" :disabled="loading" />
        </label>
        <button class="primary" type="submit" :disabled="loading"><span v-if="loading" class="spinner"></span>{{ loading ? '创建中…' : '创建账户' }}</button>
      </form>
      <p class="signup">已有账户？ <router-link to="/login">返回登录</router-link></p>
    </section>
  </main>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ApiError } from '../api'
import { signIn } from '../stores/auth'
import { authApi } from '../api'

const router = useRouter()
const form = reactive({ username: '', password: '', confirmPassword: '' })
const loading = ref(false)
const errorMessage = ref('')

async function submit() {
  errorMessage.value = ''
  if (form.password !== form.confirmPassword) { errorMessage.value = '两次输入的密码不一致。'; return }
  loading.value = true
  try {
    await authApi.register({ username: form.username, password: form.password })
    await signIn({ username: form.username, password: form.password })
    router.replace('/dashboard')
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '注册失败，请稍后重试。'
  } finally { loading.value = false }
}
</script>

<style scoped>
.login-page { min-height: 100vh; display: grid; place-items: center; padding: 24px; background: linear-gradient(135deg, #eef4ff, #f9fbff); }
.login-card { width: min(430px, 100%); background: #fff; padding: 40px; border-radius: 20px; box-shadow: 0 15px 50px #213b6818; }
.brand { display: flex; gap: 12px; align-items: center; margin-bottom: 30px; }.brand-mark { width: 42px; height: 42px; border-radius: 12px; background: #3b82f6; color: #fff; display: grid; place-items: center; font-size: 24px; font-weight: 700; }.brand h1 { font-size: 22px; margin: 0; }.brand p, .muted, .signup { color: #8290a6; font-size: 13px; margin: 3px 0; }h2 { margin: 0; font-size: 28px; }.form-error { margin-top: 18px; padding: 10px 12px; color: #a83232; background: #fff0f0; border-radius: 8px; font-size: 13px; }form { margin-top: 22px; }label { display: block; font-size: 13px; color: #59677d; margin: 16px 0; }input:not([type=checkbox]) { display: block; width: 100%; margin-top: 7px; padding: 12px 14px; border: 1px solid #dbe2ee; border-radius: 9px; font-size: 14px; outline: none; }input:focus { border-color: #3b82f6; }.primary { width: 100%; padding: 13px; border: 0; border-radius: 9px; background: #2563eb; color: #fff; font-weight: 600; cursor: pointer; margin-top: 10px; display: flex; justify-content: center; gap: 8px; }.primary:disabled { opacity: .65; cursor: wait; }.spinner { width: 15px; height: 15px; border: 2px solid #ffffff66; border-top-color: #fff; border-radius: 50%; animation: spin .7s linear infinite; }.signup { text-align: center; margin-top: 25px; }.signup a { color: #3b82f6; text-decoration: none; }@keyframes spin { to { transform: rotate(360deg); } }@media(max-width:480px){.login-card{padding:30px 22px;}}
</style>
