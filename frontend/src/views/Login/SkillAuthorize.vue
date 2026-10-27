<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElAlert, ElButton } from 'element-plus'
import { authorizeSkillApi } from '@/api/login'
import { useUserStore } from '@/store/modules/user'
import { getAicheckErrorMessage } from '@/utils/aicheckError'
import {
  SKILL_AUTHORIZE_ROLES,
  decodeSkillAuthorizeRequest,
  skillCallbackUrl
} from './skillAuthorize'

const route = useRoute()
const userStore = useUserStore()
const loading = ref(false)
const done = ref('')
const errorMessage = ref('')

const authorizeRequest = computed(() => decodeSkillAuthorizeRequest(route.params.payload))
const user = computed(() => userStore.getUserInfo)
const canAuthorize = computed(() => SKILL_AUTHORIZE_ROLES.includes(String(user.value?.role || '')))

const authorize = async () => {
  const request = authorizeRequest.value
  if (!request || !canAuthorize.value) return
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await authorizeSkillApi({
      redirectUri: request.redirectUri,
      codeChallenge: request.codeChallenge
    })
    const code = response?.data?.code
    if (!code) {
      errorMessage.value = '授权失败：服务器没有返回授权码，请回到助手重新运行 login --web。'
      return
    }
    done.value = '已授权，正在把授权交回 skill……可以回到助手那边了。'
    window.location.assign(skillCallbackUrl(request, { code }))
  } catch (error: unknown) {
    errorMessage.value = getAicheckErrorMessage(error, '授权失败，请稍后重试。')
  } finally {
    loading.value = false
  }
}

const deny = () => {
  const request = authorizeRequest.value
  if (!request) return
  done.value = '已拒绝。skill 不会拿到任何权限。'
  window.location.assign(skillCallbackUrl(request, { error: 'access_denied' }))
}

const switchAccount = () => {
  userStore.logout()
}
</script>

<template>
  <main class="authorize-page">
    <section class="authorize-panel" aria-labelledby="authorize-title">
      <header>
        <img src="@/assets/imgs/logo.png" alt="AIcheck" />
        <div>
          <h1 id="authorize-title">授权 AIcheck 节点审计 skill</h1>
          <p>本机的 skill 请求以你的身份访问平台：拉取节点资料、做服务器 OCR、查证书和标准。</p>
        </div>
      </header>

      <ElAlert
        v-if="!authorizeRequest"
        type="error"
        show-icon
        :closable="false"
        title="授权链接无效或不完整。请回到助手，重新运行 login --web 获取新链接。"
        role="alert"
      />

      <template v-else>
        <dl class="authorize-facts">
          <div>
            <dt>登录账号</dt>
            <dd
              >{{ user?.displayName || user?.username }}（{{ user?.roleLabel || user?.role }}）</dd
            >
          </div>
          <div>
            <dt>交给谁</dt>
            <dd>这台电脑上端口 {{ authorizeRequest.port }} 的 skill</dd>
          </div>
          <div>
            <dt>有效期</dt>
            <dd>与登录相同，到期后需要重新授权</dd>
          </div>
        </dl>

        <ElAlert
          v-if="!canAuthorize"
          type="warning"
          show-icon
          :closable="false"
          title="当前账号不能给 skill 授权：只有监检和管理员账号可以。请切换账号后再打开这个链接。"
          role="alert"
        />
        <ElAlert
          v-else
          type="info"
          show-icon
          :closable="false"
          title="只有在你自己刚刚让助手运行 login --web 时才点授权。别人发来的授权链接不要点。"
        />

        <ElAlert
          v-if="errorMessage"
          type="error"
          show-icon
          :closable="false"
          :title="errorMessage"
          role="alert"
        />
        <ElAlert v-if="done" type="success" show-icon :closable="false" :title="done" />

        <div class="authorize-actions">
          <template v-if="canAuthorize">
            <ElButton :disabled="loading || !!done" @click="deny">拒绝</ElButton>
            <ElButton type="primary" :loading="loading" :disabled="!!done" @click="authorize"
              >授权</ElButton
            >
          </template>
          <ElButton v-else type="primary" @click="switchAccount">切换账号</ElButton>
        </div>
      </template>
    </section>
  </main>
</template>

<style scoped>
.authorize-page {
  display: grid;
  min-height: 100dvh;
  padding: 24px;
  color: #24364f;
  background: #eef3f8;
  place-items: center;
}

.authorize-panel {
  display: grid;
  gap: 16px;
  width: min(100%, 560px);
  padding: 32px;
  background: #fff;
  border: 1px solid #d6e0ed;
  border-radius: 8px;
  box-shadow: 0 12px 32px rgb(35 54 79 / 10%);
}

header {
  display: flex;
  align-items: center;
  gap: 16px;
}

header img {
  width: 48px;
  height: 48px;
  object-fit: contain;
}

h1 {
  margin: 0;
  font-size: 22px;
  letter-spacing: 0;
}

header p {
  margin: 6px 0 0;
  line-height: 1.6;
  color: #52647d;
}

.authorize-facts {
  display: grid;
  gap: 10px;
  margin: 0;
  padding: 16px;
  background: #f6f9fc;
  border: 1px solid #e3eaf3;
  border-radius: 6px;
}

.authorize-facts div {
  display: grid;
  grid-template-columns: 88px 1fr;
  gap: 12px;
}

.authorize-facts dt {
  color: #52647d;
}

.authorize-facts dd {
  margin: 0;
  font-weight: 500;
}

.authorize-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.authorize-actions :deep(.el-button) {
  min-height: 44px;
  min-width: 96px;
}

@media (width <= 520px) {
  .authorize-page {
    padding: 16px;
  }

  .authorize-panel {
    padding: 24px 20px;
  }

  .authorize-facts div {
    grid-template-columns: 1fr;
    gap: 2px;
  }

  .authorize-actions {
    flex-direction: column-reverse;
  }

  .authorize-actions :deep(.el-button) {
    width: 100%;
    margin: 0;
  }
}
</style>
