<script setup lang="ts">
/**
 * P12 F2 周度 triage 页：把 ai_feedback 按七类根因归档，标 canUseForEval / canUseForTraining。
 * 单条纠正永不直接改规则（优化计划 §17.4）；这里只做分类与入评测集，规则改动走 ≥2 人 ≥2 项目门槛。
 */
import { computed, onMounted, ref } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElCheckbox,
  ElEmpty,
  ElMessage,
  ElOption,
  ElSelect,
  ElSpace,
  ElTable,
  ElTableColumn,
  ElTag
} from 'element-plus'
import {
  getFdeFeedbackMetricsApi,
  listFdeFeedbackApi,
  triageFdeFeedbackApi,
  type FdeFeedback
} from '@/api/aicheck'
import StaticPageShell from './components/StaticPageShell.vue'
import { useUserStore } from '@/store/modules/user'
import { getAicheckRoleLabel } from '@/utils/roleAccess'

/** 与 backend/apps/api/feedback_capture.AI_FEEDBACK_ROOT_CAUSES 一一对应。 */
const ROOT_CAUSE_OPTIONS = [
  { value: 'data_table', label: 'A 数据表 / 限值' },
  { value: 'rule_logic', label: 'B 确定性规则' },
  { value: 'guard_downgrade', label: 'C 守卫误杀' },
  { value: 'evidence_extraction', label: 'D 证据抽取' },
  { value: 'prompt', label: 'E 提示词' },
  { value: 'policy', label: 'F 业务口径' },
  { value: 'external_source', label: 'G 外部源' },
  { value: 'other', label: '其它 / 未定' }
] as const

const GOVERNANCE_LABELS: Record<string, string> = {
  needs_triage: '待归因',
  triaged: '已归因',
  ready_for_eval: '可入评测',
  promoted_to_eval: '已入评测',
  needs_adjudication: '待仲裁'
}

const FEEDBACK_TYPE_LABELS: Record<string, string> = {
  accepted: '采纳',
  rejected: '驳回',
  wrong_evidence: '证据有误',
  missed_issue: '漏报',
  guard_false_downgrade: '守卫误降级',
  human_override: '人工改判',
  return_for_correction: '退回补正'
}

const userStore = useUserStore()
const userLabel = computed(() => {
  const user = userStore.getUserInfo
  return `${user?.displayName || user?.username || '当前用户'} · ${getAicheckRoleLabel(user?.role)}`
})

const loading = ref(false)
const saving = ref('')
const error = ref('')
const rows = ref<FdeFeedback[]>([])
const metrics = ref<Record<string, any> | null>(null)
const metricsMarkdown = ref('')

const rootCauseFilter = ref('')
const stateFilter = ref('needs_triage')
const weekFilter = ref<'week' | 'month' | 'all'>('week')

/** 每行的待提交归因草稿；不直接改 rows，保存成功后再回填。 */
const drafts = ref<
  Record<
    string,
    {
      rootCause: string
      canUseForEval: boolean
      canUseForTraining: boolean
      adjudicationRequired: boolean
    }
  >
>({})

const draftFor = (row: FdeFeedback) => {
  if (!drafts.value[row.id]) {
    drafts.value[row.id] = {
      rootCause: row.rootCause || '',
      canUseForEval: Boolean(row.canUseForEval),
      canUseForTraining: Boolean(row.canUseForTraining),
      adjudicationRequired: Boolean(row.adjudicationRequired)
    }
  }
  return drafts.value[row.id]
}

const withinWindow = (row: FdeFeedback) => {
  if (weekFilter.value === 'all') return true
  const created = Date.parse(row.createdAt || '')
  if (Number.isNaN(created)) return true
  const days = weekFilter.value === 'week' ? 7 : 30
  return Date.now() - created <= days * 86400000
}

const visibleRows = computed(() =>
  rows.value.filter((row) => {
    if (rootCauseFilter.value && (row.rootCause || '') !== rootCauseFilter.value) return false
    if (stateFilter.value && (row.governanceState || 'needs_triage') !== stateFilter.value)
      return false
    return withinWindow(row)
  })
)

