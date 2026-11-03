<script setup lang="ts">
/* 管理员看各角色提的意见反馈：按状态、类型、角色筛，逐条回复并改状态。
 * 回复会出现在提交人「意见反馈 → 我的反馈」里。 */
import { computed, onMounted, reactive, ref } from 'vue'
import {
  ElButton,
  ElCard,
  ElDialog,
  ElEmpty,
  ElInput,
  ElMessage,
  ElOption,
  ElRadioButton,
  ElRadioGroup,
  ElSelect,
  ElTable,
  ElTableColumn,
  ElTag
} from 'element-plus'
import StaticPageShell from './components/StaticPageShell.vue'
import { getAdminUserFeedbackApi, replyUserFeedbackApi } from '@/api/aicheck'
import {
  USER_FEEDBACK_CATEGORIES,
  USER_FEEDBACK_STATUSES,
  type UserFeedback,
  type UserFeedbackCategory,
  type UserFeedbackStatus
} from '@/api/aicheck/userFeedback'
import { useUserStoreWithOut } from '@/store/modules/user'
import { getAicheckErrorMessage } from '@/utils/aicheckError'
import {
  ADMIN_BOUNDARY_BADGE,
  ADMIN_BOUNDARY_TITLE,
  ADMIN_MENU_ROOT,
  ADMIN_MENU_TITLE,
  buildAdminMenuSections
} from './adminMenuTree'

const ROLE_LABELS: Record<string, string> = {
  inspection: '监检人员',
  contractor: '施工方',
  ndt: '无损检测',
  owner: '建设方',
  admin: '系统管理员'
}

const userStore = useUserStoreWithOut()
const userLabel = computed(
  () => userStore.getUserInfo?.displayName || userStore.getUserInfo?.username || '系统管理员'
)
const menuSections = computed(() =>
  buildAdminMenuSections('/admin/feedback', {
    platformAdmin: Boolean(userStore.getUserInfo?.platformAdmin)
  })
)

const filters = reactive<{
  status: UserFeedbackStatus | ''
  category: UserFeedbackCategory | ''
  role: string
}>({
  status: 'open',
  category: '',
  role: ''
})
const items = ref<UserFeedback[]>([])
const statusCounts = ref<Partial<Record<UserFeedbackStatus, number>>>({})
const loading = ref(false)
const loadError = ref('')

const load = async () => {
  loading.value = true
  loadError.value = ''
  try {
    const res = await getAdminUserFeedbackApi(filters)
    items.value = res.data?.items || []
    statusCounts.value = res.data?.statusCounts || {}
  } catch (error) {
    loadError.value = getAicheckErrorMessage(error, '意见反馈加载失败，请稍后重试。')
  } finally {
    loading.value = false
  }
}

const statusTabLabel = (status: UserFeedbackStatus | '', label: string) => {
  if (!status) {
    const total = Object.values(statusCounts.value).reduce((sum, value) => sum + (value || 0), 0)
    return `${label} ${total}`
  }
  return `${label} ${statusCounts.value[status] || 0}`
}

const statusTagType = (status: string) =>
  ({ open: 'info', acknowledged: 'warning', resolved: 'success', declined: 'danger' })[status] as
    | 'info'
    | 'warning'
    | 'success'
    | 'danger'

const contextText = (item: UserFeedback) => {
  const parts = [item.context?.pageTitle || item.context?.page]
  if (item.context?.projectId) parts.push(`工程 ${item.context.projectId}`)
  if (item.context?.nodeId) parts.push(`节点 ${item.context.nodeId}`)
  return parts.filter(Boolean).join(' · ') || '—'
}

/* 回复弹窗 */
const replyOpen = ref(false)
const replying = ref(false)
const replyError = ref('')
const replyTarget = ref<UserFeedback | null>(null)
const replyForm = reactive<{ status: UserFeedbackStatus; reply: string }>({
  status: 'acknowledged',
  reply: ''
})
let replyKey = ''

const openReply = (item: UserFeedback) => {
  replyTarget.value = item
  replyForm.status = item.status === 'open' ? 'acknowledged' : item.status
  replyForm.reply = item.reply?.content || ''
  replyError.value = ''
  replyKey = `user-feedback-reply-${item.id}-${Date.now()}`
  replyOpen.value = true
}

const submitReply = async () => {
  if (!replyTarget.value) return
  if (['resolved', 'declined'].includes(replyForm.status) && !replyForm.reply.trim()) {
    replyError.value = '标为已解决或暂不采纳时，请写一句回复给提交人。'
    return
  }
  replying.value = true
  replyError.value = ''
  try {
    await replyUserFeedbackApi(
      replyTarget.value.id,
      { status: replyForm.status, reply: replyForm.reply.trim() || undefined },
      { idempotencyKey: replyKey }
    )
    ElMessage.success('已保存，提交人可以看到这条回复。')
    replyOpen.value = false
    await load()
  } catch (error) {
    replyError.value = getAicheckErrorMessage(error, '保存失败，请稍后重试。')
  } finally {
    replying.value = false
  }
}

const rightCards = computed(() => [
  {
    title: '处理说明',
    rows: USER_FEEDBACK_STATUSES.map((item) => ({
      label: item.label,
      value: String(statusCounts.value[item.value] || 0)
    })),
    note: '「已解决」「暂不采纳」要写回复；回复会出现在提交人的「我的反馈」里。'
  }
])

onMounted(load)
</script>

