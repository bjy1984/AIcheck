<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElCol,
  ElEmpty,
  ElRow,
  ElSelect,
  ElOption,
  ElSpace,
  ElTable,
  ElTableColumn,
  ElTag
} from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import StatusTag from './components/StatusTag.vue'
import { getProjectReviewWorkbenchApi, listWorkbenchProjectsApi } from '@/api/aicheck'
import type { GenericReviewWorkbenchPayload } from '@/api/aicheck'
import type { Project, RoleCode } from '@/types/aicheck'
import { formatConfidence } from '@/utils/confidence'
import { friendlyReviewStatus } from './components/auditLabels'
import StaticPageShell from './components/StaticPageShell.vue'
import { useUserStore } from '@/store/modules/user'
import { getAicheckRoleLabel } from '@/utils/roleAccess'
import GenericFindingDetail from './components/GenericFindingDetail.vue'
import { findingReviewState, pendingFinding } from './workbenchTruth'
import { genericRoleContent } from './genericRoleContent'

const loading = ref(false)
const error = ref('')
const projects = ref<Project[]>([])
const selectedProjectId = ref('')
const workbench = ref<GenericReviewWorkbenchPayload | null>(null)
const userStore = useUserStore()
const roleContent = computed(() => genericRoleContent(userStore.getUserInfo?.role as RoleCode))
const operationArea = computed(() =>
  userStore.getUserInfo?.role === 'admin' ? 'admin' : 'workbench'
)
const genericUserLabel = computed(() => {
  const user = userStore.getUserInfo
  const name = user?.displayName || user?.username || '当前用户'
  const roleLabel = getAicheckRoleLabel(user?.role)
  return name === roleLabel ? name : `${name} · ${roleLabel}`
})

const genericProjects = computed(() =>
  projects.value.filter((project) => project.businessPackId !== 'engineering_inspection_v1')
)

const selectedProject = computed(() =>
  projects.value.find((project) => project.id === selectedProjectId.value)
)

const severityType = (severity?: string) => {
  if (severity === 'high') return 'danger'
  if (severity === 'medium') return 'warning'
  return 'info'
}

const severityLabel = (severity?: string) => {
  if (severity === 'high') return '高风险'
  if (severity === 'medium') return '中风险'
  if (severity === 'low') return '低风险'
  return severity || '-'
}

