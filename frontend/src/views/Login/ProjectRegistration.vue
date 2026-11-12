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
 *
 * ## 单位自己填（2026-11-11 客户反馈）
 *
 * 原来不收单位，审核时要求管理员事先建好组织，结果一直通过不了。
 * 现在申请人自己填所属单位；项目已登记该角色单位时选完角色就预填。
 *
 * ## 查审核结果
 *
 * 审核通过前没有账号、登录不了。同一个链接里「查看我的申请」凭用户名＋口令
 * 看进度；被拒了能看到理由，并带着原来填的内容重新提交。
 */
import { computed, onMounted, ref, watch } from 'vue'
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
  ElSelect,
  ElTag
} from 'element-plus'

import {
  getRegistrationLinkApi,
  getRegistrationStatusApi,
  submitRegistrationApi,
  type RegistrationLinkInfo,
  type RegistrationStatus
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

// apply：填申请；status：查看我的申请
const mode = ref<'apply' | 'status'>('apply')

const form = ref({
  username: '',
  displayName: '',
  mobile: '',
  role: '' as RoleCode | '',
  orgName: '',
  password: '',
  confirm: ''
})

/* 选了角色就预填项目已登记的该角色单位；申请人自己改过的不覆盖 */
let orgNameAutoFilled = ''
watch(
  () => form.value.role,
  (role) => {
    const preset = (role && info.value?.roleOrgNames?.[role as RoleCode]) || ''
    if (!form.value.orgName.trim() || form.value.orgName === orgNameAutoFilled) {
      form.value.orgName = preset
      orgNameAutoFilled = preset
    }
  }
)

const statusForm = ref({ username: '', password: '' })
const statusLoading = ref(false)
const statusResult = ref<RegistrationStatus | undefined>(undefined)

const STATUS_TAG: Record<string, 'success' | 'danger' | 'warning'> = {
  已通过: 'success',
  已拒绝: 'danger',
  待审核: 'warning'
}

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
  if (!form.value.orgName.trim()) {
    ElMessage.warning('请填写所属单位（你所在公司的全称）。')
    return
  }
  if (!form.value.password) {
    ElMessage.warning('请填写口令。')
    return
  }
  if (form.value.password.length < 6) {
    ElMessage.warning('口令至少 6 位。')
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
      orgName: form.value.orgName.trim(),
      displayName: form.value.displayName.trim() || undefined,
      mobile: form.value.mobile.trim() || undefined
    })
    if (!res) return
    submitted.value = true
    // 查进度时自动带上用户名，省得再输一遍
    statusForm.value.username = form.value.username.trim()
  } catch (error) {
    // 展示服务端返回的申请失败原因。
    ElMessage.error(getAicheckErrorMessage(error, '提交失败，请检查填写内容。'))
  } finally {
    submitting.value = false
  }
}

const handleCheckStatus = async () => {
  if (!statusForm.value.username.trim() || !statusForm.value.password) {
    ElMessage.warning('请填写申请时的用户名和口令。')
    return
  }
  statusLoading.value = true
  statusResult.value = undefined
  try {
    const res = await getRegistrationStatusApi(token.value, {
      username: statusForm.value.username.trim(),
      password: statusForm.value.password
    })
    if (res) statusResult.value = res.data
  } catch (error) {
    ElMessage.error(getAicheckErrorMessage(error, '没有找到这个用户名和口令对应的申请。'))
  } finally {
    statusLoading.value = false
  }
}

/* 被拒后带着原来填的内容重新申请，只需改被指出的那一项 */
const handleReapply = () => {
  const previous = statusResult.value
  if (!previous) return
  form.value = {
    username: statusForm.value.username.trim(),
    displayName: previous.displayName,
    mobile: previous.mobile,
    role: previous.role,
    orgName: previous.orgName,
    password: '',
    confirm: ''
  }
  orgNameAutoFilled = ''
  submitted.value = false
  statusResult.value = undefined
  mode.value = 'apply'
}

