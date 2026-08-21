<template>
  <div class="mobile-app-shell">
    <header class="mobile-header">
      <div class="mobile-titlebar">
        <div class="mobile-brand-mark" aria-hidden="true">₱</div>
        <div class="mobile-heading">
          <slot name="title"><h1>{{ title }}</h1></slot>
          <slot name="subtitle"><p v-if="subtitle">{{ subtitle }}</p></slot>
        </div>
        <button
          ref="moreButton"
          class="mobile-more-trigger"
          type="button"
          aria-label="打开更多菜单"
          aria-controls="mobile-more-panel"
          :aria-expanded="moreOpen"
          @click="openMore"
        >
          <span aria-hidden="true">•••</span>
        </button>
      </div>
      <div v-if="$slots.actions" class="mobile-actions" aria-label="页面操作">
        <slot name="actions"></slot>
      </div>
    </header>

    <main class="mobile-main">
      <div v-if="notice" class="mobile-notice" :class="`notice-${notice.type}`" role="status">{{ notice.message }}</div>
      <slot></slot>
    </main>

    <nav class="mobile-tabbar" aria-label="主导航">
      <router-link v-for="item in primaryItems" :key="item.to" :to="item.to" class="mobile-tab" :aria-label="item.label">
        <span class="mobile-tab-icon" aria-hidden="true">{{ item.icon }}</span>
        <span>{{ item.label }}</span>
      </router-link>
    </nav>

    <Teleport to="body">
      <div v-if="moreOpen" class="mobile-more-layer">
        <button class="mobile-more-scrim" type="button" aria-label="关闭更多菜单" tabindex="-1" @click="closeMore"></button>
        <section id="mobile-more-panel" ref="morePanel" class="mobile-more-panel" role="dialog" aria-modal="true" aria-labelledby="mobile-more-title" tabindex="-1" @keydown.esc="closeMore">
          <div class="mobile-more-handle" aria-hidden="true"></div>
          <div class="mobile-more-head">
            <div>
              <h2 id="mobile-more-title">更多功能</h2>
              <p v-if="authState.user"><span class="mobile-user-avatar" aria-hidden="true">{{ avatarLetter }}</span>{{ authState.user.username }}</p>
            </div>
            <button class="mobile-more-close" type="button" aria-label="关闭更多菜单" @click="closeMore">×</button>
          </div>
          <nav class="mobile-more-grid" aria-label="更多功能导航">
            <router-link v-for="item in moreItems" :key="item.to" :to="item.query ? { path: item.to, query: item.query } : item.to" class="mobile-more-item" @click="closeMore">
              <span class="mobile-more-icon" aria-hidden="true">{{ item.icon }}</span>
              <span>{{ item.label }}</span>
            </router-link>
            <button class="mobile-more-item mobile-logout-item" type="button" @click="logout">
              <span class="mobile-more-icon" aria-hidden="true">↪</span>
              <span>退出登录</span>
            </button>
          </nav>
        </section>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { authState, signOut } from '../stores/auth'

defineProps({
  title: { type: String, default: '概览' },
  subtitle: { type: String, default: '' },
  notice: { type: Object, default: null },
})

const router = useRouter()
const moreOpen = ref(false)
const moreButton = ref(null)
const morePanel = ref(null)
let previousBodyOverflow = ''
let bodyWasLocked = false

const primaryItems = [
  { to: '/dashboard', label: '概览', icon: '⌂' },
  { to: '/ai', label: 'AI 记账', icon: '✦' },
  { to: '/partners', label: '往来', icon: '♧' },
  { to: '/settlements', label: '日结', icon: '▣' },
]
const moreItems = [
  { to: '/transactions', label: '手动流水', icon: '↕', query: { mode: 'manual', from: 'ai' } },
  { to: '/reports', label: '财务分析', icon: '▥' },
  { to: '/feedback', label: '意见反馈', icon: '✉' },
  { to: '/settings', label: '设置', icon: '⚙' },
]
const avatarLetter = computed(() => String(authState.user?.username || '我').slice(0, 1).toUpperCase())

