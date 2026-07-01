<script setup lang="ts">
import { LoginForm, RegisterForm } from './components'
import { ThemeSwitch } from '@/components/ThemeSwitch'
import { LocaleDropdown } from '@/components/LocaleDropdown'
import { underlineToHump } from '@/utils'
import { useAppStore } from '@/store/modules/app'
import { useDesign } from '@/hooks/web/useDesign'
import { ref } from 'vue'
import { ElScrollbar } from 'element-plus'

const { getPrefixCls } = useDesign()

const prefixCls = getPrefixCls('login')

const appStore = useAppStore()

const isLogin = ref(true)

const toRegister = () => {
  isLogin.value = false
}

const toLogin = () => {
  isLogin.value = true
}
</script>

<template>
  <div :class="[prefixCls, 'aicheck-login-page']" class="h-[100%] relative">
    <ElScrollbar class="h-full">
      <main class="aicheck-login-shell">
        <section :class="`${prefixCls}__left aicheck-login-brief`">
          <div class="brand-row">
            <img src="@/assets/imgs/logo.png" alt="AIcheck" class="brand-logo" />
            <div>
              <div class="brand-name">{{ underlineToHump(appStore.getTitle) }}</div>
              <div class="brand-subtitle">AI 资料审查操作系统</div>
            </div>
          </div>

          <div class="brief-content">
            <p class="eyebrow">AI DELIVERY WORKSPACE</p>
            <h1>AIcheck 审查工作台</h1>
            <p class="brief-copy">
              面向资料审查、证据追溯、规则知识与 AI
              治理的一体化入口。不同角色进入各自面板，业务结论和 AI 运行全程留痕。
            </p>

            <div class="capability-strip" aria-label="系统能力">
              <span>角色隔离</span>
              <span>本地 OCR</span>
              <span>证据留痕</span>
              <span>FDE 治理</span>
            </div>
          </div>
        </section>

        <section class="aicheck-login-main">
          <div class="login-toolbar">
            <div class="mobile-brand">
              <img src="@/assets/imgs/logo.png" alt="AIcheck" class="brand-logo small" />
              <span>{{ underlineToHump(appStore.getTitle) }}</span>
            </div>

            <div class="toolbar-actions">
              <ThemeSwitch />
              <LocaleDropdown class="login-locale" />
            </div>
          </div>

          <Transition appear enter-active-class="animate__animated animate__fadeInUp">
            <div class="auth-panel-wrap">
              <LoginForm v-if="isLogin" class="auth-panel" @to-register="toRegister" />
              <RegisterForm v-else class="auth-panel" @to-login="toLogin" />
            </div>
          </Transition>
        </section>
      </main>
    </ElScrollbar>
  </div>
</template>

<style lang="less" scoped>
@prefix-cls: ~'@{adminNamespace}-login';

.@{prefix-cls} {
  overflow: auto;

  &__left {
    position: relative;
  }
}

.aicheck-login-page {
  --login-primary: #1f66d8;
  --login-primary-strong: #174fa8;
  --login-ink: #26364e;
  --login-text: #52647d;
  --login-muted: #6e7d92;
  --login-line: #d9e2ef;
  --login-soft: #f5f8fd;
  --login-surface: #fff;
  --login-accent: #ff7a2f;
  --el-color-primary: var(--login-primary);
  --el-color-primary-dark-2: var(--login-primary-strong);
  --el-color-primary-light-9: #eef5ff;

  min-height: 100dvh;
  color: var(--login-ink);
  background: #eef3f8;
}

.aicheck-login-shell {
  display: grid;
  grid-template-columns: minmax(400px, 0.86fr) minmax(440px, 1fr);
  min-height: 100dvh;
}

.aicheck-login-brief {
  position: relative;
  display: flex;
  padding: 36px;
  overflow: hidden;
  background: #06152f;
  border-right: 1px solid rgb(92 147 220 / 30%);
  flex-direction: column;
}

.aicheck-login-brief::before {
  position: absolute;
  pointer-events: none;
  background-image: linear-gradient(rgb(122 207 255 / 24%) 1px, transparent 1px),
    linear-gradient(90deg, rgb(122 207 255 / 22%) 1px, transparent 1px);
  background-position: 0 0;
  background-size: 50px 50px;
  content: '';
  box-shadow: inset 0 0 120px rgb(12 34 72 / 78%);
  animation: login-grid-scroll 0.92s linear infinite reverse;
  inset: 0;
}

.aicheck-login-brief::after {
  position: absolute;
  pointer-events: none;
  background: radial-gradient(circle at 74% 30%, rgb(75 171 255 / 20%), transparent 28%),
    linear-gradient(90deg, rgb(3 14 31 / 82%) 0%, rgb(6 21 47 / 34%) 48%, rgb(3 14 31 / 68%) 100%);
  content: '';
  inset: 0;
}

.brand-row,
.mobile-brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.aicheck-login-brief .brand-row,
.brief-content {
  position: relative;
  z-index: 2;
}

.brand-logo {
  width: 46px;
  height: 46px;
  object-fit: contain;
}

