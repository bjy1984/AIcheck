<script setup lang="ts">
/* 改进任务（平台管理员）：各院送上来的意见反馈在这里审批、合并、交 AI 修复，修好上线后关闭。
 * 方案见「意见反馈审批与 AI 修复方案」。AI 通过 aicheck-feedback skill 领取「待开发」的任务。 */
import { computed, onMounted, reactive, ref } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElDrawer,
  ElEmpty,
  ElInput,
  ElMessage,
  ElMessageBox,
  ElOption,
  ElRadioButton,
  ElRadioGroup,
  ElSelect,
  ElTable,
  ElTableColumn,
  ElTag
} from 'element-plus'
import StaticPageShell from './components/StaticPageShell.vue'
import {
  approveImprovementTaskApi,
  declineImprovementTaskApi,
  getImprovementTasksApi,
  mergeImprovementTaskApi,
  setImprovementTaskStatusApi
} from '@/api/aicheck'
import {
  IMPROVEMENT_TASK_TABS,
  type ImprovementTask,
  type ImprovementTaskPriority,
  type ImprovementTaskScope,
  type ImprovementTaskStatus
} from '@/api/aicheck/improvementTasks'
import { USER_FEEDBACK_CATEGORIES } from '@/api/aicheck/userFeedback'
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
  admin: '管理员'
}
const PRIORITY_OPTIONS: Array<{ value: ImprovementTaskPriority; label: string }> = [
  { value: 'P1', label: 'P1 高' },
  { value: 'P2', label: 'P2 中' },
  { value: 'P3', label: 'P3 低' }
]
const SCOPE_OPTIONS: Array<{ value: ImprovementTaskScope; label: string }> = [
  { value: 'public', label: '公共改进' },
  { value: 'gray', label: '各院口径不一' }
]

const userStore = useUserStoreWithOut()
const platformAdmin = computed(() => Boolean(userStore.getUserInfo?.platformAdmin))
const userLabel = computed(
  () => userStore.getUserInfo?.displayName || userStore.getUserInfo?.username || '平台管理员'
)
const menuSections = computed(() =>
  buildAdminMenuSections('/admin/improvement-tasks', { platformAdmin: platformAdmin.value })
)

const statusFilter = ref<ImprovementTaskStatus | ''>('pending_review')
const items = ref<ImprovementTask[]>([])
const allItems = ref<ImprovementTask[]>([])
const statusCounts = ref<Partial<Record<ImprovementTaskStatus, number>>>({})
const loading = ref(false)
const loadError = ref('')

const load = async () => {
  if (!platformAdmin.value) return
  loading.value = true
  loadError.value = ''
  try {
    const res = await getImprovementTasksApi()
    allItems.value = res.data?.items || []
    statusCounts.value = res.data?.statusCounts || {}
    items.value = statusFilter.value
      ? allItems.value.filter((item) => item.status === statusFilter.value)
      : allItems.value.filter((item) => item.status !== 'merged')
    if (active.value)
      active.value = allItems.value.find((item) => item.id === active.value?.id) || null
  } catch (error) {
    loadError.value = getAicheckErrorMessage(error, '改进任务加载失败，请稍后重试。')
  } finally {
    loading.value = false
  }
}

const tabLabel = (value: ImprovementTaskStatus | '', label: string) => {
  if (!value) {
    const total = allItems.value.filter((item) => item.status !== 'merged').length
    return `${label} ${total}`
  }
  return `${label} ${statusCounts.value[value] || 0}`
}

const statusTagType = (status: ImprovementTaskStatus) =>
  (
    ({
      pending_review: 'warning',
      approved: 'primary',
      claimed: 'primary',
      in_review: 'warning',
      deployed: 'success',
      closed: 'info',
      declined: 'danger',
      merged: 'info'
    }) as const
  )[status]

const categoryLabel = (value: string) =>
  USER_FEEDBACK_CATEGORIES.find((item) => item.value === value)?.label || '其他'

