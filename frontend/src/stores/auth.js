import { reactive } from 'vue'
import { authApi, ApiError } from '../api'

export const authState = reactive({
  user: null,
  checked: false,
  loading: false,
})

export async function ensureAuthenticated() {
  if (authState.checked) return authState.user
  authState.loading = true
  try {
    authState.user = await authApi.me()
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401) throw error
    authState.user = null
  } finally {
    authState.checked = true
    authState.loading = false
  }
  return authState.user
}

export async function signIn(credentials) {
  authState.loading = true
  try {
    const result = await authApi.login(credentials)
    authState.user = result?.user || await authApi.me()
    authState.checked = true
    return authState.user
  } finally {
    authState.loading = false
  }
}

export async function signOut() {
  try { await authApi.logout() } finally {
    authState.user = null
    authState.checked = true
  }
}

export function clearAuth() {
  authState.user = null
  authState.checked = true
}

