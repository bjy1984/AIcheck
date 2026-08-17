<script setup lang="ts">
/**
 * 项目注册：通过链接进来，自选角色，提交后等负责人审核。
 *
 * ## 这个页面的人还没有账号
 *
 * 所以它必须在登录之前可达——不能挂在需要登录的布局下，
 * 也不能因为没有登录态被路由守卫弹回登录页。
 *
 * ## 提交之后没有账号
 *
 * 这一点必须在界面上说清楚。用户填完表单、看到「成功」，
 * 会自然而然去登录，然后登不进去——**那时他会以为注册失败了，
 * 于是再填一遍**。所以成功页要写明「等待审核」，而不是笼统的「提交成功」。
 *
 * ## 角色可以自选，因为审核是闸门
 *
 * 上一版邀请链接把角色写死，理由是「自选角色的链接等于公开提权入口」。
 * 加了审核之后这个理由不成立了：自选只是填表，审核才决定给不给。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElForm,
  ElFormItem,
  ElInput,
  ElMessage,
  ElOption,
  ElResult,
  ElSelect
} from 'element-plus'

import {
  getRegistrationLinkApi,
  submitRegistrationApi,
  type RegistrationLinkInfo
} from '@/api/aicheck'
import type { RoleCode } from '@/types/aicheck'
import { getAicheckErrorMessage } from '@/utils/aicheckError'

const route = useRoute()
const token = computed(() => String(route.params.token || ''))

const loading = ref(true)
const submitting = ref(false)
const submitted = ref(false)
const info = ref<RegistrationLinkInfo | undefined>(undefined)
const loadError = ref('')

const form = ref({
  username: '',
  displayName: '',
  mobile: '',
  role: '' as RoleCode | '',
  password: '',
  confirm: ''
})

const ROLE_LABELS: Record<string, string> = {
  inspection: '监检人员',
  contractor: '施工单位',
  ndt: '无损检测',
  owner: '建设单位'
}

onMounted(async () => {
  if (!token.value) {
    loadError.value = '注册链接不完整。'
    loading.value = false
    return
  }
  try {
    const res = await getRegistrationLinkApi(token.value)
    if (!res) {
      loadError.value = '注册链接无效或已过期。'
      return
    }
    info.value = res.data
  } catch (error) {
    loadError.value = getAicheckErrorMessage(error, '注册链接无效或已过期。')
  } finally {
    loading.value = false
  }
})

const handleSubmit = async () => {
  if (!form.value.username.trim()) {
    ElMessage.warning('请填写用户名。')
    return
  }
  if (!form.value.role) {
    ElMessage.warning('请选择你在本项目中的角色。')
    return
  }
  /* 两次口令不一致要在提交前拦住：交给服务端的话，申请提上去了但口令
     不是他以为的那个，等审核通过去登录才发现——那时已经改不了了。 */
  if (form.value.password !== form.value.confirm) {
    ElMessage.warning('两次输入的口令不一致。')
    return
  }
  submitting.value = true
  try {
    const res = await submitRegistrationApi(token.value, {
      username: form.value.username.trim(),
      password: form.value.password,
      role: form.value.role,
      displayName: form.value.displayName.trim() || undefined,
      mobile: form.value.mobile.trim() || undefined
    })
    if (!res) return
    submitted.value = true
  } catch (error) {
    // 口令强度这类校验由服务端说了算，原样转述；
    // 前端另写一套提示，两边一旦不一致，用户会照着前端的提示反复失败
    ElMessage.error(getAicheckErrorMessage(error, '提交失败，请检查填写内容。'))
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="registration-page">
    <ElCard v-loading="loading" class="registration-card">
      <template #header>
        <strong>加入项目</strong>
      </template>

      <ElAlert v-if="loadError" type="error" :title="loadError" :closable="false" show-icon />

      <!-- 提交之后**没有账号**。不说清楚的话，用户会去登录、登不进去，
           以为注册失败了，然后再填一遍。 -->
      <ElResult
        v-else-if="submitted"
        icon="success"
        title="已提交，等待项目负责人审核"
        sub-title="审核通过后你的账号才会创建，届时可用刚才设置的用户名和口令登录。现在还不能登录。"
      />

      <template v-else-if="info">
        <p class="registration-summary">
          你正在申请加入 <strong>{{ info.projectName || info.projectId }}</strong>
        </p>

        <ElForm label-width="96px" @submit.prevent>
          <ElFormItem label="用户名">
            <ElInput v-model="form.username" autocomplete="username" />
          </ElFormItem>
          <ElFormItem label="姓名">
            <ElInput v-model="form.displayName" placeholder="选填，默认与用户名相同" />
          </ElFormItem>
          <ElFormItem label="手机号">
            <ElInput v-model="form.mobile" placeholder="选填" />
          </ElFormItem>
          <!-- 角色自选。审核才是闸门，这里只是填表 -->
          <ElFormItem label="我的角色">
            <ElSelect v-model="form.role" placeholder="请选择你在本项目中的角色">
              <ElOption
                v-for="role in info.selectableRoles"
                :key="role"
                :label="ROLE_LABELS[role] || role"
                :value="role"
              />
            </ElSelect>
          </ElFormItem>
          <ElFormItem label="设置口令">
            <ElInput
              v-model="form.password"
              type="password"
              show-password
              autocomplete="new-password"
            />
          </ElFormItem>
          <ElFormItem label="确认口令">
            <ElInput
              v-model="form.confirm"
              type="password"
              show-password
              autocomplete="new-password"
            />
          </ElFormItem>
          <ElFormItem>
            <ElButton type="primary" :loading="submitting" @click="handleSubmit">
              提交申请
            </ElButton>
            <small class="registration-hint">提交后需项目负责人审核通过才能登录</small>
          </ElFormItem>
        </ElForm>
      </template>
    </ElCard>
  </div>
</template>

<style scoped>
.registration-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 24px;
  background: var(--el-bg-color-page);
}

.registration-card {
  width: 100%;
  max-width: 460px;
}

.registration-summary {
  margin: 0 0 16px;
  line-height: 1.8;
}

.registration-hint {
  margin-left: 10px;
  color: var(--el-text-color-secondary);
}
</style>