function updateBodyLock() {
  if (typeof document === 'undefined') return
  if (moreOpen.value && !bodyWasLocked) {
    previousBodyOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    bodyWasLocked = true
  } else if (!moreOpen.value && bodyWasLocked) {
    document.body.style.overflow = previousBodyOverflow
    previousBodyOverflow = ''
    bodyWasLocked = false
  }
}

function openMore() {
  moreOpen.value = true
  nextTick(() => morePanel.value?.focus())
}

function closeMore() {
  if (!moreOpen.value) return
  moreOpen.value = false
  nextTick(() => moreButton.value?.focus())
}

async function logout() {
  closeMore()
  await signOut()
  router.replace({ name: 'login' })
}

function handleKeydown(event) {
  if (event.key === 'Escape') closeMore()
}

watch(moreOpen, updateBodyLock)
watch(() => router.currentRoute.value.fullPath, closeMore)

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown)
  if (bodyWasLocked && typeof document !== 'undefined') document.body.style.overflow = previousBodyOverflow
  bodyWasLocked = false
  previousBodyOverflow = ''
})
</script>

<style scoped>
.mobile-app-shell {
  --mobile-blue: #2563eb;
  --mobile-ink: #17202f;
  --mobile-muted: #8794a8;
  display: flex;
  flex-direction: column;
  width: 100%;
  min-width: 0;
  min-height: 100vh;
  min-height: 100svh;
  min-height: 100dvh;
  overflow-x: clip;
  background: #f5f7fb;
  color: var(--mobile-ink);
}
.mobile-header {
  position: sticky;
  top: 0;
  z-index: 30;
  width: 100%;
  background: rgba(245, 247, 251, .94);
  background: #f5f7fbeF;
  border-bottom: 1px solid #e8edf5;
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  padding-top: 8px;
  padding-top: max(8px, env(safe-area-inset-top, 0px));
}
.mobile-titlebar {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 60px;
  padding: 8px 16px;
  padding: 8px max(16px, env(safe-area-inset-right, 0px)) 8px max(16px, env(safe-area-inset-left, 0px));
}
.mobile-brand-mark {
  display: grid;
  place-items: center;
  flex: 0 0 34px;
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: #3b82f6;
  color: #fff;
  font-size: 18px;
  font-weight: 700;
}
.mobile-heading {
  min-width: 0;
  flex: 1;
}
.mobile-heading h1 {
  overflow-wrap: anywhere;
  margin: 0;
  color: var(--mobile-ink);
  font-size: 20px;
  line-height: 1.25;
}
.mobile-heading p {
  overflow: hidden;
  margin: 3px 0 0;
  color: var(--mobile-muted);
  font-size: 11px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mobile-more-trigger,
.mobile-more-close {
  display: grid;
  place-items: center;
  flex: 0 0 44px;
  width: 44px;
  height: 44px;
  border: 0;
  border-radius: 11px;
  background: transparent;
  color: #52617a;
  cursor: pointer;
  touch-action: manipulation;
}
.mobile-more-trigger { font-size: 17px; letter-spacing: 2px; line-height: 1; }
.mobile-more-trigger:hover,
.mobile-more-trigger:focus-visible,
.mobile-more-close:hover,
.mobile-more-close:focus-visible { background: #e8f1ff; color: var(--mobile-blue); }
.mobile-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
  padding: 0 16px 10px;
  padding: 0 max(16px, env(safe-area-inset-right, 0px)) 10px max(16px, env(safe-area-inset-left, 0px));
}
.mobile-actions :deep(a),
.mobile-actions :deep(button) {
  min-height: 44px;
  max-width: 100%;
}
.mobile-main {
  flex: 1 1 auto;
  width: 100%;
  min-width: 0;
  overflow-x: clip;
  padding: 16px 16px 100px;
  padding: 16px max(16px, env(safe-area-inset-right, 0px)) calc(100px + env(safe-area-inset-bottom, 0px)) max(16px, env(safe-area-inset-left, 0px));
}
.mobile-notice {
  margin: 0 0 14px;
  padding: 10px 12px;
  border-radius: 9px;
  font-size: 12px;
  line-height: 1.5;
}
.mobile-notice.notice-success { color: #116b47; background: #e9f8f1; }
.mobile-notice.notice-error { color: #a83232; background: #fff0f0; }
.mobile-tabbar {
  position: fixed;
  right: 0;
  bottom: 0;
  left: 0;
  z-index: 40;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  min-height: 64px;
  padding: 6px 8px;
  padding: 6px max(8px, env(safe-area-inset-right, 0px)) max(6px, env(safe-area-inset-bottom, 0px)) max(8px, env(safe-area-inset-left, 0px));
  border-top: 1px solid #e2e8f1;
  background: rgba(255, 255, 255, .95);
  background: #fffffff2;
  box-shadow: 0 -5px 24px #1a2b4512;
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
}
.mobile-tab {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  min-width: 0;
  min-height: 52px;
  gap: 3px;
  border-radius: 10px;
  color: #8a97aa;
  font-size: 10px;
  line-height: 1.15;
  text-decoration: none;
  transition: color .15s, background .15s;
}
.mobile-tab-icon { font-size: 19px; line-height: 1; }
.mobile-tab.router-link-active { color: var(--mobile-blue); background: #edf4ff; font-weight: 600; }
.mobile-tab:active { background: #e5efff; }
.mobile-more-layer {
  position: fixed;
  inset: 0;
  z-index: 60;
  pointer-events: none;
}
.mobile-more-scrim {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  border: 0;
  background: #0c172a66;
  pointer-events: auto;
}
.mobile-more-panel {
  position: absolute;
  right: 10px;
  bottom: 76px;
  left: 10px;
  right: max(10px, env(safe-area-inset-right, 0px));
  bottom: calc(76px + env(safe-area-inset-bottom, 0px));
  left: max(10px, env(safe-area-inset-left, 0px));
  max-height: min(70vh, 430px);
  overflow: auto;
  padding: 9px 16px 18px;
  padding: 9px max(16px, env(safe-area-inset-right, 0px)) 18px max(16px, env(safe-area-inset-left, 0px));
  border: 1px solid #e3eaf4;
  border-radius: 18px;
  background: #fff;
  box-shadow: 0 20px 70px #10213c40;
  pointer-events: auto;
}
.mobile-more-handle {
  width: 38px;
  height: 4px;
  margin: 0 auto 8px;
  border-radius: 99px;
  background: #dbe3ef;
}
.mobile-more-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid #edf0f5;
}
.mobile-more-head h2 { margin: 0; color: #34435b; font-size: 17px; }
.mobile-more-head p { display: flex; align-items: center; gap: 5px; overflow: hidden; margin: 4px 0 0; color: #98a4b4; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.mobile-user-avatar { display: inline-grid; place-items: center; flex: 0 0 20px; width: 20px; height: 20px; border-radius: 50%; background: #dce9ff; color: var(--mobile-blue); font-size: 10px; font-weight: 700; }
.mobile-more-close { margin: -5px -5px 0 0; color: #8794a8; font-size: 26px; line-height: 1; }
.mobile-more-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; padding-top: 13px; }
.mobile-more-item {
  display: flex;
  align-items: center;
  min-width: 0;
  min-height: 56px;
  gap: 9px;
  padding: 9px 11px;
  border: 1px solid #e7edf5;
  border-radius: 11px;
  background: #fff;
  color: #52617a;
  font-size: 12px;
  text-decoration: none;
  cursor: pointer;
  touch-action: manipulation;
}
.mobile-more-item:hover,
.mobile-more-item:focus-visible,
.mobile-more-item.router-link-active { border-color: #b9d2f8; background: #f4f8ff; color: var(--mobile-blue); }
.mobile-more-icon {
  display: grid;
  place-items: center;
  flex: 0 0 31px;
  width: 31px;
  height: 31px;
  border-radius: 9px;
  background: #edf4ff;
  color: var(--mobile-blue);
  font-size: 16px;
}
.mobile-logout-item { border-color: #f2dede; color: #b74e56; }
.mobile-logout-item .mobile-more-icon { background: #fff0f0; color: #c95b62; }
@media (prefers-reduced-motion: reduce) {
  .mobile-tab { transition: none; }
}
</style>
