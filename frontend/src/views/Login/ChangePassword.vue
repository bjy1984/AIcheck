<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import {
  ElAlert,
  ElButton,
  ElForm,
  ElFormItem,
  ElInput,
  ElMessage,
  type FormInstance,
  type FormRules
} from 'element-plus'
import { changePasswordApi } from '@/api/login'
import { useUserStore } from '@/store/modules/user'
import { usePermissionStore } from '@/store/modules/permission'
import { getRoleDefaultPath } from '@/utils/roleAccess'
import { getAicheckErrorMessage } from '@/utils/aicheckError'

const router = useRouter()
const userStore = useUserStore()
const permissionStore = usePermissionStore()
const formRef = ref<FormInstance>()
const loading = ref(false)
const errorMessage = ref('')
const form = reactive({
  currentPassword: '',
  newPassword: '',
  confirmPassword: ''
})

const passwordProblems = (value: string) => {
  const classes = [
    /[a-z]/.test(value),
    /[A-Z]/.test(value),
    /\d/.test(value),
    /[^A-Za-z0-9]/.test(value)
  ]
  const problems: string[] = []
  if (value.length < 12) problems.push('至少 12 位')
  if (classes.filter(Boolean).length < 3) problems.push('至少包含三类字符')
  if (
    userStore.getUserInfo?.username &&
    value.toLowerCase().includes(userStore.getUserInfo.username.toLowerCase())
  ) {
    problems.push('不得包含用户名')
  }
  return problems
}

const rules: FormRules = {
  currentPassword: [{ required: true, message: '请输入当前密码', trigger: 'blur' }],
  newPassword: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    {
      validator: (_rule, value: string, callback) => {
        const problems = passwordProblems(value || '')
        callback(problems.length ? new Error(problems.join('，')) : undefined)
      },
      trigger: 'blur'
    }
  ],
  confirmPassword: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (_rule, value: string, callback) => {
        callback(value === form.newPassword ? undefined : new Error('两次输入的密码不一致'))
      },
      trigger: 'blur'
    }
  ]
}

const ensureRoleRoutes = async (role?: string) => {
  await permissionStore.generateRoutes('static', undefined, role)
  permissionStore.getAddRouters.forEach((route) => {
    router.addRoute(route as RouteRecordRaw)
  })
  permissionStore.setIsAddRouters(true)
}

const submit = async () => {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await changePasswordApi({
      currentPassword: form.currentPassword,
      newPassword: form.newPassword
    })
    if (!response) {
      errorMessage.value = '密码修改失败，请检查当前密码和安全要求。'
      return
    }
    userStore.setToken(response.data.token ? `Bearer ${response.data.token}` : '')
    userStore.setUserInfo(response.data.user)
    await ensureRoleRoutes(response.data.user?.role)
    ElMessage.success('密码已更新，请使用新密码继续工作。')
    await router.replace(
      response.data.defaultPath || getRoleDefaultPath(response.data.user?.role)
    )
  } catch (error: unknown) {
    errorMessage.value = getAicheckErrorMessage(error, '密码修改失败，请稍后重试。')
  } finally {
    loading.value = false
  }
}

const logout = async () => {
  userStore.logout()
}
</script>

<template>
  <main class="password-page">
    <section class="password-panel" aria-labelledby="password-title">
      <header>
        <img src="@/assets/imgs/logo.png" alt="AIcheck" />
        <div>
          <h1 id="password-title">设置安全密码</h1>
          <p>首次登录必须修改初始密码，完成后才能进入业务工作台。</p>
        </div>
      </header>

      <ElAlert
        v-if="errorMessage"
        type="error"
        show-icon
        :closable="false"
        :title="errorMessage"
        role="alert"
      />

      <ElForm
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        @submit.prevent="submit"
      >
        <ElFormItem label="当前密码" prop="currentPassword">
          <ElInput
            v-model="form.currentPassword"
            type="password"
            show-password
            autocomplete="current-password"
            aria-label="当前密码"
          />
        </ElFormItem>
        <ElFormItem label="新密码" prop="newPassword">
          <ElInput
            v-model="form.newPassword"
            type="password"
            show-password
            autocomplete="new-password"
            aria-label="新密码"
          />
          <p class="password-help"
            >至少 12 位，并包含大写字母、小写字母、数字、特殊字符中的三类。</p
          >
        </ElFormItem>
        <ElFormItem label="确认新密码" prop="confirmPassword">
          <ElInput
            v-model="form.confirmPassword"
            type="password"
            show-password
            autocomplete="new-password"
            aria-label="确认新密码"
            @keyup.enter="submit"
          />
        </ElFormItem>
        <div class="password-actions">
          <ElButton native-type="button" @click="logout">退出登录</ElButton>
          <ElButton type="primary" native-type="submit" :loading="loading">保存并进入系统</ElButton>
        </div>
      </ElForm>
    </section>
  </main>
</template>

<style scoped>
.password-page {
  display: grid;
  min-height: 100dvh;
  padding: 24px;
  color: #24364f;
  background: #eef3f8;
  place-items: center;
}

.password-panel {
  width: min(100%, 520px);
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
  margin-bottom: 24px;
}

header img {
  width: 48px;
  height: 48px;
  object-fit: contain;
}

h1 {
  margin: 0;
  font-size: 24px;
  letter-spacing: 0;
}

header p,
.password-help {
  margin: 6px 0 0;
  line-height: 1.6;
  color: #52647d;
}

.password-help {
  font-size: 13px;
}

.password-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 8px;
}

.password-actions :deep(.el-button) {
  min-height: 44px;
}

@media (width <= 520px) {
  .password-page {
    padding: 16px;
  }

  .password-panel {
    padding: 24px 20px;
  }

  .password-actions {
    flex-direction: column-reverse;
  }

  .password-actions :deep(.el-button) {
    width: 100%;
    margin: 0;
  }
}
</style>
