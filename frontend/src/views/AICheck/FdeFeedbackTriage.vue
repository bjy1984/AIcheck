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
  ElTag
} from 'element-plus'
import {
  getFdeFeedbackMetricsApi,
  listFdeFeedbackApi,
  triageFdeFeedbackApi,
  type FdeFeedback
} from '@/api/aicheck'
import StaticPageShell from './components/StaticPageShell.vue'
import StatusTag from './components/StatusTag.vue'
import { Icon } from '@/components/Icon'
import {
  GOVERNANCE_LABELS,
  ROOT_CAUSE_OPTIONS,
  countBy,
  feedbackCommentPreview,
  feedbackTypeLabel,
  filterRows,
  formatRatio,
  historicalRootCauses,
  rootCauseOptionsFor,
  triagePayload,
  withinWindow,
  type WindowKey
} from './fdeFeedbackTriageModel'
import { useUserStore } from '@/store/modules/user'
import { getAicheckRoleLabel } from '@/utils/roleAccess'

const userStore = useUserStore()
const userLabel = computed(() => {
  const user = userStore.getUserInfo
  const name = user?.displayName || user?.username || '当前用户'
  const role = getAicheckRoleLabel(user?.role)
  return name === role ? name : `${name} · ${role}`
})

const loading = ref(false)
const saving = ref('')
const error = ref('')
const rows = ref<FdeFeedback[]>([])
const metrics = ref<Record<string, any> | null>(null)
const metricsMarkdown = ref('')
const metricsError = ref('')

const rootCauseFilter = ref('')
const stateFilter = ref('needs_triage')
const weekFilter = ref<WindowKey>('week')

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

const visibleRows = computed(() =>
  filterRows(rows.value, {
    rootCause: rootCauseFilter.value,
    state: stateFilter.value,
    window: weekFilter.value
  })
)

const rootCauseCounts = computed(() =>
  countBy(
    rows.value.filter((row) => withinWindow(row, weekFilter.value)),
    (row) => row.rootCause || 'untriaged'
  )
)

const stateCounts = computed(() =>
  countBy(
    rows.value.filter((row) => withinWindow(row, weekFilter.value)),
    (row) => row.governanceState || 'needs_triage'
  )
)

