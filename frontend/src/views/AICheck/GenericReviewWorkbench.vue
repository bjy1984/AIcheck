<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
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
import { getProjectReviewWorkbenchApi, listWorkbenchProjectsApi } from '@/api/aicheck'
import type { GenericReviewWorkbenchPayload } from '@/api/aicheck'
import type { Project } from '@/types/aicheck'
import { formatConfidence } from '@/utils/confidence'
import AuditSummaryGrid, { type AuditSummaryCard } from './components/AuditSummaryGrid.vue'
import { friendlyReviewStatus } from './components/auditLabels'
import StaticPageShell from './components/StaticPageShell.vue'
import { useUserStore } from '@/store/modules/user'
import { getAicheckRoleLabel } from '@/utils/roleAccess'

const loading = ref(false)
const error = ref('')
const projects = ref<Project[]>([])
const selectedProjectId = ref('')
const workbench = ref<GenericReviewWorkbenchPayload | null>(null)
const userStore = useUserStore()
const genericUserLabel = computed(() => {
  const user = userStore.getUserInfo
  const name = user?.displayName || user?.username || '当前用户'
  return `${name} · ${getAicheckRoleLabel(user?.role)}`
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

const genericQualityStats = computed(() => {
  const findings = workbench.value?.findings || []
  return {
    ruleRefs: findings.reduce((sum, finding) => sum + finding.ruleRefs.length, 0),
    evidenceRefs: findings.reduce((sum, finding) => sum + finding.evidenceLinkIds.length, 0),
    highRisk: findings.filter((finding) => finding.severity === 'high').length,
    humanPending: findings.filter((finding) => !finding.humanStatus).length
  }
})

const genericAuditCards = computed<AuditSummaryCard[]>(() => {
  if (!workbench.value) return []
  const evidenceCount = workbench.value.findings.reduce(
    (sum, item) => sum + item.evidenceLinkIds.length,
    0
  )

  return [
    {
      label: '当前项目',
      value: selectedProject.value?.name || workbench.value.project.name,
      hint: selectedProject.value?.businessPackId || '默认业务类型',
      tone: 'blue'
    },
    {
      label: '审查节点',
      value: `${workbench.value.nodes.length} 个`,
      hint: '节点模板来自业务类型，可迁移复用',
      tone: 'green'
    },
    {
      label: 'AI 发现',
      value: `${workbench.value.findings.length} 条`,
      hint: '全部需人工确认后生效',
      tone: 'orange'
    },
    {
      label: '证据约束',
      value: `${evidenceCount} 条`,
      hint: '发现项必须绑定 EvidenceRef',
      tone: 'red'
    }
  ]
})

const genericShellMenuSections = computed(() => [
  {
    title: selectedProject.value?.name || '通用资料审查项目',
    meta: workbench.value?.project.status || '待选择',
    chips: [
      { label: '节点', value: workbench.value?.nodes.length || 0, tone: 'blue' as const },
      { label: '发现', value: workbench.value?.findings.length || 0, tone: 'orange' as const }
    ],
    items: [
      {
        index: '01',
        label: '项目总览',
        hint: '当前业务类型与审查对象',
        badge: selectedGenericView.value === 'overview' ? '当前' : undefined,
        tone: 'blue' as const,
        active: selectedGenericView.value === 'overview',
        subpage: 'overview'
      },
      {
        index: '02',
        label: '资料要求',
        hint: '业务类型资料目录',
        active: selectedGenericView.value === 'requirements',
        subpage: 'requirements'
      },
      {
        index: '03',
        label: '规则命中',
        hint: '确定性约束',
        active: selectedGenericView.value === 'rules',
        subpage: 'rules'
      },
      {
        index: '04',
        label: 'AI 发现',
        hint: '待人工确认',
        active: selectedGenericView.value === 'findings',
        subpage: 'findings'
      },
      {
        index: '05',
        label: '证据链路',
        hint: 'EvidenceRef',
        active: selectedGenericView.value === 'evidence',
        subpage: 'evidence'
      },
      {
        index: '06',
        label: '人工确认',
        hint: '最终结论',
        active: selectedGenericView.value === 'human',
        subpage: 'human'
      }
    ]
  }
])

const genericBoundaryRows = [
  { label: '平台语义', value: '项目、节点、资料、发现、证据、补正' },
  { label: '复用边界', value: '不写死工程监检角色和资料名称' },
  { label: 'AI 边界', value: '生成审查草稿，不替代人工结论' },
  { label: '迁移方式', value: '替换业务类型、规则、知识库和报告模板' }
] as const

const genericRightCards = computed(() => [
  {
    title: '业务类型摘要',
    rows: [
      { label: '业务类型', value: workbench.value?.businessPack.name || '未选择' },
      { label: '领域', value: workbench.value?.businessPack.domainType || '-' },
      { label: '节点', value: `${workbench.value?.nodes.length || 0} 个` },
      {
        label: 'AI 发现',
        value: `${workbench.value?.findings.length || 0} 条`,
        valueBadge: '待确认'
      }
    ]
  },
  {
    title: '审查闭环',
    timeline: [
      { title: '资料提交', description: '提交方上传资料并绑定节点。', tone: 'blue' as const },
      {
        title: '规则与 AI 预审',
        description: '规则先行，AI 只生成发现草稿。',
        tone: 'orange' as const
      },
      { title: '人工确认', description: '审查方确认后才进入正式结论。', tone: 'green' as const }
    ]
  }
])

const loadWorkbench = async () => {
  if (!selectedProjectId.value) return
  loading.value = true
  error.value = ''
  try {
    const res = await getProjectReviewWorkbenchApi(selectedProjectId.value)
    if (!res) {
      error.value = '通用资料审查工作台加载失败。'
      return
    }
    workbench.value = res.data
  } catch {
    error.value = '通用资料审查工作台加载失败。'
  } finally {
    loading.value = false
  }
}

const handleGenericMenuSelect = (item: { subpage?: string; index: string }) => {
  const target = item.subpage || item.index
  selectedGenericView.value = target
  const targetElement = document.getElementById(`generic-${target}`)
  targetElement?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

const loadData = async () => {
  loading.value = true
  error.value = ''
  try {
    const res = await listWorkbenchProjectsApi('admin')
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
  <div class="generic-workbench" v-loading="loading">
    <StaticPageShell
      brand-mark="审"
      title="通用资料审查工作台"
      :status="loading ? '加载中' : '可复用内核'"
      :status-tone="loading ? 'orange' : 'green'"
      search-placeholder="搜索业务类型、节点、资料、发现"
      search-scope="admin"
      task-area="admin"
      :user-label="genericUserLabel"
      workspace-mode="wide"
      right-panel-mode="drawer"
      right-toggle-label="复用摘要"
      right-collapsed-default
      boundary-collapsed-default
      :top-stats="[
        { label: '项目', value: genericProjects.length || projects.length, tone: 'blue' },
        { label: '发现', value: workbench?.findings.length || 0, tone: 'orange' }
      ]"
      menu-title="通用审查对象"
      menu-root="资料审查 OS"
      :menu-sections="genericShellMenuSections"
      boundary-title="平台边界"
      boundary-badge="业务类型化"
      boundary-tone="green"
      :boundary-rows="genericBoundaryRows"
      right-title="复用摘要"
      right-subtitle="通用资料审查内核"
      :right-cards="genericRightCards"
      @menu-select="handleGenericMenuSelect"
    >
      <div class="page-title">
        <div>
          <h1>通用资料审查工作台</h1>
          <p>按业务类型组织节点、资料要求、AI 发现和人工确认入口</p>
        </div>
        <ElTag :type="loading ? 'warning' : 'success'" effect="plain">
          {{ loading ? '加载中' : '已连接' }}
        </ElTag>
      </div>

      <ElAlert
        v-if="error"
        type="error"
        show-icon
        :closable="false"
        :title="error"
        class="mb-12px"
      />

      <AuditSummaryGrid
        v-if="workbench"
        id="generic-overview"
        :cards="genericAuditCards"
        aria-label="通用资料审查摘要"
      />

      <ElRow :gutter="16">
        <ElCol :span="24">
          <ElCard shadow="never" class="panel">
            <template #header>
              <div class="panel-header">
                <span>业务类型项目</span>
                <ElSpace>
                  <ElSelect
                    v-model="selectedProjectId"
                    filterable
                    style="width: min(320px, 100%)"
                    @change="loadWorkbench"
                  >
                    <ElOption
                      v-for="project in projects"
                      :key="project.id"
                      :label="`${project.name} / ${project.businessPackId || '默认业务类型'}`"
                      :value="project.id"
                    />
                  </ElSelect>
                  <ElButton plain type="primary" :loading="loading" @click="loadWorkbench">
                    刷新
                  </ElButton>
                </ElSpace>
              </div>
            </template>

            <div v-if="workbench" class="generic-summary">
              <div>
                <div class="summary-label">项目</div>
                <strong>{{ selectedProject?.name || workbench.project.name }}</strong>
              </div>
              <div>
                <div class="summary-label">业务类型</div>
                <strong>{{ workbench.businessPack.name }}</strong>
              </div>
              <div>
                <div class="summary-label">节点</div>
                <strong>{{ workbench.nodes.length }}</strong>
              </div>
              <div>
                <div class="summary-label">AI 发现</div>
                <strong>{{ workbench.findings.length }}</strong>
              </div>
            </div>
            <ElEmpty v-else description="请选择业务类型项目" />
          </ElCard>
        </ElCol>
      </ElRow>

      <section v-if="workbench" class="generic-quality-grid">
        <ElCard id="generic-rules" shadow="never" class="panel quality-panel">
          <template #header>
            <div class="panel-header">
              <span>规则命中</span>
              <ElTag type="primary" effect="plain">确定性约束</ElTag>
            </div>
          </template>
          <div class="quality-body">
            <strong>{{ genericQualityStats.ruleRefs }}</strong>
            <span>条规则引用绑定到 AI 发现，规则用于判断“能不能”。</span>
          </div>
        </ElCard>
        <ElCard id="generic-evidence" shadow="never" class="panel quality-panel">
          <template #header>
            <div class="panel-header">
              <span>证据链路</span>
              <ElTag type="success" effect="plain">EvidenceRef</ElTag>
            </div>
          </template>
          <div class="quality-body">
            <strong>{{ genericQualityStats.evidenceRefs }}</strong>
            <span>条证据引用用于回溯资料、页码、字段或表格坐标。</span>
          </div>
        </ElCard>
        <ElCard id="generic-human" shadow="never" class="panel quality-panel">
          <template #header>
            <div class="panel-header">
              <span>人工确认</span>
              <ElTag type="warning" effect="plain">最终结论</ElTag>
            </div>
          </template>
          <div class="quality-body">
            <strong>{{ genericQualityStats.humanPending }}</strong>
            <span>条发现仍需人工确认，AI 输出不会直接成为正式业务结论。</span>
          </div>
        </ElCard>
      </section>

      <ElRow v-if="workbench" :gutter="16" class="mt-16px">
        <ElCol :xl="13" :lg="13" :md="24" :sm="24" :xs="24">
          <ElCard id="generic-requirements" shadow="never" class="panel">
            <template #header>
              <div class="panel-header">
                <span>节点与资料进度</span>
                <ElTag effect="plain">{{ workbench.businessPack.domainType }}</ElTag>
              </div>
            </template>
            <ElTable :data="workbench.nodes" border height="420" empty-text="暂无节点模板">
              <ElTableColumn prop="code" label="编码" width="92" />
              <ElTableColumn prop="name" label="节点" min-width="190" show-overflow-tooltip />
              <ElTableColumn prop="groupName" label="分组" min-width="130" show-overflow-tooltip />
              <ElTableColumn label="资料进度" width="110">
                <template #default="{ row }">
                  {{ row.requiredProgress.done }}/{{ row.requiredProgress.total }}
                </template>
              </ElTableColumn>
              <ElTableColumn label="状态" width="120">
                <template #default="{ row }">
                  <span :title="row.status">{{ friendlyReviewStatus(row.status) }}</span>
                </template>
              </ElTableColumn>
            </ElTable>
          </ElCard>
        </ElCol>

        <ElCol :xl="11" :lg="11" :md="24" :sm="24" :xs="24">
          <ElCard id="generic-findings" shadow="never" class="panel">
            <template #header>
              <div class="panel-header">
                <span>证据化审查发现</span>
                <ElTag type="warning" effect="plain">待人工确认</ElTag>
              </div>
            </template>
            <ElTable :data="workbench.findings" border height="420" empty-text="暂无 AI 发现草稿">
              <ElTableColumn prop="title" label="发现" min-width="180" show-overflow-tooltip />
              <ElTableColumn label="等级" width="86">
                <template #default="{ row }">
                  <ElTag :type="severityType(row.severity)" size="small" effect="plain">
                    {{ severityLabel(row.severity) }}
                  </ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn label="证据" width="80">
                <template #default="{ row }">{{ row.evidenceLinkIds.length }}</template>
              </ElTableColumn>
              <ElTableColumn label="规则" width="80">
                <template #default="{ row }">{{ row.ruleRefs.length }}</template>
              </ElTableColumn>
              <ElTableColumn label="置信度" width="88">
                <template #default="{ row }">{{ formatConfidence(row.confidence) }}</template>
              </ElTableColumn>
            </ElTable>
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
}

.generic-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.generic-quality-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 2px;
  scroll-margin-top: 18px;
}

.quality-panel {
  scroll-margin-top: 18px;
}

.quality-body {
  display: grid;
  min-height: 86px;
  gap: 8px;
  align-content: start;
}

.quality-body strong {
  font-size: 28px;
  font-weight: 600;
  line-height: 1;
  color: #1f66d8;
  font-variant-numeric: tabular-nums;
}

.quality-body span {
  font-size: 13px;
  font-weight: 600;
  line-height: 1.6;
  color: #52647d;
}

.summary-label {
  margin-bottom: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

@media (width <= 768px) {
  .generic-audit-board,
  .generic-quality-grid,
  .generic-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .panel-header {
    flex-direction: column;
    align-items: flex-start;
  }
}

@media (width <= 480px) {
  .generic-audit-board,
  .generic-quality-grid,
  .generic-summary {
    grid-template-columns: 1fr;
  }
}
</style>
