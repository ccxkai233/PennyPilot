<template>
  <MobileAppLayout v-if="isMobile" :title="props.title" :subtitle="props.subtitle" :notice="props.notice">
    <template v-if="$slots.title" #title><slot name="title"></slot></template>
    <template v-if="$slots.subtitle" #subtitle><slot name="subtitle"></slot></template>
    <template v-if="$slots.actions" #actions><slot name="actions"></slot></template>
    <template #default><slot></slot></template>
  </MobileAppLayout>

  <div v-else class="app-shell">
    <aside class="sidebar">
      <div class="side-brand">
        <div class="brand-mark">₱</div>
        <b>PennyPilot</b>
      </div>
      <nav class="side-nav" aria-label="主导航">
        <router-link v-for="item in navItems" :key="item.to" :to="item.to">
          <span class="nav-icon" aria-hidden="true">{{ item.icon }}</span><span>{{ item.label }}</span>
        </router-link>
      </nav>
      <div class="side-foot">
        <router-link to="/settings" class="settings-link">⚙ 设置</router-link>
        <span>v0.2.0</span>
      </div>
    </aside>
    <main class="main">
      <header class="page-header">
        <div class="page-heading">
          <slot name="title"><h1>{{ props.title }}</h1></slot>
          <slot name="subtitle"><p>{{ props.subtitle }}</p></slot>
        </div>
        <div class="header-actions">
          <slot name="actions"></slot>
          <div v-if="authState.user" class="user-menu">
            <span class="avatar">{{ avatarLetter }}</span>
            <span class="user-name">{{ authState.user.username }}</span>
            <button class="logout-button" type="button" @click="logout">退出</button>
          </div>
        </div>
      </header>
      <div v-if="props.notice" class="global-notice" :class="`notice-${props.notice.type}`" role="status">{{ props.notice.message }}</div>
      <slot></slot>
    </main>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { signOut, authState } from '../stores/auth'
import MobileAppLayout from './MobileAppLayout.vue'
import { useViewport } from '../composables/useViewport'

const props = defineProps({
  title: { type: String, default: '概览' },
  subtitle: { type: String, default: '' },
  notice: { type: Object, default: null },
})

const router = useRouter()
const { isMobile } = useViewport()
const navItems = [
  { to: '/dashboard', label: '概览', icon: '⌂' },
  { to: '/ai', label: 'AI 记账', icon: '✦' },
  { to: '/transactions', label: '收支记录', icon: '↕' },
  { to: '/partners', label: '往来账户', icon: '♧' },
  { to: '/settlements', label: '日结', icon: '▣' },
  { to: '/reports', label: '财务分析', icon: '▥' },
  { to: '/feedback', label: '意见反馈', icon: '✉' },
]
const avatarLetter = computed(() => String(authState.user?.username || '我').slice(0, 1).toUpperCase())

async function logout() {
  await signOut()
  router.replace({ name: 'login' })
}
</script>

<style scoped>
.app-shell { display: flex; width: 100%; min-height: 100vh; min-height: 100dvh; background: #f5f7fb; overflow-x: clip; }
.sidebar { position: sticky; top: 0; align-self: flex-start; width: 235px; flex: 0 0 235px; height: 100vh; height: 100dvh; overflow-y: auto; background: #111b2d; color: #b7c4d9; padding: 24px 15px; display: flex; flex-direction: column; z-index: 20; }
.sidebar { padding: max(24px, env(safe-area-inset-top)) max(15px, env(safe-area-inset-right)) max(24px, env(safe-area-inset-bottom)) max(15px, env(safe-area-inset-left)); }
.side-brand { display: flex; align-items: center; gap: 10px; color: #fff; font-size: 18px; padding: 0 10px 35px; }
.brand-mark { width: 34px; height: 34px; border-radius: 9px; background: #3b82f6; color: #fff; display: grid; place-items: center; font-size: 19px; }
.side-nav { display: grid; gap: 4px; overflow-y: auto; overscroll-behavior: contain; scrollbar-width: thin; }
.side-nav a { display: flex; align-items: center; gap: 11px; padding: 12px 14px; border-radius: 8px; margin: 0; font-size: 14px; color: #b7c4d9; text-decoration: none; transition: background .15s, color .15s; }
.side-nav a.router-link-active, .side-nav a:hover { background: #263b61; color: #fff; }
.nav-icon { width: 18px; text-align: center; font-size: 17px; opacity: .9; }
.side-foot { margin-top: auto; display: flex; flex-direction: column; gap: 18px; font-size: 13px; padding: 14px; color: #9cabc2; }
.settings-link { color: inherit; text-decoration: none; }
.side-foot span { font-size: 11px; color: #667895; }
.main { flex: 1; min-width: 0; padding: 32px 40px; max-width: 1450px; margin: auto; width: 100%; overflow-x: clip; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 18px; min-height: 50px; }
.page-heading { min-width: 0; }
.page-heading h1 { margin: 0; color: #17202f; font-size: 28px; line-height: 1.2; overflow-wrap: anywhere; }
.page-heading p { color: #8794a8; margin: 6px 0 0; font-size: 13px; }
.header-actions { display: flex; align-items: center; justify-content: flex-end; gap: 12px; min-width: 0; max-width: 100%; flex-wrap: wrap; }
.user-menu { display: flex; align-items: center; gap: 9px; color: #52617a; font-size: 13px; }
.avatar { display: grid; place-items: center; width: 32px; height: 32px; border-radius: 50%; background: #dce9ff; color: #2563eb; font-size: 13px; font-weight: 700; }
.logout-button { border: 0; background: transparent; color: #7d8aa0; font-size: 12px; cursor: pointer; padding: 5px 0 5px 5px; }
.logout-button:hover { color: #2563eb; }
.global-notice { margin: 18px 0 -6px; padding: 10px 14px; border-radius: 8px; font-size: 13px; }
.notice-success { color: #116b47; background: #e9f8f1; }
.notice-error { color: #a83232; background: #fff0f0; }
</style>