const rootCauseCounts = computed(() => {
  const counts: Record<string, number> = {}
  rows.value.filter(withinWindow).forEach((row) => {
    const key = row.rootCause || 'untriaged'
    counts[key] = (counts[key] || 0) + 1
  })
  return counts
})

const stateCounts = computed(() => {
  const counts: Record<string, number> = {}
  rows.value.filter(withinWindow).forEach((row) => {
    const key = row.governanceState || 'needs_triage'
    counts[key] = (counts[key] || 0) + 1
  })
  return counts
})

const menuSections = computed(() => [
  {
    id: 'state',
    title: '治理状态',
    defaultOpen: true,
    items: [
      {
        index: 'state:',
        label: '全部',
        badge: String(rows.value.filter(withinWindow).length),
        active: stateFilter.value === ''
      },
      ...Object.entries(GOVERNANCE_LABELS).map(([key, label]) => ({
        index: `state:${key}`,
        label,
        badge: String(stateCounts.value[key] || 0),
        active: stateFilter.value === key
      }))
    ]
  },
  {
    id: 'root-cause',
    title: '七类根因',
    defaultOpen: true,
    items: [
      {
        index: 'cause:',
        label: '全部',
        badge: String(rows.value.filter(withinWindow).length),
        active: rootCauseFilter.value === ''
      },
      ...ROOT_CAUSE_OPTIONS.map((option) => ({
        index: `cause:${option.value}`,
        label: option.label,
        badge: String(rootCauseCounts.value[option.value] || 0),
        active: rootCauseFilter.value === option.value
      })),
      {
        index: 'cause:untriaged',
        label: '未归因',
        badge: String(rootCauseCounts.value.untriaged || 0),
        active: false
      }
    ]
  }
])

const handleMenuSelect = (item: { index?: string }) => {
  const key = item?.index || ''
  if (key.startsWith('state:')) stateFilter.value = key.slice('state:'.length)
  else if (key === 'cause:untriaged') {
    rootCauseFilter.value = ''
    stateFilter.value = 'needs_triage'
  } else if (key.startsWith('cause:')) rootCauseFilter.value = key.slice('cause:'.length)
}

const formatRatio = (item: unknown) => {
  if (!item || typeof item !== 'object') return '—'
  const value = (item as { value?: number | null }).value
  if (value === null || value === undefined) return '—'
  return `${(Number(value) * 100).toFixed(1)}%`
}

const metricCards = computed(() => {
  const data = metrics.value
  if (!data) return []
  return [
    { label: '采集覆盖率', value: formatRatio(data.collectionCoverage), note: '目标 ≥ 95%' },
    { label: '采纳率', value: formatRatio(data.adoptionRate), note: '高但不趋 100%' },
    { label: '覆盖差异率', value: formatRatio(data.overrideRate), note: '逐版下降' },
    { label: '发现级精确率', value: formatRatio(data.findingPrecision), note: '上升' },
    { label: '补充发现数', value: String(data.supplementalFindings ?? 0), note: '召回率分子' },
    { label: '误降级率', value: formatRatio(data.falseDowngradeRate), note: '下降' },
    { label: '证据引用准确率', value: formatRatio(data.evidenceReferenceAccuracy), note: '上升' },
    {
      label: '橡皮图章指数',
      value: data.rubberStampIndex == null ? '待 F4 盲审' : String(data.rubberStampIndex),
      note: '不趋零'
    }
  ]
})

const rightCards = computed(() => [
  {
    title: '§17.3 指标',
    rows: metricCards.value.map((card) => ({ label: card.label, value: card.value }))
  },
  {
    title: '规则',
    note: '单条纠正永不直接改规则；canUseForTraining 默认关，只做评估与检索。数据表候选行需 ≥2 人 ≥2 项目才合并。'
  }
])

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    const [listRes, metricsRes] = await Promise.all([
      listFdeFeedbackApi(),
      getFdeFeedbackMetricsApi()
    ])
    rows.value = listRes.data || []
    metrics.value = metricsRes.data?.metrics || null
    metricsMarkdown.value = metricsRes.data?.markdown || ''
    drafts.value = {}
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载反馈失败'
  } finally {
    loading.value = false
  }
}

