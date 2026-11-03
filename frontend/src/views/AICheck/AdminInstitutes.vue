<script setup lang="ts">
/* 平台管理员开通特检院：建院的同时建好它的第一个院管理员；院管理员登录后在本院建用户、
 * 发项目邀请，各院数据互相看不到。停用后该院的人立即登不进来，数据保留。 */
import { computed, onMounted, reactive, ref } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElDialog,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElInput,
  ElMessage,
  ElMessageBox,
  ElOption,
  ElSelect,
  ElTable,
  ElTableColumn,
  ElTag
} from 'element-plus'
import StaticPageShell from './components/StaticPageShell.vue'
import {
  createInstituteApi,
  getInstitutesApi,
  setInstituteStatusApi,
  syncPlatformRulesApi,
  addInstituteAdminApi,
  resetInstituteAdminPasswordApi
} from '@/api/aicheck'
import type { Institute } from '@/api/aicheck/platform'
import { useUserStoreWithOut } from '@/store/modules/user'
import { getAicheckErrorMessage } from '@/utils/aicheckError'
import {
  ADMIN_BOUNDARY_BADGE,
  ADMIN_BOUNDARY_TITLE,
  ADMIN_MENU_ROOT,
  ADMIN_MENU_TITLE,
  buildAdminMenuSections
} from './adminMenuTree'

const userStore = useUserStoreWithOut()
const platformAdmin = computed(() => Boolean(userStore.getUserInfo?.platformAdmin))
const userLabel = computed(
  () => userStore.getUserInfo?.displayName || userStore.getUserInfo?.username || '平台管理员'
)
const menuSections = computed(() =>
  buildAdminMenuSections('/admin/institutes', { platformAdmin: platformAdmin.value })
)

const items = ref<Institute[]>([])
const loading = ref(false)
const loadError = ref('')

const load = async () => {
  if (!platformAdmin.value) return
  loading.value = true
  loadError.value = ''
  try {
    const res = await getInstitutesApi()
    items.value = res.data?.items || []
  } catch (error) {
    loadError.value = getAicheckErrorMessage(error, '特检院列表加载失败，请稍后重试。')
  } finally {
    loading.value = false
  }
}

const activeCount = computed(() => items.value.filter((item) => item.status === 'active').length)

/* 开通弹窗 */
const createOpen = ref(false)
const creating = ref(false)
const createError = ref('')
const form = reactive({ code: '', name: '', adminUsername: '', adminName: '', adminPassword: '' })
let createKey = ''

const openCreate = () => {
  Object.assign(form, { code: '', name: '', adminUsername: '', adminName: '', adminPassword: '' })
  createError.value = ''
  createKey = `institute-create-${Date.now()}`
  createOpen.value = true
}

const submitCreate = async () => {
  const code = form.code.trim().toUpperCase()
  if (!/^[A-Z0-9][A-Z0-9-]{1,31}$/.test(code)) {
    createError.value = '单位代码用 2–32 位大写字母、数字或连字符，例如 GDTJ。'
    return
  }
  if (!form.name.trim() || !form.adminUsername.trim()) {
    createError.value = '请填写特检院名称和院管理员用户名。'
    return
  }
  if (form.adminPassword && form.adminPassword.length < 6) {
    createError.value = '初始密码至少 6 位，或留空使用系统默认初始密码。'
    return
  }
  creating.value = true
  createError.value = ''
  try {
    await createInstituteApi(
      {
        code,
        name: form.name.trim(),
        adminUsername: form.adminUsername.trim(),
        adminName: form.adminName.trim() || undefined,
        adminPassword: form.adminPassword || undefined
      },
      { idempotencyKey: createKey }
    )
    ElMessage.success('已开通。院管理员用这个用户名直接登录，首次登录须修改密码。')
    createOpen.value = false
    await load()
  } catch (error) {
    createError.value = getAicheckErrorMessage(error, '开通失败，请稍后重试。')
  } finally {
    creating.value = false
  }
}