const contextText = (context: Record<string, string>) => {
  const parts = [context?.pageTitle || context?.page]
  if (context?.projectId) parts.push(`工程 ${context.projectId}`)
  if (context?.nodeId) parts.push(`节点 ${context.nodeId}`)
  return parts.filter(Boolean).join(' · ')
}

/* 处理抽屉 */
const active = ref<ImprovementTask | null>(null)
const drawerOpen = ref(false)
const saving = ref(false)
const actionError = ref('')
const form = reactive<{
  title: string
  taskStatement: string
  acceptanceCriteria: string
  priority: ImprovementTaskPriority
  scope: ImprovementTaskScope
  mergeInto: string
}>({
  title: '',
  taskStatement: '',
  acceptanceCriteria: '',
  priority: 'P2',
  scope: 'public',
  mergeInto: ''
})

const editable = computed(
  () => !!active.value && ['pending_review', 'approved'].includes(active.value.status)
)
const mergeTargets = computed(() =>
  allItems.value.filter(
    (item) =>
      item.id !== active.value?.id &&
      ['pending_review', 'approved', 'claimed'].includes(item.status)
  )
)

const openTask = (item: ImprovementTask) => {
  active.value = item
  form.title = item.title || ''
  form.taskStatement = item.taskStatement || ''
  form.acceptanceCriteria = item.acceptanceCriteria || ''
  form.priority = item.priority || 'P2'
  form.scope = item.scope || 'public'
  form.mergeInto = ''
  actionError.value = ''
  drawerOpen.value = true
}

const run = async (work: () => Promise<unknown>, success: string) => {
  saving.value = true
  actionError.value = ''
  try {
    await work()
    ElMessage.success(success)
    await load()
  } catch (error) {
    actionError.value = getAicheckErrorMessage(error, '操作失败，请稍后重试。')
  } finally {
    saving.value = false
  }
}

const key = (verb: string) => `improvement-${verb}-${active.value?.id}-${Date.now()}`

const approve = () => {
  if (!active.value) return
  if (!form.title.trim() || !form.taskStatement.trim() || !form.acceptanceCriteria.trim()) {
    actionError.value = '请写标题、任务描述和验收标准：AI 只按这几段干活，不按用户原话。'
    return
  }
  const taskId = active.value.id
  return run(
    () =>
      approveImprovementTaskApi(
        taskId,
        {
          title: form.title.trim(),
          taskStatement: form.taskStatement.trim(),
          acceptanceCriteria: form.acceptanceCriteria.trim(),
          priority: form.priority,
          scope: form.scope
        },
        { idempotencyKey: key('approve') }
      ),
    active.value.status === 'approved' ? '任务描述已更新' : '已审批，进入待开发'
  )
}

const askNote = async (title: string, message: string, placeholder: string) => {
  try {
    const { value } = await ElMessageBox.prompt(message, title, {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      inputType: 'textarea',
      inputPlaceholder: placeholder,
      inputValidator: (input: string) => Boolean(String(input || '').trim()) || '请填写'
    })
    return String(value || '').trim()
  } catch {
    return ''
  }
}

const decline = async () => {
  if (!active.value) return
  const taskId = active.value.id
  const reason = await askNote(
    '暂不采纳',
    '理由会回复给提交这条反馈的所有人。',
    '例如：这是院级配置，在报告模板里就能改'
  )
  if (reason)
    await run(
      () => declineImprovementTaskApi(taskId, reason, { idempotencyKey: key('decline') }),
      '已暂不采纳，并回复了提交人'
    )
}

const merge = () => {
  if (!active.value || !form.mergeInto) return
  const taskId = active.value.id
  const into = form.mergeInto
  return run(
    () => mergeImprovementTaskApi(taskId, into, { idempotencyKey: key('merge') }),
    '已合并：来源反馈都挂到目标任务上'
  ).then(() => {
    // 合并失败时留在抽屉里显示错误（2026-11-04 审计）
    if (!actionError.value) drawerOpen.value = false
  })
}

