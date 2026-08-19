<template>
  <main class="login-page">
    <section class="login-card" aria-labelledby="login-title">
      <div class="brand">
        <div class="brand-mark">₱</div>
        <div><h1>PennyPilot</h1><p>智能记账，掌控每一笔</p></div>
      </div>
      <h2 id="login-title">欢迎回来</h2>
      <p class="muted">登录您的账户以继续</p>
      <div v-if="errorMessage" class="form-error" role="alert">{{ errorMessage }}</div>
      <form @submit.prevent="submit">
        <label>用户名
          <input v-model.trim="form.username" autocomplete="username" required placeholder="输入用户名" :disabled="loading" />
        </label>
        <label>密码
          <input v-model="form.password" type="password" autocomplete="current-password" required placeholder="输入密码" :disabled="loading" />
        </label>
        <div class="row"><label class="remember"><input v-model="remember" type="checkbox" /> 保持登录</label><span class="hint">会话有效期 7 天</span></div>
        <button class="primary" type="submit" :disabled="loading">
          <span v-if="loading" class="spinner"></span>{{ loading ? '登录中…' : '登录' }}
        </button>
      </form>
      <p class="signup">还没有账户？ <router-link to="/register">立即注册</router-link></p>
    </section>
  </main>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError } from '../api'
import { signIn } from '../stores/auth'

const router = useRouter()
const route = useRoute()
const form = reactive({ username: '', password: '' })
const remember = ref(true)
const loading = ref(false)
const errorMessage = ref('')

async function submit() {
  errorMessage.value = ''
  loading.value = true
  try {
    await signIn(form)
    const target = typeof route.query.redirect === 'string' ? route.query.redirect : '/dashboard'
    router.replace(target)
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '登录失败，请稍后重试。'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page { min-height: 100vh; display: grid; place-items: center; padding: 24px; background: linear-gradient(135deg, #eef4ff, #f9fbff); }
.login-card { width: min(430px, 100%); background: #fff; padding: 40px; border-radius: 20px; box-shadow: 0 15px 50px #213b6818; }
.brand { display: flex; gap: 12px; align-items: center; margin-bottom: 35px; }
.brand-mark { width: 42px; height: 42px; border-radius: 12px; background: #3b82f6; color: #fff; display: grid; place-items: center; font-size: 24px; font-weight: 700; }
.brand h1 { font-size: 22px; margin: 0; }.brand p, .muted, .signup { color: #8290a6; font-size: 13px; margin: 3px 0; }
h2 { margin: 0; font-size: 28px; }.form-error { margin-top: 18px; padding: 10px 12px; color: #a83232; background: #fff0f0; border-radius: 8px; font-size: 13px; }
form { margin-top: 25px; }label { display: block; font-size: 13px; color: #59677d; margin: 16px 0; }
input:not([type=checkbox]) { display: block; width: 100%; margin-top: 7px; padding: 12px 14px; border: 1px solid #dbe2ee; border-radius: 9px; font-size: 14px; outline: none; transition: border-color .15s, box-shadow .15s; }
input:not([type=checkbox]):focus { border-color: #3b82f6; box-shadow: 0 0 0 3px #3b82f61c; }
input:disabled { background: #f7f9fc; cursor: wait; }.row { display: flex; justify-content: space-between; align-items: center; font-size: 12px; }.row label { margin: 0; }.remember { display: flex; align-items: center; gap: 5px; }.hint { color: #9aa7b9; }
.primary { width: 100%; padding: 13px; border: 0; border-radius: 9px; background: #2563eb; color: #fff; font-weight: 600; cursor: pointer; margin-top: 10px; display: flex; align-items: center; justify-content: center; gap: 8px; }.primary:hover { background: #1d4ed8; }.primary:disabled { opacity: .65; cursor: wait; }
.spinner { width: 15px; height: 15px; border: 2px solid #ffffff66; border-top-color: #fff; border-radius: 50%; animation: spin .7s linear infinite; }.signup { text-align: center; margin-top: 25px; }.signup a { color: #3b82f6; text-decoration: none; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 480px) { .login-card { padding: 30px 22px; } }
</style>