.brand-logo.small {
  width: 34px;
  height: 34px;
}

.brand-name {
  font-size: 20px;
  font-weight: 800;
  line-height: 1.2;
  color: #f7fbff;
}

.brand-subtitle {
  margin-top: 4px;
  font-size: 13px;
  font-weight: 700;
  color: rgb(202 218 240 / 82%);
}

.brief-content {
  display: flex;
  flex: 1;
  flex-direction: column;
  justify-content: center;
  max-width: 560px;
  padding: 48px 0;
}

.eyebrow {
  margin: 0 0 14px;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0;
  color: #7db7ff;
}

.brief-content h1 {
  max-width: 480px;
  margin: 0;
  font-size: 36px;
  font-weight: 800;
  line-height: 1.24;
  color: #f8fbff;
}

.brief-copy {
  max-width: 520px;
  margin: 18px 0 0;
  font-size: 15px;
  line-height: 1.85;
  color: rgb(218 229 246 / 82%);
}

.capability-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  max-width: 520px;
  margin-top: 30px;
}

.capability-strip span {
  padding: 8px 12px;
  font-size: 13px;
  font-weight: 800;
  color: #dcecff;
  background: rgb(255 255 255 / 8%);
  border: 1px solid rgb(132 178 240 / 34%);
  border-radius: 999px;
  box-shadow: 0 0 22px rgb(84 154 255 / 8%);
}

.aicheck-login-main {
  display: flex;
  min-width: 0;
  flex-direction: column;
  padding: 26px 32px 32px;
}

.login-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 46px;
}

.mobile-brand {
  font-size: 17px;
  font-weight: 800;
  visibility: hidden;
}

.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-left: auto;
}

.login-locale {
  color: var(--login-ink);
}

.auth-panel-wrap {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: center;
  padding: 30px 0;
}

.auth-panel {
  width: min(100%, 430px);
  padding: 30px;
  background: #fff;
  border: 1px solid rgb(210 220 234 / 94%);
  border-radius: 8px;
  box-shadow: 0 18px 42px rgb(47 65 91 / 10%);
}

:deep(.auth-form-title) {
  margin: 0;
  font-size: 24px;
  font-weight: 800;
  line-height: 1.25;
  color: var(--login-ink);
  text-align: left;
}

:deep(.auth-form-subtitle) {
  margin: 8px 0 2px;
  font-size: 14px;
  line-height: 1.6;
  color: var(--login-text);
}

:deep(.auth-form .el-form-item) {
  margin-bottom: 18px;
}

:deep(.auth-form .el-form-item__label) {
  padding-bottom: 7px;
  font-size: 13px;
  font-weight: 800;
  line-height: 1.2;
  color: var(--login-ink);
}

:deep(.auth-form .el-input__wrapper) {
  min-height: 44px;
  background: #fbfdff;
  border-radius: 6px;
  box-shadow: 0 0 0 1px #d9e2ef inset;
}

:deep(.auth-form .el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #9db8df inset;
}

:deep(.auth-form .el-input__wrapper.is-focus) {
  box-shadow:
    0 0 0 1px var(--login-primary) inset,
    0 0 0 3px rgb(31 102 216 / 13%);
}

:deep(.auth-form .el-checkbox__label),
:deep(.auth-form .el-link) {
  font-size: 13px;
  font-weight: 700;
}

:deep(.auth-submit-button),
:deep(.auth-secondary-button),
:deep(.auth-code-button) {
  min-height: 44px;
  font-weight: 800;
  border-radius: 6px;
}

:deep(.auth-submit-button) {
  box-shadow: 0 9px 18px rgb(31 102 216 / 15%);
}

:deep(.auth-helper-line) {
  width: 100%;
  margin: -2px 0 0;
  font-size: 12px;
  font-weight: 700;
  line-height: 1.6;
  color: var(--login-muted);
}

:deep(.auth-helper-line b) {
  font-weight: 800;
  color: var(--login-ink);
}

:deep(.auth-code-row) {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  width: 100%;
}

@media (width <= 1180px) {
  .aicheck-login-shell {
    grid-template-columns: minmax(0, 1fr);
  }

  .aicheck-login-brief {
    display: none;
  }

  .mobile-brand {
    visibility: visible;
  }

  .aicheck-login-main {
    min-height: 100dvh;
  }
}

@media (width <= 560px) {
  .aicheck-login-main {
    padding: 16px;
  }

  .auth-panel-wrap {
    align-items: flex-start;
    padding: 20px 0;
  }

  .auth-panel {
    padding: 20px;
  }

  .toolbar-actions {
    gap: 6px;
  }

  :deep(.auth-code-row) {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (prefers-reduced-motion: reduce) {
  .aicheck-login-page *,
  .aicheck-login-page *::before,
  .aicheck-login-page *::after {
    animation-duration: 0s !important;
    transition-duration: 0s !important;
  }
}

@keyframes login-grid-scroll {
  from {
    background-position: 0 0;
  }

  to {
    background-position: 50px 50px;
  }
}
</style>