const setStatus = async (status: 'deployed' | 'closed' | 'approved') => {
  if (!active.value) return
  const taskId = active.value.id
  let note = ''
  if (status === 'approved') {
    note = await askNote(
      '重新打开',
      '写清楚哪里不对，AI 会照着重修。',
      '例如：PR 改错了规则；上线后 R24 仍判证据不足'
    )
    if (!note) return
  }
  const labels = {
    deployed: '已标为已上线',
    closed: '已关闭，提交人会收到回复',
    approved: '已重新打开，回到待开发'
  }
  await run(
    () =>
      setImprovementTaskStatusApi(taskId, status, note || undefined, {
        idempotencyKey: key(status)
      }),
    labels[status]
  )
}

const rightCards = computed(() => [
  {
    title: '处理流程',
    rows: [
      { label: '待平台审批', value: '写任务描述和验收标准，或不采纳、合并' },
      { label: '待开发', value: 'AI 用 aicheck-feedback skill 领取' },
      { label: '待审核合并', value: '审 PR；合并部署后标「已上线」' },
      { label: '已上线', value: '确认解决后关闭，提交人收到回复' }
    ],
    note: '判断归属：改给所有院都不会变差 → 公共改进；院和院要求不同 → 院级配置，不改代码。'
  }
])

onMounted(load)
</script>