const saveTriage = async (row: FdeFeedback) => {
  const draft = draftFor(row)
  if (!draft.rootCause) {
    ElMessage.warning('先选根因再归档。')
    return
  }
  saving.value = row.id
  try {
    const res = await triageFdeFeedbackApi(row.id, {
      rootCause: draft.rootCause,
      status: draft.canUseForEval ? 'approved_for_eval' : 'triaged',
      canUseForEval: draft.canUseForEval,
      canUseForTraining: draft.canUseForTraining,
      adjudicationRequired: draft.adjudicationRequired
    })
    const updated = res.data?.feedback
    if (updated) {
      rows.value = rows.value.map((item) => (item.id === row.id ? { ...item, ...updated } : item))
      delete drafts.value[row.id]
    }
    ElMessage.success(`已归因：${row.id}`)
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '归因失败')
  } finally {
    saving.value = ''
  }
}

const copyMarkdown = async () => {
  if (!metricsMarkdown.value) return
  try {
    await navigator.clipboard.writeText(metricsMarkdown.value)
    ElMessage.success('指标表已复制（Markdown）')
  } catch {
    ElMessage.warning('浏览器不允许写剪贴板，可从右栏抄录。')
  }
}

const stateTagType = (state?: string) => {
  if (state === 'promoted_to_eval' || state === 'ready_for_eval') return 'success'
  if (state === 'needs_adjudication') return 'danger'
  if (state === 'triaged') return 'info'
  return 'warning'
}

onMounted(load)
</script>

