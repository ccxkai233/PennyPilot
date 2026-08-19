import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import './style.css'
import Login from './views/Login.vue'
import Register from './views/Register.vue'
import Dashboard from './views/Dashboard.vue'
import Transactions from './views/Transactions.vue'
import Settings from './views/Settings.vue'
import Partners from './views/Partners.vue'
import AiBookkeeping from './views/AiBookkeeping.vue'
import Reports from './views/Reports.vue'
import Settlements from './views/Settlements.vue'
import { authState, clearAuth, ensureAuthenticated } from './stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/dashboard' },
    { path: '/login', name: 'login', component: Login, meta: { public: true } },
    { path: '/register', name: 'register', component: Register, meta: { public: true } },
    { path: '/dashboard', name: 'dashboard', component: Dashboard, meta: { requiresAuth: true } },
    { path: '/transactions', name: 'transactions', component: Transactions, meta: { requiresAuth: true } },
    { path: '/settings', name: 'settings', component: Settings, meta: { requiresAuth: true } },
    { path: '/partners', name: 'partners', component: Partners, meta: { requiresAuth: true } },
    { path: '/ai', name: 'ai', component: AiBookkeeping, meta: { requiresAuth: true } },
    { path: '/settlements', name: 'settlements', component: Settlements, meta: { requiresAuth: true } },
    { path: '/reports', name: 'reports', component: Reports, meta: { requiresAuth: true } },
    { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
  ],
})

router.beforeEach(async (to) => {
  if (to.meta.public) {
    if (to.name === 'login' || to.name === 'register') {
      try {
        const user = authState.checked ? authState.user : await ensureAuthenticated()
        if (user) return { name: 'dashboard' }
      } catch {
        // Keep the public login screen available while the API is unreachable.
      }
    }
    return true
  }
  try {
    const user = await ensureAuthenticated()
    if (user) return true
  } catch {
    // The login screen provides a useful error state if the API is unavailable.
  }
  return { name: 'login', query: { redirect: to.fullPath } }
})

if (typeof window !== 'undefined') {
  window.addEventListener('pennypilot:unauthorized', () => {
    clearAuth()
    const currentName = router.currentRoute.value.name
    if (currentName && currentName !== 'login' && currentName !== 'register') {
      router.push({ name: 'login', query: { redirect: router.currentRoute.value.fullPath } })
    }
  })
}

createApp(App).use(router).mount('#app')
