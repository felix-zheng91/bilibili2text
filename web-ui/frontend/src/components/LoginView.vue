<script setup>
  import { computed, onMounted, ref } from 'vue'
  import { useRoute, useRouter } from 'vue-router'
  import {
    AudioLines,
    Eye,
    EyeOff,
    Loader2,
    LockKeyhole,
    ShieldAlert,
    UserRound
  } from 'lucide-vue-next'
  import { useAuth } from '../composables/useAuth'

  const route = useRoute()
  const router = useRouter()
  const { authenticated, checkSession, login, sessionChecked, sessionError } =
    useAuth()

  const username = ref('')
  const password = ref('')
  const showPassword = ref(false)
  const submitting = ref(false)
  const checking = ref(false)
  const errorMessage = ref('')

  const redirectTarget = computed(() => {
    const raw =
      typeof route.query.redirect === 'string'
        ? route.query.redirect.trim()
        : ''
    return raw.startsWith('/') && !raw.startsWith('//') ? raw : '/process'
  })

  const canSubmit = computed(
    () => Boolean(username.value.trim() && password.value) && !submitting.value
  )

  const goToApp = async () => {
    await router.replace(redirectTarget.value)
  }

  const retrySession = async () => {
    checking.value = true
    errorMessage.value = ''
    await checkSession({ force: true })
    checking.value = false
    if (authenticated.value) await goToApp()
  }

  const handleSubmit = async () => {
    if (!canSubmit.value) return
    errorMessage.value = ''
    submitting.value = true
    try {
      const ok = await login(username.value.trim(), password.value)
      if (!ok) throw new Error('登录失败')
      await goToApp()
    } catch (error) {
      errorMessage.value =
        error instanceof Error ? error.message : '登录失败，请稍后重试'
      password.value = ''
    } finally {
      submitting.value = false
    }
  }

  onMounted(async () => {
    if (sessionChecked.value) return
    checking.value = true
    await checkSession({ force: true })
    checking.value = false
    if (authenticated.value) await goToApp()
  })
</script>

<template>
  <main class="login-page">
    <section class="login-card" aria-labelledby="login-title">
      <header class="login-header">
        <div class="login-brand">
          <span class="login-mark"><AudioLines :size="22" /></span>
          <span class="login-brand-copy">
            <strong>闻录</strong>
            <span>bilibili-to-text</span>
          </span>
        </div>
        <p class="login-kicker">访问保护</p>
        <h1 id="login-title">登录以继续</h1>
        <p class="login-description">
          本站已启用登录保护。请使用管理员账号登录，防止转录与模型额度被未授权使用。
        </p>
      </header>

      <form class="login-form" @submit.prevent="handleSubmit">
        <label class="login-label" for="login-username">用户名</label>
        <div class="login-field">
          <UserRound :size="17" />
          <input
            id="login-username"
            v-model="username"
            type="text"
            name="username"
            autocomplete="username"
            spellcheck="false"
            placeholder="请输入用户名"
            autofocus
          />
        </div>

        <label class="login-label" for="login-password">密码</label>
        <div class="login-field">
          <LockKeyhole :size="17" />
          <input
            id="login-password"
            v-model="password"
            :type="showPassword ? 'text' : 'password'"
            name="password"
            autocomplete="current-password"
            placeholder="请输入密码"
          />
          <button
            class="login-reveal"
            type="button"
            :aria-label="showPassword ? '隐藏密码' : '显示密码'"
            :title="showPassword ? '隐藏密码' : '显示密码'"
            @click="showPassword = !showPassword"
          >
            <EyeOff v-if="showPassword" :size="17" />
            <Eye v-else :size="17" />
          </button>
        </div>

        <button class="login-submit" type="submit" :disabled="!canSubmit">
          <Loader2 v-if="submitting" :size="17" class="spin" />
          <span>{{ submitting ? '登录中…' : '登录' }}</span>
        </button>

        <p v-if="errorMessage" class="login-error" role="alert">
          <ShieldAlert :size="16" />
          <span>{{ errorMessage }}</span>
        </p>

        <p
          v-if="sessionError && !errorMessage"
          class="login-error"
          role="alert"
        >
          <ShieldAlert :size="16" />
          <span>{{ sessionError }}</span>
          <button
            class="login-retry"
            type="button"
            :disabled="checking"
            @click="retrySession"
          >
            {{ checking ? '检查中…' : '重试' }}
          </button>
        </p>
      </form>

      <footer class="login-footer">
        登录状态保存在 HttpOnly Cookie 中，关闭浏览器后不会丢失。
      </footer>
    </section>
  </main>
</template>