<template>
  <StaticPageShell
    brand-mark="FB"
    title="意见反馈"
    :status="loadError ? '加载异常' : `${statusCounts.open || 0} 条待处理`"
    :status-tone="loadError ? 'red' : statusCounts.open ? 'orange' : 'green'"
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
    right-title="反馈处理"
    :right-cards="rightCards"
    workspace-mode="wide"
    right-panel-mode="drawer"
    right-toggle-label="处理说明"
    right-collapsed-default
    boundary-collapsed-default
    search-scope="admin"
    task-area="admin"
  >
    <section class="feedback-page" aria-labelledby="feedback-heading">
      <ElCard shadow="never">
        <div class="heading-row">
          <div>
            <h2 id="feedback-heading">意见反馈</h2>
            <p>各角色在使用中提交的不便、审计不准确和功能问题，逐条回复后提交人能看到。</p>
          </div>
          <ElButton :loading="loading" @click="load">刷新</ElButton>
        </div>
        <div class="filters" aria-label="反馈筛选">
          <ElRadioGroup v-model="filters.status" size="small" @change="load">
            <ElRadioButton value="">{{ statusTabLabel('', '全部') }}</ElRadioButton>
            <ElRadioButton
              v-for="item in USER_FEEDBACK_STATUSES"
              :key="item.value"
              :value="item.value"
            >
              {{ statusTabLabel(item.value, item.label) }}
            </ElRadioButton>
          </ElRadioGroup>
          <ElSelect
            v-model="filters.category"
            clearable
            placeholder="全部类型"
            size="small"
            class="filter-select"
            @change="load"
          >
            <ElOption
              v-for="item in USER_FEEDBACK_CATEGORIES"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </ElSelect>
          <ElSelect
            v-model="filters.role"
            clearable
            placeholder="全部角色"
            size="small"
            class="filter-select"
            @change="load"
          >
            <ElOption
              v-for="(label, value) in ROLE_LABELS"
              :key="value"
              :label="label"
              :value="value"
            />
          </ElSelect>
        </div>
        <p v-if="loadError" class="error" role="alert">{{ loadError }}</p>
        <ElTable v-else v-loading="loading" :data="items" row-key="id" class="feedback-table">
          <template #empty>
            <ElEmpty
              :description="filters.status === 'open' ? '没有待处理的反馈' : '没有符合条件的反馈'"
            />
          </template>
          <ElTableColumn label="状态" width="100">
            <template #default="{ row }">
              <ElTag size="small" :type="statusTagType(row.status)">{{ row.statusLabel }}</ElTag>
            </template>
          </ElTableColumn>
          <ElTableColumn label="类型" prop="categoryLabel" width="110" />
          <ElTableColumn label="内容" min-width="320">
            <template #default="{ row }">
              <p class="cell-content">{{ row.content }}</p>
              <p v-if="row.reply" class="cell-reply">回复：{{ row.reply.content }}</p>
            </template>
          </ElTableColumn>
          <ElTableColumn label="提交人" width="160">
            <template #default="{ row }">
              <div>{{ row.submittedBy.name || row.submittedBy.username }}</div>
              <small class="muted">{{
                ROLE_LABELS[row.submittedBy.role] || row.submittedBy.role
              }}</small>
            </template>
          </ElTableColumn>
          <ElTableColumn label="发生在" min-width="180">
            <template #default="{ row }">
              <small class="muted">{{ contextText(row) }}</small>
            </template>
          </ElTableColumn>
          <ElTableColumn label="提交时间" prop="createdAt" width="160" />
          <ElTableColumn label="操作" width="90" fixed="right">
            <template #default="{ row }">
              <ElButton link type="primary" @click="openReply(row)">{{
                row.reply ? '改回复' : '回复'
              }}</ElButton>
            </template>
          </ElTableColumn>
        </ElTable>
      </ElCard>
    </section>

    <ElDialog
      v-model="replyOpen"
      title="回复意见反馈"
      width="min(520px, calc(100vw - 32px))"
      append-to-body
    >
      <template v-if="replyTarget">
        <p class="reply-quote">{{ replyTarget.content }}</p>
        <div class="field">
          <span class="field-label">处理状态</span>
          <ElRadioGroup v-model="replyForm.status" size="small">
            <ElRadioButton
              v-for="item in USER_FEEDBACK_STATUSES"
              :key="item.value"
              :value="item.value"
            >
              {{ item.label }}
            </ElRadioButton>
          </ElRadioGroup>
        </div>
        <div class="field">
          <span class="field-label">回复提交人</span>
          <ElInput
            v-model="replyForm.reply"
            type="textarea"
            :rows="4"
            maxlength="1000"
            show-word-limit
            aria-label="回复提交人"
          />
        </div>
        <p v-if="replyError" class="error" role="alert">{{ replyError }}</p>
      </template>
      <template #footer>
        <ElButton @click="replyOpen = false">取消</ElButton>
        <ElButton type="primary" :loading="replying" @click="submitReply">保存</ElButton>
      </template>
    </ElDialog>
  </StaticPageShell>
</template>

<style scoped>
.feedback-page {
  display: grid;
  gap: 16px;
}

.heading-row {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
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

.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 12px;
}

.filter-select {
  width: 140px;
}

.cell-content,
.cell-reply,
.reply-quote {
  margin: 0;
  white-space: pre-wrap;
}

.cell-reply {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-color-success-dark-2);
}

.reply-quote {
  padding: 8px 10px;
  margin-bottom: 14px;
  font-size: 13px;
  background: var(--el-fill-color-light);
  border-radius: 4px;
}

.field {
  display: grid;
  gap: 6px;
  margin-bottom: 14px;
}

/* 窄屏时类型 / 状态按钮换行，不被挤出弹窗 */
.field :deep(.el-radio-group) {
  flex-wrap: wrap;
  row-gap: 6px;
}

.field-label {
  font-size: 13px;
  font-weight: 600;
}

.error {
  margin: 0 0 12px;
  font-size: 13px;
  color: var(--el-color-danger);
}
</style>