const menuSections = computed(() => [
  {
    id: 'state',
    title: '治理状态',
    defaultOpen: true,
    items: [
      {
        index: 'state:',
        label: '全部',
        badge: String(rows.value.filter((row) => withinWindow(row, weekFilter.value)).length),
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
        badge: String(rows.value.filter((row) => withinWindow(row, weekFilter.value)).length),
        active: rootCauseFilter.value === ''
      },
      ...ROOT_CAUSE_OPTIONS.map((option) => ({
        index: `cause:${option.value}`,
        label: option.label,
        badge: String(rootCauseCounts.value[option.value] || 0),
        active: rootCauseFilter.value === option.value
      })),
      ...historicalRootCauses(rows.value).map((option) => ({
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
      value: data.rubberStampIndex == null ? '暂无盲审统计' : String(data.rubberStampIndex),
      note: '不趋零'
    }
  ]
})

const rightCards = computed(() => [
  {
    title: '反馈质量指标',
    rows: metricCards.value.map((card) => ({ label: card.label, value: card.value })),
    note: metricsError.value || '全量反馈统计，不随当前列表的时间筛选变化。'
  },
  {
    title: '样本用途',
    note: '归因仅更新反馈分类与样本用途；规则调整需另走发布和回归流程。'
  }
])

const load = async () => {
  loading.value = true
  error.value = ''
  metricsError.value = ''
  const [listResult, metricsResult] = await Promise.allSettled([
    listFdeFeedbackApi(),
    getFdeFeedbackMetricsApi()
  ])
  if (listResult.status === 'fulfilled') {
    rows.value = listResult.value.data || []
    drafts.value = {}
  } else {
    error.value = listResult.reason instanceof Error ? listResult.reason.message : '加载反馈失败'
  }
  if (metricsResult.status === 'fulfilled') {
    metrics.value = metricsResult.value.data?.metrics || null
    metricsMarkdown.value = metricsResult.value.data?.markdown || ''
  } else {
    metrics.value = null
    metricsMarkdown.value = ''
    metricsError.value = '质量指标暂不可用，可刷新重试；反馈归因不受影响。'
  }
  loading.value = false
}

const saveTriage = async (row: FdeFeedback) => {
  const draft = draftFor(row)
  if (!draft.rootCause) {
    ElMessage.warning('先选根因再归档。')
    return
  }
  saving.value = row.id
  try {
    const res = await triageFdeFeedbackApi(row.id, triagePayload(draft))
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

onMounted(load)
</script>

<template>
  <div class="feedback-triage">
    <StaticPageShell
      :refreshing="loading"
      brand-mark="归"
      title="反馈归因"
      :status="loading ? '加载中' : `${visibleRows.length} 条`"
      :status-tone="loading ? 'orange' : 'green'"
      search-placeholder="搜索反馈、发现、节点"
      search-scope="fde"
      task-area="fde"
      :user-label="userLabel"
      workspace-mode="wide"
      right-panel-mode="drawer"
      right-toggle-label="质量指标"
      right-collapsed-default
      boundary-collapsed-default
      :top-stats="[
        { label: '待归因', value: stateCounts.needs_triage || 0, tone: 'orange' },
        { label: '已入评测', value: stateCounts.promoted_to_eval || 0, tone: 'green' },
        { label: '待仲裁', value: stateCounts.needs_adjudication || 0, tone: 'orange' }
      ]"
      menu-title="归因筛选"
      menu-root="FDE 控制台"
      :menu-sections="menuSections"
      boundary-title="归因说明"
      boundary-badge="只分类不改规则"
      boundary-tone="orange"
      :boundary-rows="[
        { label: '训练用途', value: '默认关闭，仅在确认用途后启用' },
        { label: '规则改动', value: '≥2 人 ≥2 项目门槛，另走回归' }
      ]"
      right-title="反馈质量指标"
      right-subtitle="全量反馈统计"
      :right-cards="rightCards"
      @menu-select="handleMenuSelect"
    >
      <div class="page-title">
        <div>
          <h1>反馈归因</h1>
          <p>按七类根因归档人工纠正；入评测集的样本才进回放基准</p>
        </div>
        <ElSpace class="page-actions" wrap>
          <ElSelect v-model="weekFilter" aria-label="反馈时间范围" style="width: 120px">
            <ElOption value="week" label="近 7 天" />
            <ElOption value="month" label="近 30 天" />
            <ElOption value="all" label="全部" />
          </ElSelect>
          <ElButton plain :disabled="!metricsMarkdown" @click="copyMarkdown"
            ><Icon icon="vi-ep:copy-document" :size="16" aria-hidden="true" /><span
              >复制指标表</span
            ></ElButton
          >
          <ElButton type="primary" plain :loading="loading" @click="load"
            ><Icon v-if="!loading" icon="vi-ep:refresh" :size="16" aria-hidden="true" /><span
              >刷新</span
            ></ElButton
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

      <ElCard shadow="never" class="panel">
        <ElEmpty v-if="!loading && !visibleRows.length" description="这个窗口内没有待处理的反馈" />
        <p v-else-if="loading && !visibleRows.length" role="status">正在加载反馈…</p>
        <div v-else class="feedback-list" role="list" aria-label="反馈记录">
          <article
            v-for="row in visibleRows"
            :key="row.id"
            class="feedback-record"
            role="listitem"
            :aria-labelledby="`feedback-title-${row.id}`"
          >
            <header class="feedback-heading">
              <h2 :id="`feedback-title-${row.id}`">{{ row.projectId }} · 节点 {{ row.nodeId }}</h2>
              <div class="feedback-labels">
                <ElTag size="small" effect="plain">{{ feedbackTypeLabel(row.feedbackType) }}</ElTag>
                <StatusTag
                  size="small"
                  :status="row.governanceState || 'needs_triage'"
                  :label="
                    GOVERNANCE_LABELS[row.governanceState || 'needs_triage'] || row.governanceState
                  "
                />
              </div>
            </header>
            <div class="feedback-workspace">
              <div class="feedback-content">
                <dl class="feedback-decisions">
                  <div
                    ><dt>AI 建议</dt><dd>{{ row.suggestedResult || '未记录' }}</dd></div
                  >
                  <div
                    ><dt>人工结论</dt><dd>{{ row.humanResult || '未记录' }}</dd></div
                  >
                </dl>
                <div class="feedback-comment">
                  <span class="field-label">反馈说明</span>
                  <details v-if="(row.comment || '').trim().length > 140" class="long-comment">
                    <summary
                      >{{ feedbackCommentPreview(row.comment) }} <span>展开全文</span></summary
                    >
                    <p>{{ row.comment }}</p>
                  </details>
                  <p v-else>{{ row.comment || '未填写说明' }}</p>
                </div>
                <p v-if="row.claim" class="feedback-claim"
                  ><span class="field-label">相关断言</span>{{ row.claim }}</p
                >
                <details class="record-references">
                  <summary>关联编号与原始分类</summary>
                  <dl>
                    <div
                      ><dt>反馈编号</dt><dd>{{ row.id }}</dd></div
                    >
                    <div v-if="row.findingId"
                      ><dt>发现编号</dt><dd>{{ row.findingId }}</dd></div
                    >
                    <div
                      ><dt>反馈类型</dt><dd>{{ row.feedbackType || '未记录' }}</dd></div
                    >
                    <div
                      ><dt>原始根因</dt><dd>{{ row.rootCause || '未归因' }}</dd></div
                    >
                  </dl>
                </details>
              </div>
              <div class="feedback-triage-controls">
                <label :for="`root-cause-${row.id}`">归因分类</label>
                <ElSelect
                  :id="`root-cause-${row.id}`"
                  v-model="draftFor(row).rootCause"
                  :aria-label="`节点 ${row.nodeId} 的归因分类`"
                  placeholder="选择根因"
                >
                  <ElOption
                    v-for="option in rootCauseOptionsFor(row.rootCause)"
                    :key="option.value"
                    :value="option.value"
                    :label="option.label"
                  />
                </ElSelect>
                <div
                  class="sample-usage"
                  role="group"
                  :aria-label="`节点 ${row.nodeId} 的样本用途`"
                >
                  <ElCheckbox v-model="draftFor(row).canUseForEval">入评测集</ElCheckbox>
                  <ElCheckbox v-model="draftFor(row).canUseForTraining">可用于训练</ElCheckbox>
                  <ElCheckbox v-model="draftFor(row).adjudicationRequired">需仲裁</ElCheckbox>
                </div>
                <ElButton
                  class="triage-save"
                  type="primary"
                  plain
                  :loading="saving === row.id"
                  :aria-label="`归档节点 ${row.nodeId} 的反馈`"
                  @click="saveTriage(row)"
                  >归档</ElButton
                >
              </div>
            </div>
          </article>
        </div>
      </ElCard>
    </StaticPageShell>
  </div>
</template>

<style scoped lang="less">
.feedback-triage {
  .page-title {
    display: flex;
    flex-wrap: wrap;
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

  .record-references {
    margin-top: 10px;
    font-size: 13px;
    color: var(--el-text-color-secondary);
    overflow-wrap: anywhere;

    dl {
      margin: 8px 0 0;
    }
  }

  .panel {
    border-radius: 8px;
  }

  .feedback-record {
    padding: 18px 0;

    &:first-child {
      padding-top: 0;
    }
    &:last-child {
      padding-bottom: 0;
    }
    & + .feedback-record {
      border-top: 1px solid var(--el-border-color-light);
    }
  }

  .feedback-heading,
  .feedback-labels {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px 12px;
  }

  .feedback-heading {
    justify-content: space-between;
    margin-bottom: 12px;

    h2 {
      min-width: 0;
      margin: 0;
      font-size: 15px;
      line-height: 1.5;
      overflow-wrap: anywhere;
    }
  }

  .feedback-labels :deep(.el-tag) {
    max-width: 100%;
    min-height: 24px;
    height: auto;
    white-space: normal;
  }

  .feedback-labels :deep(.el-tag__content) {
    white-space: normal;
    overflow-wrap: anywhere;
  }

  .feedback-workspace {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 280px;
    align-items: start;
    gap: 20px;
  }

  .feedback-content,
  .feedback-triage-controls {
    min-width: 0;
  }

  .feedback-decisions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px 28px;
    margin: 0 0 12px;
  }

  .feedback-decisions > div,
  .record-references dl > div {
    display: flex;
    align-items: baseline;
    gap: 8px;
    min-width: 0;
  }

  dt,
  .field-label {
    color: var(--el-text-color-secondary);
    font-size: 13px;
    flex-shrink: 0;
  }

  dd {
    margin: 0;
    overflow-wrap: anywhere;
  }

  .feedback-comment p,
  .feedback-claim {
    margin: 4px 0 0;
    line-height: 1.65;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  .feedback-claim .field-label {
    display: block;
  }

  summary {
    cursor: pointer;
    line-height: 1.6;
    overflow-wrap: anywhere;

    &:focus-visible {
      outline: 2px solid var(--el-color-primary);
      outline-offset: 3px;
    }
  }

  .long-comment summary span {
    color: var(--el-color-primary);
    white-space: nowrap;
  }

  .feedback-triage-controls {
    display: grid;
    gap: 8px;

    > label {
      color: var(--el-text-color-secondary);
      font-size: 13px;
    }
  }

  .sample-usage {
    display: flex;
    flex-wrap: wrap;
    column-gap: 14px;

    :deep(.el-checkbox) {
      margin-right: 0;
    }
  }

  .triage-save {
    justify-self: end;
  }

  @media (max-width: 680px) {
    .feedback-workspace {
      grid-template-columns: minmax(0, 1fr);
      gap: 16px;
    }
    .feedback-triage-controls {
      padding-top: 12px;
      border-top: 1px solid var(--el-border-color-lighter);
    }
    .page-actions {
      width: 100%;
    }
    .triage-save {
      justify-self: stretch;
    }
    :deep(.el-button),
    :deep(.el-select__wrapper),
    :deep(.sample-usage .el-checkbox) {
      min-height: 44px;
    }
  }
}
</style>