<style scoped>
  .login-page {
    display: grid;
    min-height: 100vh;
    padding: 32px 20px;
    place-items: center;
    background:
      radial-gradient(
        circle at 12% 18%,
        rgba(15, 143, 131, 0.12),
        transparent 34%
      ),
      radial-gradient(
        circle at 88% 82%,
        rgba(16, 24, 32, 0.08),
        transparent 38%
      ),
      var(--bg-base);
  }

  .login-card {
    width: 100%;
    max-width: 430px;
    padding: 34px 34px 24px;
    border: 1px solid var(--panel-border);
    border-radius: 12px;
    background: var(--panel-bg);
    box-shadow:
      0 1px 2px rgba(15, 23, 42, 0.05),
      0 18px 48px rgba(15, 23, 42, 0.09);
  }

  .login-header {
    margin-bottom: 24px;
  }

  .login-brand {
    display: flex;
    align-items: center;
    gap: 11px;
    margin-bottom: 26px;
  }

  .login-mark {
    display: grid;
    width: 40px;
    height: 40px;
    place-items: center;
    border-radius: 8px;
    background: #101820;
    color: #5eead4;
  }

  .login-brand-copy {
    display: grid;
    gap: 1px;
  }

  .login-brand-copy strong {
    font-size: 0.92rem;
    line-height: 1.2;
  }

  .login-brand-copy span {
    color: var(--text-muted);
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.04em;
  }

  .login-kicker {
    margin: 0 0 6px;
    color: var(--brand-strong);
    font-size: 0.68rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  .login-header h1 {
    margin: 0 0 9px;
    font-size: 1.52rem;
    font-weight: 780;
    letter-spacing: -0.01em;
    line-height: 1.2;
  }

  .login-description {
    margin: 0;
    color: var(--text-muted);
    font-size: 0.85rem;
    line-height: 1.6;
  }

  .login-form {
    display: grid;
  }

  .login-label {
    margin: 0 0 7px;
    color: var(--text-soft);
    font-size: 0.78rem;
    font-weight: 750;
  }

  .login-field {
    display: flex;
    align-items: center;
    gap: 9px;
    min-height: 44px;
    padding: 0 12px;
    border: 1px solid var(--line);
    border-radius: var(--radius-md);
    background: #fbfcfd;
    color: #8b97a5;
    transition:
      border-color 0.15s ease,
      box-shadow 0.15s ease,
      background-color 0.15s ease;
  }

  .login-field + .login-label {
    margin-top: 17px;
  }

  .login-field:focus-within {
    border-color: var(--brand);
    background: #fff;
    box-shadow: 0 0 0 3px rgba(15, 143, 131, 0.12);
  }

  .login-field input {
    flex: 1 1 auto;
    min-width: 0;
    padding: 10px 0;
    border: 0;
    outline: 0;
    background: transparent;
    color: var(--text-main);
    font-size: 0.9rem;
  }

  .login-field input::placeholder {
    color: #9aa5b2;
  }

  .login-reveal {
    display: grid;
    flex: 0 0 auto;
    width: 30px;
    height: 30px;
    padding: 0;
    place-items: center;
    border: 0;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-muted);
    cursor: pointer;
  }

  .login-reveal:hover {
    background: #eef2f4;
    color: var(--text-soft);
  }

  .login-submit {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    width: 100%;
    min-height: 46px;
    margin-top: 22px;
    padding: 0 20px;
    border: 1px solid var(--brand);
    border-radius: var(--radius-md);
    background: var(--brand);
    color: #fff;
    font-size: 0.92rem;
    font-weight: 750;
    cursor: pointer;
    transition:
      background-color 0.15s ease,
      border-color 0.15s ease,
      box-shadow 0.15s ease;
  }

  .login-submit:hover:not(:disabled) {
    border-color: var(--brand-strong);
    background: var(--brand-strong);
    box-shadow: 0 4px 14px rgba(15, 143, 131, 0.22);
  }

  .login-submit:focus-visible {
    outline: 3px solid rgba(15, 143, 131, 0.2);
    outline-offset: 2px;
  }

  .login-submit:disabled {
    border-color: #94a3b8;
    background: #94a3b8;
    cursor: not-allowed;
    opacity: 0.72;
    box-shadow: none;
  }

  .login-error {
    display: flex;
    align-items: flex-start;
    gap: 7px;
    margin: 14px 0 0;
    color: var(--danger);
    font-size: 0.83rem;
    line-height: 1.5;
  }

  .login-error svg {
    flex: 0 0 auto;
    margin-top: 1px;
  }

  .login-retry {
    flex: 0 0 auto;
    padding: 0;
    border: 0;
    background: transparent;
    color: var(--brand-strong);
    font-size: inherit;
    font-weight: 750;
    text-decoration: underline;
    cursor: pointer;
  }

  .login-retry:disabled {
    cursor: wait;
    opacity: 0.65;
  }

  .login-footer {
    margin-top: 26px;
    padding-top: 15px;
    border-top: 1px solid #edf1f4;
    color: var(--text-muted);
    font-size: 0.72rem;
    line-height: 1.5;
    text-align: center;
  }

  @media (max-width: 480px) {
    .login-page {
      padding: 18px 12px;
    }

    .login-card {
      padding: 28px 22px 20px;
    }
  }
</style>