const switchMode = (next: 'apply' | 'status') => {
  mode.value = next
  statusResult.value = undefined
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
      <!-- 查看我的申请：没账号前唯一能看到进度和拒绝理由的地方 -->
      <template v-else-if="info && mode === 'status'">
        <p class="registration-summary">
          查看你在 <strong>{{ info.projectName || info.projectId }}</strong> 的申请
        </p>
        <ElForm label-width="96px" @submit.prevent="handleCheckStatus">
          <ElFormItem label="用户名">
            <ElInput v-model="statusForm.username" autocomplete="username" />
          </ElFormItem>
          <ElFormItem label="口令">
            <ElInput
              v-model="statusForm.password"
              type="password"
              show-password
              autocomplete="current-password"
              placeholder="申请时设置的口令"
              @keyup.enter="handleCheckStatus"
            />
          </ElFormItem>
          <ElFormItem>
            <ElButton type="primary" :loading="statusLoading" @click="handleCheckStatus">
              查询
            </ElButton>
            <ElButton link @click="switchMode('apply')">返回填写申请</ElButton>
          </ElFormItem>
        </ElForm>
        <div v-if="statusResult" class="status-result" data-testid="registration-status">
          <p>
            审核结果：
            <ElTag :type="STATUS_TAG[statusResult.status] || 'info'" effect="plain">
              {{ statusResult.status }}
            </ElTag>
          </p>
          <p>申请角色：{{ ROLE_LABELS[statusResult.role] || statusResult.role }}</p>
          <p>所属单位：{{ statusResult.orgName || '未填写' }}</p>
          <p v-if="statusResult.status === '待审核'" class="status-hint">
            还在等项目负责人审核，通过后用这个用户名和口令登录。
          </p>
          <template v-else-if="statusResult.status === '已通过'">
            <p class="status-hint">已通过，可以登录了。</p>
            <ElButton type="primary" @click="$router.push('/login')">去登录</ElButton>
          </template>
          <template v-else>
            <p class="status-reject">拒绝理由：{{ statusResult.rejectReason || '未说明' }}</p>
            <ElButton type="primary" @click="handleReapply">修改后重新申请</ElButton>
          </template>
        </div>
      </template>

      <ElResult
        v-else-if="submitted"
        icon="success"
        title="已提交，等待项目负责人审核"
        sub-title="审核通过后你的账号才会创建，届时可用刚才设置的用户名和口令登录。现在还不能登录。"
      >
        <template #extra>
          <ElButton @click="switchMode('status')">查看审核进度</ElButton>
        </template>
      </ElResult>

      <template v-else-if="info">
        <p class="registration-summary">
          你正在申请加入 <strong>{{ info.projectName || info.projectId }}</strong>
        </p>
        <!-- 申请人还没账号、多半第一次用：先说清接下来会发生什么 -->
        <ol class="registration-steps" aria-label="加入项目的步骤">
          <li><strong>填下面的表</strong>：姓名、单位、你在项目里的角色，自己设一个密码。</li>
          <li><strong>等项目负责人审核</strong>：可以随时回这个链接点「查看我的申请」看进度。</li>
          <li>
            <strong>审核通过后登录</strong>：用刚才的用户名和密码，第一次进去会有引导教你怎么用。
          </li>
        </ol>

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
          <ElFormItem label="所属单位" required>
            <ElInput
              v-model="form.orgName"
              maxlength="80"
              placeholder="你所在公司的全称，例如：某某工程有限公司"
              data-testid="registration-org-name"
            />
          </ElFormItem>
          <ElFormItem label="设置口令">
            <ElInput
              v-model="form.password"
              type="password"
              show-password
              autocomplete="new-password"
              placeholder="至少 6 位"
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
        <p class="registration-switch">
          已经提交过？
          <ElButton link type="primary" @click="switchMode('status')">查看我的申请</ElButton>
        </p>
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

.registration-steps {
  display: grid;
  padding: 10px 12px 10px 30px;
  margin: 0 0 16px;
  font-size: 13px;
  line-height: 20px;
  color: #475467;
  background: var(--el-fill-color-light);
  border-radius: 6px;
  gap: 4px;
}

.registration-steps strong {
  color: var(--el-text-color-primary);
}

.registration-switch {
  margin: 8px 0 0;
  color: var(--el-text-color-secondary);
  text-align: center;
}

.status-result {
  padding: 12px 16px;
  margin-top: 8px;
  line-height: 1.9;
  background: var(--el-fill-color-light);
  border-radius: 6px;
}

.status-result p {
  margin: 0;
}

.status-hint {
  color: var(--el-text-color-secondary);
}

.status-reject {
  margin-bottom: 8px !important;
  color: var(--el-color-danger);
}

.registration-hint {
  margin-left: 10px;
  color: var(--el-text-color-secondary);
}
</style>