<template>
  <StaticPageShell
    brand-mark="PL"
    title="改进任务"
    :status="loadError ? '加载异常' : `${statusCounts.pending_review || 0} 条待审批`"
    :status-tone="loadError ? 'red' : statusCounts.pending_review ? 'orange' : 'green'"
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
    right-toggle-label="处理流程"
    right-collapsed-default
    boundary-collapsed-default
    search-scope="admin"
    task-area="admin"
  >
    <section class="tasks-page" aria-labelledby="tasks-heading">
      <ElCard shadow="never">
        <div class="heading-row">
          <div>
            <h2 id="tasks-heading">改进任务</h2>
            <p>各院送平台审批的意见反馈。审批后交 AI 修复，人审核合并、部署后关闭。</p>
          </div>
          <ElButton :loading="loading" :disabled="!platformAdmin" @click="load">刷新</ElButton>
        </div>
        <ElAlert
          v-if="!platformAdmin"
          type="warning"
          :closable="false"
          title="只有平台管理员可以处理改进任务。各特检院的管理员请在「意见反馈」里把问题送平台。"
        />
        <template v-else>
          <div class="filters" aria-label="任务筛选">
            <ElRadioGroup v-model="statusFilter" size="small" @change="load">
              <ElRadioButton
                v-for="tab in IMPROVEMENT_TASK_TABS"
                :key="tab.value"
                :value="tab.value"
              >
                {{ tabLabel(tab.value, tab.label) }}
              </ElRadioButton>
            </ElRadioGroup>
          </div>
          <p v-if="loadError" class="error" role="alert">{{ loadError }}</p>
          <ElTable v-else v-loading="loading" :data="items" row-key="id" class="tasks-table">
            <template #empty>
              <ElEmpty description="这里还没有任务" />
            </template>
            <ElTableColumn label="优先级" width="80">
              <template #default="{ row }">
                <ElTag
                  size="small"
                  :type="row.priority === 'P1' ? 'danger' : 'info'"
                  effect="plain"
                  >{{ row.priority }}</ElTag
                >
              </template>
            </ElTableColumn>
            <ElTableColumn label="状态" width="110">
              <template #default="{ row }">
                <ElTag size="small" :type="statusTagType(row.status)">{{ row.statusLabel }}</ElTag>
              </template>
            </ElTableColumn>
            <ElTableColumn label="任务" min-width="300">
              <template #default="{ row }">
                <p class="cell-title">
                  {{ row.title || row.sources?.[0]?.contentRedacted?.slice(0, 40) || '（未命名）' }}
                </p>
                <small class="muted">{{ row.scopeLabel }}</small>
              </template>
            </ElTableColumn>
            <ElTableColumn label="来源" min-width="180">
              <template #default="{ row }">
                <div>{{ row.sourceInstitutes.join('、') }}</div>
                <small class="muted">{{ row.sourceCount }} 条反馈</small>
              </template>
            </ElTableColumn>
            <ElTableColumn label="更新时间" prop="updatedAt" width="160" />
            <ElTableColumn label="操作" width="80" fixed="right">
              <template #default="{ row }">
                <ElButton link type="primary" @click="openTask(row)">处理</ElButton>
              </template>
            </ElTableColumn>
          </ElTable>
        </template>
      </ElCard>
    </section>

    <ElDrawer
      v-model="drawerOpen"
      :title="active?.title || '改进任务'"
      size="min(640px, 100vw)"
      append-to-body
    >
      <template v-if="active">
        <div class="drawer-status">
          <ElTag :type="statusTagType(active.status)">{{ active.statusLabel }}</ElTag>
          <span class="muted">{{ active.id }} · {{ active.sourceInstitutes.join('、') }}</span>
        </div>

        <h3 class="block-title">反馈原文（已脱敏，{{ active.sourceCount }} 条）</h3>
        <ul class="sources">
          <li v-for="src in active.sources" :key="`${src.sourceTenantId}-${src.feedbackId}`">
            <p class="source-content">{{ src.contentRedacted }}</p>
            <small class="muted"
              >{{ categoryLabel(src.category) }} ·
              {{ ROLE_LABELS[src.submittedRole] || src.submittedRole }} · {{ src.submittedAt
              }}<template v-if="contextText(src.context)">
                · {{ contextText(src.context) }}</template
              ></small
            >
            <small v-if="src.escalationNote" class="source-note"
              >院管理员说明：{{ src.escalationNote }}</small
            >
          </li>
        </ul>

        <template v-if="editable">
          <h3 class="block-title">任务描述（AI 按这里干活）</h3>
          <div class="field">
            <span class="field-label">标题</span>
            <ElInput
              v-model="form.title"
              maxlength="80"
              placeholder="会显示给提交人；不要写工程名、人名"
              aria-label="标题"
            />
          </div>
          <div class="field">
            <span class="field-label">任务描述</span>
            <ElInput
              v-model="form.taskStatement"
              type="textarea"
              :rows="4"
              maxlength="2000"
              placeholder="要改什么、改在哪一层（平台代码 / 业务包规则 / 院级配置）"
              aria-label="任务描述"
            />
          </div>
          <div class="field">
            <span class="field-label">验收标准</span>
            <ElInput
              v-model="form.acceptanceCriteria"
              type="textarea"
              :rows="3"
              maxlength="2000"
              placeholder="怎样算修好；审计准确性改动写上评测不低于基线"
              aria-label="验收标准"
            />
          </div>
          <div class="field-row">
            <div class="field">
              <span class="field-label">优先级</span>
              <ElSelect v-model="form.priority" size="small" class="small-select">
                <ElOption
                  v-for="item in PRIORITY_OPTIONS"
                  :key="item.value"
                  :label="item.label"
                  :value="item.value"
                />
              </ElSelect>
            </div>
            <div class="field">
              <span class="field-label">归属</span>
              <ElSelect v-model="form.scope" size="small" class="small-select">
                <ElOption
                  v-for="item in SCOPE_OPTIONS"
                  :key="item.value"
                  :label="item.label"
                  :value="item.value"
                />
              </ElSelect>
            </div>
          </div>
          <div class="actions">
            <ElButton type="primary" :loading="saving" @click="approve">{{
              active.status === 'approved' ? '保存任务描述' : '审批通过'
            }}</ElButton>
            <ElButton :disabled="saving" @click="decline">暂不采纳</ElButton>
          </div>
          <div v-if="mergeTargets.length" class="field merge-row">
            <span class="field-label">和别的任务是同一件事？合并过去</span>
            <div class="merge-controls">
              <ElSelect
                v-model="form.mergeInto"
                size="small"
                placeholder="选择目标任务"
                class="merge-select"
              >
                <ElOption
                  v-for="item in mergeTargets"
                  :key="item.id"
                  :label="`${item.title || item.id}（${item.statusLabel}）`"
                  :value="item.id"
                />
              </ElSelect>
              <ElButton size="small" :disabled="!form.mergeInto || saving" @click="merge"
                >合并</ElButton
              >
            </div>
          </div>
        </template>

        <template v-else>
          <h3 class="block-title">任务描述</h3>
          <p class="statement">{{ active.taskStatement || '—' }}</p>
          <h3 class="block-title">验收标准</h3>
          <p class="statement">{{ active.acceptanceCriteria || '—' }}</p>
        </template>

        <template v-if="active.claim">
          <h3 class="block-title">开发中</h3>
          <p class="statement">
            {{ active.claim.agent }}（{{ active.claim.by }}）{{ active.claim.at }} 领取，{{
              active.claim.expiresAt
            }}
            前没回报自动释放。
          </p>
        </template>

        <template v-if="active.result">
          <h3 class="block-title">AI 回报</h3>
          <p class="statement">
            PR：<a
              v-if="/^https?:\/\//.test(active.result.prUrl)"
              :href="active.result.prUrl"
              target="_blank"
              rel="noopener noreferrer"
              >{{ active.result.prUrl }}</a
            ><span v-else>{{ active.result.prUrl }}</span>
          </p>
          <p class="statement">测试：{{ active.result.tests }}</p>
          <p v-if="active.result.note" class="statement">说明：{{ active.result.note }}</p>
        </template>

        <div class="actions">
          <ElButton
            v-if="active.status === 'in_review'"
            type="primary"
            :loading="saving"
            @click="setStatus('deployed')"
            >已合并部署，标为已上线</ElButton
          >
          <ElButton
            v-if="active.status === 'deployed'"
            type="primary"
            :loading="saving"
            @click="setStatus('closed')"
            >确认解决，关闭</ElButton
          >
          <ElButton
            v-if="['in_review', 'deployed', 'closed'].includes(active.status)"
            :disabled="saving"
            @click="setStatus('approved')"
            >没解决，重新打开</ElButton
          >
        </div>
        <p v-if="actionError" class="error" role="alert">{{ actionError }}</p>

        <h3 class="block-title">记录</h3>
        <ol class="history">
          <li v-for="(entry, index) in [...(active.history || [])].reverse()" :key="index">
            <span>{{ entry.at }} · {{ entry.by }} · {{ entry.action }}</span>
            <small v-if="entry.note" class="muted">{{ entry.note }}</small>
          </li>
        </ol>
      </template>
    </ElDrawer>
  </StaticPageShell>