const toggleStatus = async (item: Institute) => {
  const disabling = item.status === 'active'
  if (disabling) {
    try {
      await ElMessageBox.confirm(
        `停用后「${item.name}」的所有人立即无法登录，数据保留，随时可以重新启用。`,
        '停用特检院',
        { confirmButtonText: '停用', cancelButtonText: '取消', type: 'warning' }
      )
    } catch {
      return
    }
  }
  try {
    await setInstituteStatusApi(item.id, disabling ? 'disabled' : 'active', {
      idempotencyKey: `institute-status-${item.id}-${Date.now()}`
    })
    ElMessage.success(disabling ? '已停用' : '已启用')
    await load()
  } catch (error) {
    ElMessage.error(getAicheckErrorMessage(error, '操作失败，请稍后重试。'))
  }
}

/* 平台改了通用规则（业务规则与流程）后，各院要同步一次才用上；各院自己的项目规则不动 */
const syncing = ref(false)
const syncRules = async () => {
  syncing.value = true
  try {
    const res = await syncPlatformRulesApi({ idempotencyKey: `institute-sync-rules-${Date.now()}` })
    const results = Object.values(res.data?.results || {})
    const synced = results.reduce((sum, item) => sum + item.synced, 0)
    const removed = results.reduce((sum, item) => sum + item.removed, 0)
    ElMessage.success(`已同步到 ${results.length} 家特检院：更新 ${synced} 条，移除 ${removed} 条`)
  } catch (error) {
    ElMessage.error(getAicheckErrorMessage(error, '同步失败，请稍后重试。'))
  } finally {
    syncing.value = false
  }
}

/* 院管理员：再加一个，或者忘了密码时重置（下次登录必须先改，已登录的会话立即失效） */
const adminDialog = ref<'add' | 'reset' | null>(null)
const adminTarget = ref<Institute | null>(null)
const adminSaving = ref(false)
const adminError = ref('')
const adminForm = reactive({ username: '', name: '', password: '' })
let adminKey = ''

const openAdminDialog = (mode: 'add' | 'reset', item: Institute) => {
  adminDialog.value = mode
  adminTarget.value = item
  Object.assign(adminForm, {
    username: mode === 'reset' ? item.adminUsernames[0] || '' : '',
    name: '',
    password: ''
  })
  adminError.value = ''
  adminKey = `institute-admin-${mode}-${item.id}-${Date.now()}`
}

const submitAdminDialog = async () => {
  const target = adminTarget.value
  if (!target || !adminDialog.value) return
  if (!adminForm.username.trim()) {
    adminError.value = adminDialog.value === 'add' ? '请填写院管理员用户名。' : '请选择院管理员。'
    return
  }
  if (adminForm.password && adminForm.password.length < 6) {
    adminError.value = '密码至少 6 位，或留空使用系统默认初始密码。'
    return
  }
  adminSaving.value = true
  adminError.value = ''
  try {
    if (adminDialog.value === 'add') {
      await addInstituteAdminApi(
        target.id,
        {
          username: adminForm.username.trim(),
          name: adminForm.name.trim() || undefined,
          password: adminForm.password || undefined
        },
        { idempotencyKey: adminKey }
      )
      ElMessage.success('已新增院管理员，首次登录须修改密码。')
    } else {
      await resetInstituteAdminPasswordApi(
        target.id,
        adminForm.username,
        { password: adminForm.password || undefined },
        { idempotencyKey: adminKey }
      )
      ElMessage.success('已重置。该管理员已登录的会话已失效，下次登录须修改密码。')
    }
    adminDialog.value = null
    await load()
  } catch (error) {
    adminError.value = getAicheckErrorMessage(error, '操作失败，请稍后重试。')
  } finally {
    adminSaving.value = false
  }
}

const rightCards = computed(() => [
  {
    title: '开通流程',
    rows: [
      { label: '已开通', value: String(items.value.length) },
      { label: '启用中', value: String(activeCount.value) }
    ],
    note: '开通时建好院管理员并带上平台的通用规则；院管理员登录后在本院建用户、发项目邀请。用户名全平台唯一，登录不用选单位。标准库和通用规则由平台维护，改了之后点「同步平台规则」。'
  }
])

