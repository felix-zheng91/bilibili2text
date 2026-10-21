import { createRouter, createWebHashHistory } from 'vue-router'
import ProcessView from './components/ProcessView.vue'
import HistoryView from './components/HistoryView.vue'
import RagView from './components/RagView.vue'
import PublicApiKeyView from './components/PublicApiKeyView.vue'
import LoginView from './components/LoginView.vue'
import { useAuth } from './composables/useAuth'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/process' },
    {
      path: '/login',
      name: 'login',
      component: LoginView,
      meta: { public: true }
    },
    { path: '/process', component: ProcessView },
    { path: '/process/:jobId', component: ProcessView },
    { path: '/history', component: HistoryView },
    { path: '/history/:runId', component: HistoryView },
    { path: '/rag', component: RagView },
    { path: '/settings', component: PublicApiKeyView }
  ]
})

router.beforeEach(async (to) => {
  const { authRequired, authenticated, checkSession } = useAuth()
  await checkSession()

  if (to.meta.public) {
    if (to.name === 'login' && authenticated.value) {
      return { path: '/process' }
    }
    return true
  }

  if (authRequired.value && !authenticated.value) {
    return {
      name: 'login',
      query: to.fullPath === '/' ? {} : { redirect: to.fullPath }
    }
  }
  return true
})

export default router