</template>

<style scoped>
.tasks-page {
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
  margin-bottom: 12px;
}

.filters :deep(.el-radio-group) {
  flex-wrap: wrap;
  row-gap: 6px;
}

.cell-title {
  margin: 0 0 2px;
  font-weight: 600;
}

.drawer-status {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-bottom: 16px;
}

.block-title {
  margin: 18px 0 8px;
  font-size: 14px;
}

.sources {
  display: grid;
  gap: 8px;
  padding: 0;
  margin: 0;
  list-style: none;
}

.sources li {
  display: grid;
  gap: 4px;
  padding: 10px 12px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
}

.source-content,
.statement {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
}

.statement + .statement {
  margin-top: 4px;
}

.source-note {
  color: var(--el-color-primary);
}

.field {
  display: grid;
  gap: 6px;
  margin-bottom: 12px;
}

.field-row {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
}

.field-label {
  font-size: 13px;
  font-weight: 600;
}

.small-select {
  width: 160px;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 12px 0;
}

.actions:empty {
  display: none;
}

.merge-row {
  padding-top: 12px;
  margin-top: 8px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.merge-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.merge-select {
  width: min(360px, 100%);
}

.history {
  display: grid;
  gap: 6px;
  padding-left: 18px;
  margin: 0;
  font-size: 12px;
}

.history li {
  display: grid;
  gap: 2px;
}

.error {
  margin: 0 0 12px;
  font-size: 13px;
  color: var(--el-color-danger);
}
</style>