onMounted(load)
</script>

<template>
  <StaticPageShell
    brand-mark="PL"
    title="特检院管理"
    :status="loadError ? '加载异常' : `${activeCount} 家启用中`"
    :status-tone="loadError ? 'red' : 'green'"
    search-placeholder="搜索后台功能"
    :user-label="userLabel"
    :top-stats="[]"
    :menu-title="ADMIN_MENU_TITLE"
    :menu-root="ADMIN_MENU_ROOT"
    :menu-sections="menuSections"
    :boundary-title="ADMIN_BOUNDARY_TITLE"
    :boundary-badge="ADMIN_BOUNDARY_BADGE"
    boundary-tone="green"
    :boundary-rows="[]"
    right-title="平台管理"
    :right-cards="rightCards"
    workspace-mode="wide"
    right-panel-mode="drawer"
    right-toggle-label="开通流程"
    right-collapsed-default
    boundary-collapsed-default
    search-scope="admin"
    task-area="admin"
  >
    <section class="institutes-page" aria-labelledby="institutes-heading">
      <ElCard shadow="never">
        <div class="heading-row">
          <div>
            <h2 id="institutes-heading">特检院管理</h2>
            <p>给需要的特检院开通账号空间并指定院管理员，各院的项目、用户和资料互相隔离。</p>
          </div>
          <div v-if="platformAdmin" class="heading-actions">
            <ElButton :loading="syncing" @click="syncRules">同步平台规则</ElButton>
            <ElButton type="primary" @click="openCreate">开通特检院</ElButton>
          </div>
        </div>
        <ElAlert
          v-if="!platformAdmin"
          type="warning"
          :closable="false"
          title="只有平台管理员可以管理特检院。各特检院的管理员请在「组织用户」里管理本院人员。"
        />
        <template v-else>
          <p v-if="loadError" class="error" role="alert">{{ loadError }}</p>
          <ElTable v-else v-loading="loading" :data="items" row-key="id">
            <template #empty><ElEmpty description="还没有开通特检院" /></template>
            <ElTableColumn label="特检院" min-width="200">
              <template #default="{ row }">
                <div>{{ row.name }}</div>
                <small class="muted">{{ row.code }} · {{ row.id }}</small>
              </template>
            </ElTableColumn>
            <ElTableColumn label="状态" width="100">
              <template #default="{ row }">
                <ElTag size="small" :type="row.status === 'active' ? 'success' : 'info'">
                  {{ row.status === 'active' ? '启用中' : '已停用' }}
                </ElTag>
              </template>
            </ElTableColumn>
            <ElTableColumn label="院管理员" min-width="160">
              <template #default="{ row }">{{ row.adminUsernames.join('、') || '—' }}</template>
            </ElTableColumn>
            <ElTableColumn label="用户" prop="userCount" width="80" />
            <ElTableColumn label="项目" prop="projectCount" width="80" />
            <ElTableColumn label="开通时间" width="170">
              <template #default="{ row }">{{ row.builtin ? '平台自带' : row.createdAt }}</template>
            </ElTableColumn>
            <ElTableColumn label="操作" width="210" fixed="right">
              <template #default="{ row }">
                <template v-if="!row.builtin">
                  <ElButton link type="primary" @click="openAdminDialog('add', row)"
                    >加管理员</ElButton
                  >
                  <ElButton
                    link
                    type="primary"
                    :disabled="!row.adminUsernames.length"
                    @click="openAdminDialog('reset', row)"
                    >重置密码</ElButton
                  >
                </template>
                <ElButton
                  v-if="!row.builtin"
                  link
                  :type="row.status === 'active' ? 'danger' : 'primary'"
                  @click="toggleStatus(row)"
                >
                  {{ row.status === 'active' ? '停用' : '启用' }}
                </ElButton>
              </template>
            </ElTableColumn>
          </ElTable>
        </template>
      </ElCard>
    </section>

    <ElDialog
      v-model="createOpen"
      title="开通特检院"
      width="min(520px, calc(100vw - 32px))"
      append-to-body
    >
      <ElForm label-position="top" @submit.prevent>
        <ElFormItem label="特检院名称">
          <ElInput v-model="form.name" maxlength="80" placeholder="例如 广东省特种设备检测研究院" />
        </ElFormItem>
        <ElFormItem label="单位代码">
          <ElInput
            v-model="form.code"
            maxlength="32"
            placeholder="2–32 位大写字母、数字或连字符，例如 GDTJ，开通后不能改"
          />
        </ElFormItem>
        <ElFormItem label="院管理员用户名">
          <ElInput
            v-model="form.adminUsername"
            maxlength="64"
            placeholder="全平台唯一，院管理员用它直接登录"
          />
        </ElFormItem>
        <ElFormItem label="院管理员姓名（选填）">
          <ElInput v-model="form.adminName" maxlength="40" />
        </ElFormItem>
        <ElFormItem label="初始密码（选填）">
          <ElInput
            v-model="form.adminPassword"
            show-password
            autocomplete="new-password"
            placeholder="至少 6 位；留空使用系统默认初始密码。首次登录都须修改"
          />
        </ElFormItem>
      </ElForm>
      <p v-if="createError" class="error" role="alert">{{ createError }}</p>
      <template #footer>
        <ElButton @click="createOpen = false">取消</ElButton>
        <ElButton type="primary" :loading="creating" @click="submitCreate">开通</ElButton>
      </template>
    </ElDialog>

    <ElDialog
      :model-value="adminDialog !== null"
      :title="adminDialog === 'add' ? '新增院管理员' : '重置院管理员密码'"
      width="min(460px, calc(100vw - 32px))"
      append-to-body
      @update:model-value="(open: boolean) => !open && (adminDialog = null)"
    >
      <p v-if="adminTarget" class="muted">{{ adminTarget.name }}</p>
      <ElForm label-position="top" @submit.prevent>
        <ElFormItem v-if="adminDialog === 'add'" label="用户名">
          <ElInput
            v-model="adminForm.username"
            maxlength="64"
            placeholder="全平台唯一，用它直接登录"
          />
        </ElFormItem>
        <ElFormItem v-if="adminDialog === 'add'" label="姓名（选填）">
          <ElInput v-model="adminForm.name" maxlength="40" />
        </ElFormItem>
        <ElFormItem v-if="adminDialog === 'reset'" label="院管理员">
          <ElSelect v-model="adminForm.username" style="width: 100%">
            <ElOption
              v-for="name in adminTarget?.adminUsernames || []"
              :key="name"
              :label="name"
              :value="name"
            />
          </ElSelect>
        </ElFormItem>
        <ElFormItem :label="adminDialog === 'add' ? '初始密码（选填）' : '新密码（选填）'">
          <ElInput
            v-model="adminForm.password"
            show-password
            autocomplete="new-password"
            placeholder="至少 6 位；留空使用系统默认初始密码。下次登录须修改"
          />
        </ElFormItem>
      </ElForm>
      <p v-if="adminError" class="error" role="alert">{{ adminError }}</p>
      <template #footer>
        <ElButton @click="adminDialog = null">取消</ElButton>
        <ElButton type="primary" :loading="adminSaving" @click="submitAdminDialog">
          {{ adminDialog === 'add' ? '新增' : '重置' }}
        </ElButton>
      </template>
    </ElDialog>
  </StaticPageShell>
</template>

<style scoped>
.institutes-page {
  display: grid;
  gap: 16px;
}

.heading-row {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}

.heading-actions {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}

.heading-row h2 {
  margin: 0 0 4px;
  font-size: 18px;
}

.heading-row p,
.muted {
  margin: 0;
  color: var(--el-text-color-secondary);
}

.error {
  margin: 0 0 12px;
  font-size: 13px;
  color: var(--el-color-danger);
}
</style>
