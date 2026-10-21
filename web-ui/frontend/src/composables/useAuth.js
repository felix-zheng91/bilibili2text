import { readonly, ref } from 'vue'
import { authApi } from '../api'

const authRequired = ref(false)
const authenticated = ref(false)
const username = ref('')
const expiresAt = ref('')
const sessionChecked = ref(false)
const sessionError = ref('')

let inflight = null

const applySession = (data) => {
  authRequired.value = Boolean(data?.auth_required)
  authenticated.value = authRequired.value ? Boolean(data?.authenticated) : true
  username.value =
    typeof data?.username === 'string' ? data.username.trim() : ''
  expiresAt.value = typeof data?.expires_at === 'string' ? data.expires_at : ''
  sessionChecked.value = true
  sessionError.value = ''
}

const markUnauthenticated = () => {
  authenticated.value = false
  username.value = ''
  expiresAt.value = ''
}

/**
 * Load the session once. Concurrent callers share the same request, and a
 * failed request fails closed: the SPA stays on the login screen instead of
 * exposing the application shell with an unknown auth state.
 */
const checkSession = async ({ force = false } = {}) => {
  if (sessionChecked.value && !force) return authenticated.value
  if (inflight) return inflight

  inflight = (async () => {
    try {
      const data = await authApi.getSession()
      applySession(data)
      return authenticated.value
    } catch (error) {
      sessionChecked.value = true
      authRequired.value = true
      markUnauthenticated()
      sessionError.value =
        error instanceof Error ? error.message : '无法获取登录状态'
      return false
    } finally {
      inflight = null
    }
  })()

  return inflight
}

const login = async (name, password) => {
  sessionError.value = ''
  const data = await authApi.login(name, password)
  applySession(data)
  return authenticated.value
}

const logout = async () => {
  try {
    await authApi.logout()
  } catch {
    // The local session must be cleared even when the request fails (for
    // example when the session already expired or the network is offline).
  }
  markUnauthenticated()
}

export function useAuth() {
  return {
    authRequired: readonly(authRequired),
    authenticated: readonly(authenticated),
    username: readonly(username),
    expiresAt: readonly(expiresAt),
    sessionChecked: readonly(sessionChecked),
    sessionError: readonly(sessionError),
    checkSession,
    login,
    logout,
    markUnauthenticated
  }
}