const selectedGenericView = ref('overview')
const findingFilter = ref<'all' | 'pending' | 'evidence'>('all')
const selectedFindingId = ref('')
const visibleFindings = computed(() =>
  (workbench.value?.findings || []).filter((finding) =>
    findingFilter.value === 'pending'
      ? pendingFinding(finding)
      : findingFilter.value === 'evidence'
        ? finding.evidenceLinkIds.length > 0
        : true
  )
)
const selectedFinding = computed(() =>
  visibleFindings.value.find((finding) => finding.id === selectedFindingId.value)
)
const businessPackName = computed(() => {
  const payload = workbench.value
  if (!payload) return '待加载'
  return payload.project.businessPackId &&
    payload.project.businessPackId !== payload.businessPack.id
    ? '业务类型信息待核对'
    : payload.businessPack.name
})
const showFindings = async (filter: typeof findingFilter.value) => {
  findingFilter.value = filter
  selectedGenericView.value = roleContent.value.reviewDetails
    ? filter === 'pending'
      ? 'human'
      : filter === 'evidence'
        ? 'evidence'
        : 'findings'
    : 'findings'
  await nextTick()
  document
    .getElementById('generic-findings')
    ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
const openFinding = async (id: string) => {
  selectedFindingId.value = id
  await nextTick()
  document
    .getElementById('generic-finding-detail')
    ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

const genericShellMenuSections = computed(() => [
  {
    title: selectedProject.value?.name || '资料审查项目',
    meta: workbench.value?.project.status || '待选择',
    items: roleContent.value.navigation.map((item) => ({
      ...item,
      index: item.subpage,
      active: selectedGenericView.value === item.subpage,
      badge: selectedGenericView.value === item.subpage ? '当前' : undefined,
      tone: 'blue' as const
    }))
  }
])

const workbenchRequest = { current: 0 }
const loadWorkbench = async () => {
  if (!selectedProjectId.value) return
  const projectId = selectedProjectId.value
  const generation = ++workbenchRequest.current
  const isCurrent = () =>
    generation === workbenchRequest.current && projectId === selectedProjectId.value
  loading.value = true
  error.value = ''
  workbench.value = null
  selectedFindingId.value = ''
  findingFilter.value = 'all'
  try {
    const res = await getProjectReviewWorkbenchApi(projectId)
    if (!isCurrent()) return
    if (!res) {
      error.value = '通用资料审查工作台加载失败。'
      return
    }
    workbench.value = res.data
  } catch {
    if (isCurrent()) error.value = '通用资料审查工作台加载失败，请重试。'
  } finally {
    if (isCurrent()) loading.value = false
  }
}

const handleGenericMenuSelect = (item: { subpage?: string; index: string }) => {
  const target = item.subpage || item.index
  if (target === 'human' || target === 'evidence' || target === 'findings') {
    void showFindings(target === 'human' ? 'pending' : target === 'evidence' ? 'evidence' : 'all')
    return
  }
  selectedGenericView.value = target
  const targetElement = document.getElementById(`generic-${target}`)
  targetElement?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

const loadData = async () => {
  loading.value = true
  error.value = ''
  try {
    const res = await listWorkbenchProjectsApi((userStore.getUserInfo?.role || 'admin') as RoleCode)
    if (!res) {
      error.value = '项目列表加载失败。'
      return
    }
    projects.value = res.data
    selectedProjectId.value = genericProjects.value[0]?.id || projects.value[0]?.id || ''
    await loadWorkbench()
  } catch {
    error.value = '通用资料审查工作台加载失败。'
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
</script>

<template>
  <div class="generic-workbench">
    <!-- 整页遮罩改为 shell 顶部细条：刷新期间页面仍可操作。 -->
    <StaticPageShell
      :refreshing="loading"
      brand-mark="审"
      title="通用资料审查工作台"
      :status="loading ? '加载中' : error ? '加载失败' : '资料审查'"
      status-tone="blue"
      search-placeholder="搜索业务类型、节点、资料、发现"
      :search-scope="operationArea"
      :task-area="operationArea"
      :project-id="selectedProjectId"
      :user-label="genericUserLabel"
      workspace-mode="wide"
      right-panel-mode="drawer"
      right-toggle-label="项目摘要"
      right-collapsed-default
      boundary-collapsed-default
      :top-stats="[]"
      menu-title="通用审查对象"
      menu-root="审查项目"
      :menu-sections="genericShellMenuSections"
      boundary-title=""
      boundary-badge=""
      boundary-tone="green"
      :boundary-rows="[]"
      right-title="项目摘要"
      right-subtitle="资料、规则与人工确认"
      :right-cards="[]"
      @menu-select="handleGenericMenuSelect"
    >
      <div class="page-title">
        <div>
          <h1>通用资料审查工作台</h1>
          <p>{{ roleContent.intro }}</p>
        </div>
        <StatusTag
          :status="error ? '加载失败' : loading ? '加载中' : workbench ? '已加载' : '未取得'"
          effect="plain"
        />
      </div>

      <ElAlert
        v-if="error"
        type="error"
        show-icon
        :closable="false"
        :title="error"
        class="mb-12px"
      />

      <ElRow :gutter="16">
        <ElCol :span="24">
          <ElCard id="generic-overview" shadow="never" class="panel">
            <template #header>
              <div class="panel-header">
                <span>当前项目</span>
                <ElSpace>
                  <ElSelect
                    v-model="selectedProjectId"
                    aria-label="选择审查项目"
                    filterable
                    style="width: min(320px, 100%)"
                    @change="loadWorkbench"
                  >
                    <ElOption
                      v-for="project in projects"
                      :key="project.id"
                      :label="project.name"
                      :value="project.id"
                    />
                  </ElSelect>
                  <ElButton
                    :icon="Refresh"
                    plain
                    type="primary"
                    :loading="loading"
                    @click="loadWorkbench"
                  >
                    刷新
                  </ElButton>
                </ElSpace>
              </div>
            </template>

            <div v-if="workbench" class="generic-summary">
              <span>业务类型：{{ businessPackName }}</span>
              <StatusTag :status="workbench.project.status" />
            </div>
            <ElEmpty v-else description="请选择业务类型项目" />
          </ElCard>
        </ElCol>
      </ElRow>

      <ElRow v-if="workbench" :gutter="16" class="mt-16px">
        <ElCol :span="24">
          <ElCard id="generic-requirements" shadow="never" class="panel">
            <template #header>
              <div class="panel-header">
                <span>节点与资料进度</span>
                <ElTag effect="plain">{{ workbench.nodes.length }} 个节点</ElTag>
              </div>
            </template>
            <ElTable :data="workbench.nodes" class="readable-table" empty-text="暂无节点模板">
              <ElTableColumn v-if="roleContent.reviewDetails" prop="code" label="编码" width="92" />
              <ElTableColumn prop="name" label="节点" min-width="220" />
              <ElTableColumn prop="groupName" label="分组" min-width="130" />
              <ElTableColumn label="资料进度" width="110">
                <template #default="{ row }">
                  {{ row.requiredProgress.done }}/{{ row.requiredProgress.total }}
                </template>
              </ElTableColumn>
              <ElTableColumn label="状态" width="150">
                <template #default="{ row }">
                  <StatusTag :status="row.status" :label="friendlyReviewStatus(row.status)" />
                </template>
              </ElTableColumn>
            </ElTable>
          </ElCard>
        </ElCol>

        <ElCol :span="24">
          <ElCard id="generic-findings" shadow="never" class="panel">
            <template #header>
              <div class="panel-header">
                <span>审查发现</span>
                <ElSpace>
                  <ElSelect
                    v-model="findingFilter"
                    aria-label="发现筛选"
                    style="width: 190px"
                    @change="showFindings(findingFilter)"
                  >
                    <ElOption label="全部发现" value="all" />
                    <ElOption label="待人工确认" value="pending" />
                    <ElOption label="有关联证据" value="evidence" />
                  </ElSelect>
                  <ElTag effect="plain">{{ visibleFindings.length }} 条</ElTag>
                </ElSpace>
              </div>
            </template>
            <ElTable :data="visibleFindings" class="readable-table" empty-text="当前筛选下没有发现">
              <ElTableColumn prop="title" label="发现" min-width="280" />
              <ElTableColumn label="等级" width="86">
                <template #default="{ row }">
                  <ElTag :type="severityType(row.severity)" size="small" effect="plain">
                    {{ severityLabel(row.severity) }}
                  </ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn v-if="roleContent.reviewDetails" label="置信度" width="88">
                <template #default="{ row }">{{ formatConfidence(row.confidence) }}</template>
              </ElTableColumn>
              <ElTableColumn label="人工确认" width="150">
                <template #default="{ row }"
                  ><StatusTag :status="findingReviewState(row)"
                /></template>
              </ElTableColumn>
              <ElTableColumn label="操作" width="140">
                <template #default="{ row }"
                  ><ElButton text type="primary" @click="openFinding(row.id)"
                    >查看发现与证据</ElButton
                  ></template
                >
              </ElTableColumn>
            </ElTable>
            <GenericFindingDetail
              v-if="selectedFinding"
              id="generic-finding-detail"
              :key="`${selectedFinding.projectId}:${selectedFinding.id}`"
              :finding="selectedFinding"
              :show-review-details="roleContent.reviewDetails"
              :node-name="
                workbench.nodes.find((node) => node.nodeId === selectedFinding?.nodeId)?.name ||
                `节点 ${selectedFinding.nodeId}`
              "
            />
          </ElCard>
        </ElCol>
      </ElRow>
    </StaticPageShell>
  </div>
</template>

<style scoped lang="less">
.generic-workbench {
  min-height: 100%;
  padding: 0;
  background: #f5f7fb;
}

.page-title {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.page-title h1 {
  margin: 0;
  font-size: 24px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.page-title p {
  margin: 6px 0 0;
  color: var(--el-text-color-secondary);
}

.panel {
  margin-bottom: 16px;
  border-radius: 8px;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.readable-table :deep(.cell) {
  white-space: normal;
  overflow-wrap: anywhere;
  word-break: normal;
  line-height: 1.6;
}

#generic-findings,
#generic-finding-detail,
#generic-requirements {
  scroll-margin-top: 18px;
}

.generic-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 16px;
  color: var(--el-text-color-regular);
}

@media (width <= 768px) {
  .panel-header {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
