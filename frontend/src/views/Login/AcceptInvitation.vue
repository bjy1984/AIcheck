<script setup lang="ts">
/**
 * 凭邀请链接注册（0817 第 4 条）。
 *
 * ## 这个页面的收件人还没有账号
 *
 * 所以它必须在**登录之前**可达：不能挂在需要登录的布局下，
 * 也不能因为没有登录态就被路由守卫弹回登录页。
 *
 * ## 角色和组织不由这个页面决定
 *
 * 它们写死在邀请里。页面只**显示**「你被邀请加入 X，角色 Y」，
 * 不提供任何选择——服务端也不看请求里的 role/orgId。
 * 让注册者自选角色的链接，等于一个公开的提权入口。
 *
 * ## 失败要说人话，但不能说太细
 *
 * 「不存在」「已用过」「已过期」服务端一律回同一句「无效或已过期」
 * ——区分了就成了给撞令牌的人送反馈。这里照搬服务端的话，不自己加戏。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElAlert, ElButton, ElCard, ElForm, ElFormItem, ElInput, ElMessage } from 'element-plus'

import { acceptInvitationApi, getInvitationApi, type InvitationInfo } from '@/api/aicheck'
import { getAicheckErrorMessage } from '@/utils/aicheckError'

const route = useRoute()
const router = useRouter()

const token = computed(() => String(route.params.token || route.query.token || ''))
const loading = ref(true)
const submitting = ref(false)
const invitation = ref<InvitationInfo | undefined>(undefined)
const loadError = ref('')

const form = ref({ username: '', displayName: '', password: '', confirm: '' })

const ROLE_LABELS: Record<string, string> = {
  inspection: '监检人员',
  contractor: '施工单位',
  ndt: '无损检测',
  owner: '建设单位',
  admin: '系统管理员',
  fde: 'FDE'
}

const roleLabel = computed(() =>
  invitation.value ? ROLE_LABELS[invitation.value.role] || invitation.value.role : ''
)

onMounted(async () => {
  if (!token.value) {
    loadError.value = '邀请链接不完整。'
    loading.value = false
    return
  }
  try {
    const res = await getInvitationApi(token.value)
    if (!res) {
      loadError.value = '邀请链接无效或已过期。'
      return
    }
    invitation.value = res.data
  } catch (error) {
    loadError.value = getAicheckErrorMessage(error, '邀请链接无效或已过期。')
  } finally {
    loading.value = false
  }
})

const handleSubmit = async () => {
  if (!form.value.username.trim()) {
    ElMessage.warning('请填写用户名。')
    return
  }
  /* 两次口令不一致要在**提交前**拦住。
     交给服务端的话，注册成功了但口令不是他以为的那个，
     下次登录才发现——而那时已经没有第二次机会填了。 */
  if (form.value.password !== form.value.confirm) {
    ElMessage.warning('两次输入的口令不一致。')
    return
  }
  submitting.value = true
  try {
    const res = await acceptInvitationApi(token.value, {
      username: form.value.username.trim(),
      password: form.value.password,
      displayName: form.value.displayName.trim() || undefined
    })
    if (!res) return
    ElMessage.success('注册成功，请使用新账号登录。')
    router.push('/login')
  } catch (error) {
    // 口令强度这类校验由服务端说了算，原样转述——
    // 前端自己写一套提示，两边一旦不一致，用户会照着前端的提示反复失败
    ElMessage.error(getAicheckErrorMessage(error, '注册失败，请检查填写内容。'))
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="invitation-page">
    <ElCard v-loading="loading" class="invitation-card">
      <template #header>
        <strong>接受邀请</strong>
      </template>

      <ElAlert v-if="loadError" type="error" :title="loadError" :closable="false" show-icon />

      <template v-else-if="invitation">
        <!-- 组织和角色只展示、不可改：它们写死在邀请里，
             服务端也不看请求里的 role/orgId -->
        <p class="invitation-summary">
          你被邀请加入 <strong>{{ invitation.orgName || invitation.orgId }}</strong
          >，角色为 <strong>{{ roleLabel }}</strong
          >。
        </p>

        <ElForm label-width="88px" @submit.prevent>
          <ElFormItem label="用户名">
            <ElInput v-model="form.username" autocomplete="username" />
          </ElFormItem>
          <ElFormItem label="姓名">
            <ElInput v-model="form.displayName" placeholder="选填，默认与用户名相同" />
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
              完成注册
            </ElButton>
          </ElFormItem>
        </ElForm>
      </template>
    </ElCard>
  </div>
</template>

<style scoped>
.invitation-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 24px;
  background: var(--el-bg-color-page);
}

.invitation-card {
  width: 100%;
  max-width: 420px;
}

.invitation-summary {
  margin: 0 0 16px;
  line-height: 1.8;
}
</style>