<template>
  <div class="feedback-triage">
    <StaticPageShell
      :refreshing="loading"
      brand-mark="归"
      title="反馈归因（周度 triage）"
      :status="loading ? '加载中' : `${visibleRows.length} 条`"
      :status-tone="loading ? 'orange' : 'green'"
      search-placeholder="搜索反馈 id、发现、断言"
      search-scope="admin"
      task-area="admin"
      :user-label="userLabel"
      workspace-mode="wide"
      right-panel-mode="drawer"
      right-toggle-label="指标"
      right-collapsed-default
      boundary-collapsed-default
      :top-stats="[
        { label: '待归因', value: stateCounts.needs_triage || 0, tone: 'orange' },
        { label: '已入评测', value: stateCounts.promoted_to_eval || 0, tone: 'green' },
        { label: '待仲裁', value: stateCounts.needs_adjudication || 0, tone: 'red' }
      ]"
      menu-title="归因筛选"
      menu-root="FDE 控制台"
      :menu-sections="menuSections"
      boundary-title="飞轮边界"
      boundary-badge="只分类不改规则"
      boundary-tone="orange"
      :boundary-rows="[
        { label: '训练用途', value: 'canUseForTraining 默认关' },
        { label: '规则改动', value: '≥2 人 ≥2 项目门槛，另走回归' }
      ]"
      right-title="§17.3 指标"
      right-subtitle="libs/feedback/metrics.py 实时计算"
      :right-cards="rightCards"
      @menu-select="handleMenuSelect"
    >
      <div class="page-title">
        <div>
          <h1>反馈归因</h1>
          <p>按七类根因归档人工纠正；入评测集的样本才进回放基准</p>
        </div>
        <ElSpace>
          <ElSelect v-model="weekFilter" size="small" style="width: 120px">
            <ElOption value="week" label="近 7 天" />
            <ElOption value="month" label="近 30 天" />
            <ElOption value="all" label="全部" />
          </ElSelect>
          <ElButton size="small" plain :disabled="!metricsMarkdown" @click="copyMarkdown"
            >复制指标表</ElButton
          >
          <ElButton size="small" type="primary" plain :loading="loading" @click="load"
            >刷新</ElButton
          >
        </ElSpace>
      </div>

      <ElAlert
        v-if="error"
        type="error"
        show-icon
        :closable="false"
        :title="error"
        class="mb-12px"
      />

      <div v-if="metricCards.length" class="metric-grid">
        <div v-for="card in metricCards" :key="card.label" class="metric-card">
          <span class="metric-label">{{ card.label }}</span>
          <strong class="metric-value">{{ card.value }}</strong>
          <span class="metric-note">{{ card.note }}</span>
        </div>
      </div>

      <ElCard shadow="never" class="panel">
        <ElEmpty v-if="!loading && !visibleRows.length" description="这个窗口内没有待处理的反馈" />
        <ElTable v-else :data="visibleRows" border row-key="id" empty-text="加载中">
          <ElTableColumn prop="id" label="反馈" width="130" show-overflow-tooltip />
          <ElTableColumn label="类型" width="110">
            <template #default="{ row }">
              <ElTag size="small" effect="plain">{{
                FEEDBACK_TYPE_LABELS[row.feedbackType] || row.feedbackType
              }}</ElTag>
            </template>
          </ElTableColumn>
          <ElTableColumn label="节点 / 发现" min-width="200">
            <template #default="{ row }">
              <div class="cell-stack">
                <span>{{ row.projectId }} · 节点 {{ row.nodeId }}</span>
                <span v-if="row.findingId" class="muted">{{ row.findingId }}</span>
                <span v-if="row.claim" class="muted">断言：{{ row.claim }}</span>
              </div>
            </template>
          </ElTableColumn>
          <ElTableColumn label="AI → 人工" width="150">
            <template #default="{ row }">
              <span>{{ row.suggestedResult || '—' }} → {{ row.humanResult || '—' }}</span>
            </template>
          </ElTableColumn>
          <ElTableColumn prop="comment" label="说明" min-width="220" show-overflow-tooltip />
          <ElTableColumn label="状态" width="110">
            <template #default="{ row }">
              <ElTag size="small" :type="stateTagType(row.governanceState)">
                {{
                  GOVERNANCE_LABELS[row.governanceState || 'needs_triage'] || row.governanceState
                }}
              </ElTag>
            </template>
          </ElTableColumn>
          <ElTableColumn label="根因" width="190">
            <template #default="{ row }">
              <ElSelect
                v-model="draftFor(row).rootCause"
                size="small"
                placeholder="选根因"
                style="width: 170px"
              >
                <ElOption
                  v-for="option in ROOT_CAUSE_OPTIONS"
                  :key="option.value"
                  :value="option.value"
                  :label="option.label"
                />
              </ElSelect>
            </template>
          </ElTableColumn>
          <ElTableColumn label="用途" width="230">
            <template #default="{ row }">
              <div class="cell-stack">
                <ElCheckbox v-model="draftFor(row).canUseForEval" size="small">入评测集</ElCheckbox>
                <ElCheckbox v-model="draftFor(row).canUseForTraining" size="small"
                  >可用于训练</ElCheckbox
                >
                <ElCheckbox v-model="draftFor(row).adjudicationRequired" size="small"
                  >需仲裁</ElCheckbox
                >
              </div>
            </template>
          </ElTableColumn>
          <ElTableColumn label="" width="90" fixed="right">
            <template #default="{ row }">
              <ElButton
                size="small"
                type="primary"
                plain
                :loading="saving === row.id"
                @click="saveTriage(row)"
                >归档</ElButton
              >
            </template>
          </ElTableColumn>
        </ElTable>
      </ElCard>
    </StaticPageShell>
  </div>
</template>

<style scoped lang="less">
.feedback-triage {
  .page-title {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 12px;

    h1 {
      margin: 0;
      font-size: 20px;
    }

    p {
      margin: 4px 0 0;
      font-size: 13px;
      color: var(--el-text-color-secondary);
    }
  }

  .metric-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
    gap: 8px;
    margin-bottom: 12px;
  }

  .metric-card {
    display: flex;
    padding: 10px 12px;
    background: var(--el-fill-color-blank);
    border: 1px solid var(--el-border-color-lighter);
    border-radius: 6px;
    flex-direction: column;
    gap: 2px;
  }

  .metric-label {
    font-size: 12px;
    color: var(--el-text-color-secondary);
  }

  .metric-value {
    font-size: 18px;
    font-variant-numeric: tabular-nums;
  }

  .metric-note {
    font-size: 11px;
    color: var(--el-text-color-placeholder);
  }

  .panel {
    border-radius: 8px;
  }

  .cell-stack {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .muted {
    font-size: 12px;
    color: var(--el-text-color-secondary);
  }
}
</style>
