<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElCol,
  ElDescriptions,
  ElDescriptionsItem,
  ElEmpty,
  ElRow,
  ElSpace,
  ElTabPane,
  ElTable,
  ElTableColumn,
  ElTabs,
  ElTag
} from 'element-plus'
import {
  createFdeDataExportApi,
  createFdeEvaluationRunApi,
  createFdeOcrCorrectionApi,
  createFdeOcrEvaluationRunApi,
  getFdeAiRunApi,
  getFdeCapabilityBundlesApi,
  getFdeCostBudgetsApi,
  getFdeDashboardApi,
  getFdeEvaluationSetsApi,
  getFdeOcrRunApi,
  getFdeOcrQualityApi,
  installFdeBusinessPackApi,
  listFdeAcceptanceReportsApi,
  listFdeAccessGrantsApi,
  listFdeAiRunsApi,
  listFdeFeedbackApi,
  listFdeIncidentsApi,
  listFdeOcrRunsApi,
  listFdeReleasesApi,
  requestFdeAccessGrantApi,
  replayFdeAiRunApi,
  startFdeShadowApi,
  submitFdeReleaseApi,
  triageFdeFeedbackApi,
  updateFdeIncidentRcaApi,
  validateFdeBusinessPacksApi
} from '@/api/aicheck'
import type {
  BusinessPackValidateAllPayload,
  FdeAccessPayload,
  FdeAiRun,
  FdeAiRunDetailPayload,
  FdeCapabilityBundlePayload,
  FdeDashboardPayload,
  FdeEvaluationPayload,
  FdeFeedback,
  FdeIncidentPayload,
  FdeOcrEvalRun,
  FdeOcrQualityPayload,
  FdeOcrRunDetailPayload,
  FdeReleasePayload
} from '@/api/aicheck'

const loading = ref(false)
const actionLoading = ref(false)
const error = ref('')
const dashboard = ref<FdeDashboardPayload | null>(null)
const aiRuns = ref<FdeAiRun[]>([])
const selectedRun = ref<FdeAiRunDetailPayload | null>(null)
const feedback = ref<FdeFeedback[]>([])
const evaluation = ref<FdeEvaluationPayload | null>(null)
const bundles = ref<FdeCapabilityBundlePayload | null>(null)
const releases = ref<FdeReleasePayload | null>(null)
const ocrQuality = ref<FdeOcrQualityPayload | null>(null)
const ocrRuns = ref<Array<Record<string, unknown>>>([])
const selectedOcrRun = ref<FdeOcrRunDetailPayload | null>(null)
const incidentPayload = ref<FdeIncidentPayload | null>(null)
const accessGrants = ref<Array<Record<string, unknown>>>([])
const costGovernance = ref<FdeAccessPayload | null>(null)
const acceptanceReports = ref<Array<Record<string, unknown>>>([])
const packValidation = ref<BusinessPackValidateAllPayload | null>(null)

const percent = (value?: number | string) => {
  const numeric = Number(value || 0)
  if (Number.isNaN(numeric)) return value || '-'
  return `${Math.round(numeric * 100)}%`
}

const scorePercent = (value?: number | string) => {
  const numeric = Number(value ?? 0)
  if (Number.isNaN(numeric)) return '-'
  return `${Math.round(numeric * 1000) / 10}%`
}

const statusType = (status?: string) => {
  if (!status) return 'info'
  if (
    ['完成', 'completed', 'production', 'production_approved', 'accepted', 'active'].includes(
      status
    )
  ) {
    return 'success'
  }
  if (['失败', 'blocked_by_gate', 'rejected'].includes(status)) return 'danger'
  if (['queued', 'submitted', 'monitoring', '排队中'].includes(status)) return 'warning'
  return 'info'
}

const firstEvaluationSetId = computed(() => String(evaluation.value?.sets?.[0]?.id || ''))
const firstBundleId = computed(() => String(bundles.value?.bundles?.[0]?.id || ''))
const firstRunId = computed(() => String(aiRuns.value[0]?.id || ''))
const firstReportId = computed(() => String(evaluation.value?.reports?.[0]?.id || ''))
const firstReleaseId = computed(() => String(releases.value?.plans?.[0]?.id || ''))
const firstPackId = computed(() => String(packValidation.value?.results?.[0]?.summary?.id || ''))
const firstOcrJobId = computed(() => String(ocrRuns.value[0]?.id || ocrRuns.value[0]?.jobId || ''))
const firstLowConfidenceField = computed(() => ocrQuality.value?.lowConfidenceFields?.[0])
const ocrRuntimeDoctor = computed(() => ocrQuality.value?.runtimeDoctor || null)
const firstRuntimeIssue = computed(() => ocrRuntimeDoctor.value?.topIssues?.[0] || null)
const selectedOcrResultSummary = computed(
  () => (selectedOcrRun.value?.job?.resultSummary || {}) as Record<string, unknown>
)
const selectedOcrPreprocessStatus = computed(
  () => (selectedOcrRun.value?.parseResult?.preprocessStatus || {}) as Record<string, unknown>
)
const selectedOcrRequestedVariants = computed(
  () => (selectedOcrPreprocessStatus.value.requestedVariants || []) as string[]
)
const selectedOcrGeneratedVariants = computed(
  () => (selectedOcrPreprocessStatus.value.generatedVariants || []) as string[]
)
const selectedOcrMissingVariants = computed(
  () => (selectedOcrPreprocessStatus.value.missingVariants || []) as string[]
)
const selectedOcrEngineRows = computed(
  () => (selectedOcrRun.value?.parseResult?.engineRuns || selectedOcrRun.value?.job?.engineRuns || []) as Array<Record<string, unknown>>
)
const ocrFieldFailureRows = computed(
  () =>
    (ocrQuality.value?.failurePools?.fieldFailures || []).slice(0, 8).map((item) =>
      typeof item === 'string' ? { code: item, source: 'diagnostic' } : item
    ) as Array<Record<string, unknown>>
)
const ocrMissingEvidenceRows = computed(
  () => (ocrQuality.value?.evidenceLevel?.missingEvidenceItems || []).slice(0, 8)
)
const topOcrQualityReason = computed(() => ocrQuality.value?.qualityReasonCounts?.[0] || null)
const topOcrFieldCode = computed(() => ocrQuality.value?.fieldLevel?.fieldCodeBreakdown?.[0] || null)
const topOcrFieldFlag = computed(() => ocrQuality.value?.fieldLevel?.qualityFlagCounts?.[0] || null)
const topMissingRequiredField = computed(
  () => ocrQuality.value?.fieldLevel?.missingRequiredFieldBreakdown?.[0] || null
)
const topMissingRequiredTable = computed(
  () => ocrQuality.value?.tableLevel?.missingRequiredTableBreakdown?.[0] || null
)
const topMatchedExpectedSealType = computed(
  () => ocrQuality.value?.sealLevel?.matchedExpectedSealTypeBreakdown?.[0] || null
)
const topMissingExpectedSealType = computed(
  () => ocrQuality.value?.sealLevel?.missingExpectedSealTypeBreakdown?.[0] || null
)
const latestOcrEvalRun = computed<FdeOcrEvalRun | null>(() => ocrQuality.value?.evalRuns?.[0] || null)
const latestOcrEvalReport = computed(() => latestOcrEvalRun.value?.evaluationReport || null)
const latestOcrEvalCompact = computed(() => latestOcrEvalRun.value?.evaluationSummary || null)
const latestOcrEvalSummary = computed(
  () => latestOcrEvalCompact.value?.summary || latestOcrEvalReport.value?.summary || {}
)
const latestOcrEvalCaseTotal = computed(
  () =>
    latestOcrEvalSummary.value.total ||
    latestOcrEvalSummary.value.cases ||
    Number(latestOcrEvalRun.value?.metrics?.caseCount || 0)
)
const latestOcrEvalOk = computed(
  () =>
    latestOcrEvalCompact.value?.ok ??
    latestOcrEvalReport.value?.ok ??
    false
)
const latestOcrScenarioMetrics = computed(
  () => latestOcrEvalCompact.value?.scenarioMetrics || latestOcrEvalRun.value?.scenarioMetrics || {}
)
const ocrScenarioRows = computed(() =>
  Object.entries(latestOcrScenarioMetrics.value).map(([scenario, item]) => {
    const summary = 'summary' in item && item.summary ? item.summary : item
    return {
      scenario,
      ok: Boolean(item?.ok),
      total: summary?.total || summary?.cases || 0,
      passed: summary?.passed || 0,
      failed: summary?.failed || 0,
      averageScore: summary?.averageScore || 0,
      thresholdFailureCount: item?.thresholdFailures?.length || 0
    }
  })
)
const ocrThresholdFailureRows = computed(() => {
  const rows: Array<Record<string, unknown>> = []
  for (const item of latestOcrEvalCompact.value?.thresholdFailures || latestOcrEvalReport.value?.thresholdFailures || []) {
    rows.push({ scope: 'overall', ...item })
  }
  for (const [scenario, item] of Object.entries(latestOcrScenarioMetrics.value)) {
    for (const failure of item?.thresholdFailures || []) {
      rows.push({ scope: scenario, ...failure })
    }
  }
  return rows
})
const ocrFindingCountRows = computed(() => {
  const rows: Array<{ scope: string; code: string; count: number }> = Object.entries(
    latestOcrEvalCompact.value?.findingCounts || latestOcrEvalReport.value?.findingCounts || {}
  ).map(
    ([code, count]) => ({
      scope: 'overall',
      code,
      count: Number(count || 0)
    })
  )
  for (const [scenario, item] of Object.entries(latestOcrScenarioMetrics.value)) {
    for (const [code, count] of Object.entries(item?.findingCounts || {})) {
      rows.push({ scope: scenario, code, count: Number(count || 0) })
    }
  }
  return rows
    .sort((left, right) => Number(right.count || 0) - Number(left.count || 0))
    .slice(0, 8)
})
const failedOcrCaseRows = computed(() =>
  (
    latestOcrEvalCompact.value?.failedCases ||
    (latestOcrEvalRun.value?.caseDiagnostics || []).filter(
      (item) => item.passed === false || Boolean(item.findings?.length)
    )
  )
    .slice(0, 8)
    .map((item) => {
      const firstFinding = item.findings?.[0]
      return {
        caseId: item.caseId,
        scenario: item.scenario,
        score: item.score || 0,
        finding:
          typeof firstFinding === 'string'
            ? firstFinding
            : String(firstFinding?.code || firstFinding?.message || '-')
      }
    })
)
const incidents = computed(() => incidentPayload.value?.incidents || [])
const rcaItems = computed(() => incidentPayload.value?.rca || [])

const loadData = async () => {
  loading.value = true
  error.value = ''
  try {
    const [
      dashboardRes,
      aiRunRes,
      feedbackRes,
      evaluationRes,
      bundleRes,
      releaseRes,
      ocrRes,
      ocrRunRes,
      incidentRes,
      acceptanceRes,
      validationRes,
      accessRes,
      costRes
    ] = await Promise.all([
      getFdeDashboardApi(),
      listFdeAiRunsApi({ pageSize: 20 }),
      listFdeFeedbackApi(),
      getFdeEvaluationSetsApi(),
      getFdeCapabilityBundlesApi(),
      listFdeReleasesApi(),
      getFdeOcrQualityApi(),
      listFdeOcrRunsApi({ pageSize: 20 }),
      listFdeIncidentsApi(),
      listFdeAcceptanceReportsApi(),
      validateFdeBusinessPacksApi(),
      listFdeAccessGrantsApi(),
      getFdeCostBudgetsApi()
    ])
    dashboard.value = dashboardRes.data
    aiRuns.value = aiRunRes.data.items
    feedback.value = feedbackRes.data
    evaluation.value = evaluationRes.data
    bundles.value = bundleRes.data
    releases.value = releaseRes.data
    ocrQuality.value = ocrRes.data
    ocrRuns.value = ocrRunRes.data.items
    incidentPayload.value = incidentRes.data
    acceptanceReports.value = acceptanceRes.data
    packValidation.value = validationRes.data
    accessGrants.value = accessRes.data
    costGovernance.value = costRes.data
    if (aiRuns.value[0]) {
      await loadRunDetail(aiRuns.value[0].id)
    }
    if (firstOcrJobId.value) {
      await loadOcrRunDetail(firstOcrJobId.value)
    }
  } catch {
    error.value = 'FDE 后台数据加载失败。'
  } finally {
    loading.value = false
  }
}

const loadRunDetail = async (runId: string) => {
  const res = await getFdeAiRunApi(runId)
  selectedRun.value = res.data
}

const loadOcrRunDetail = async (jobId: string) => {
  const res = await getFdeOcrRunApi(jobId)
  selectedOcrRun.value = res.data
}

const replayFirstRun = async () => {
  if (!aiRuns.value[0]) return
  actionLoading.value = true
  try {
    await replayFdeAiRunApi(aiRuns.value[0].id, {
      runType: 'diagnostic_replay',
      reason: 'FDE 诊断重跑'
    })
    await loadData()
  } finally {
    actionLoading.value = false
  }
}

const triageFirstFeedback = async () => {
  if (!feedback.value[0]) return
  actionLoading.value = true
  try {
    await triageFdeFeedbackApi(feedback.value[0].id, {
      rootCause: 'prompt_error',
      status: 'triaged',
      canUseForEval: true,
      canUseForTraining: false
    })
    await loadData()
  } finally {
    actionLoading.value = false
  }
}

const startEvaluation = async () => {
  if (!firstEvaluationSetId.value) return
  actionLoading.value = true
  try {
    await createFdeEvaluationRunApi({
      evaluationSetId: firstEvaluationSetId.value,
      capabilityBundleId: firstBundleId.value || undefined
    })
    await loadData()
  } finally {
    actionLoading.value = false
  }
}

const requestRawAccess = async () => {
  if (!firstRunId.value) return
  actionLoading.value = true
  try {
    await requestFdeAccessGrantApi({
      targetType: 'ai_run',
      targetId: firstRunId.value,
      reason: 'FDE 诊断需要查看 AI Run 原文。'
    })
    await createFdeDataExportApi({
      targetType: 'ai_run',
      targetId: firstRunId.value,
      masked: true
    })
    await loadData()
  } finally {
    actionLoading.value = false
  }
}

const submitReleaseGate = async () => {
  if (!firstReleaseId.value) return
  actionLoading.value = true
  try {
    await submitFdeReleaseApi(firstReleaseId.value, {
      evaluationReportId: firstReportId.value || undefined,
      rollbackPlanId: 'ROLLBACK-BUNDLE-202606'
    })
    await loadData()
  } finally {
    actionLoading.value = false
  }
}

const startShadowRun = async () => {
  if (!firstReleaseId.value) return
  actionLoading.value = true
  try {
    await startFdeShadowApi(firstReleaseId.value, { sampleRate: 0 })
    await loadData()
  } finally {
    actionLoading.value = false
  }
}

const installBusinessPack = async () => {
  if (!firstPackId.value) return
  actionLoading.value = true
  try {
    await installFdeBusinessPackApi(firstPackId.value, { tenantId: 'demo', dryRun: true })
    await loadData()
  } finally {
    actionLoading.value = false
  }
}

const updateFirstRca = async () => {
  const incidentId = String(incidents.value[0]?.id || '')
  if (!incidentId) return
  actionLoading.value = true
  try {
    await updateFdeIncidentRcaApi(incidentId, {
      status: 'open',
      rootCause: 'low_quality_scan',
      temporaryAction: '已要求低置信度字段人工复核。',
      longTermAction: '优化 OCR Profile 预处理参数。'
    })
    await loadData()
  } finally {
    actionLoading.value = false
  }
}

const correctFirstOcrField = async () => {
  const field = firstLowConfidenceField.value
  if (!field) return
  actionLoading.value = true
  try {
    await createFdeOcrCorrectionApi({
      fieldId: field.id,
      documentVersionId: field.documentVersionId,
      correctedValue: String(field.fieldValue ?? ''),
      reason: 'FDE 复核低置信度字段'
    })
    await loadData()
  } finally {
    actionLoading.value = false
  }
}

const startOcrEvaluation = async () => {
  actionLoading.value = true
  try {
    await createFdeOcrEvaluationRunApi({
      profileId: String(selectedOcrRun.value?.job?.profileId || 'all')
    })
    await loadData()
  } finally {
    actionLoading.value = false
  }
}

onMounted(loadData)
</script>

<template>
  <div class="fde-console">
    <div class="page-title">
      <div>
        <h1>FDE 后台</h1>
        <p>AI Delivery & Governance Console</p>
      </div>
      <ElSpace>
        <ElTag :type="loading ? 'warning' : 'success'" effect="plain">
          {{ loading ? '加载中' : '已连接' }}
        </ElTag>
        <ElButton type="primary" plain :loading="loading" @click="loadData">刷新</ElButton>
      </ElSpace>
    </div>

    <ElAlert v-if="error" type="error" show-icon :closable="false" :title="error" class="mb-12px" />

    <ElRow :gutter="12">
      <ElCol
        v-for="metric in dashboard?.metrics || []"
        :key="metric.label"
        :xl="4"
        :lg="8"
        :md="8"
        :sm="12"
        :xs="24"
      >
        <ElCard shadow="never" class="metric-card">
          <div class="metric-label">{{ metric.label }}</div>
          <strong>{{ metric.suffix === '%' ? percent(metric.value) : metric.value }}</strong>
        </ElCard>
      </ElCol>
    </ElRow>

    <ElTabs class="mt-16px" model-value="runs">
      <ElTabPane label="AI Run 追踪" name="runs">
        <ElRow :gutter="16">
          <ElCol :xl="14" :lg="14" :md="24" :sm="24" :xs="24">
            <ElCard shadow="never" class="panel">
              <template #header>
                <div class="panel-header">
                  <span>不可变 Run 列表</span>
                  <ElButton size="small" plain :loading="actionLoading" @click="replayFirstRun">
                    诊断重跑
                  </ElButton>
                </div>
              </template>
              <ElTable
                :data="aiRuns"
                border
                height="360"
                @row-click="(row) => loadRunDetail(row.id)"
              >
                <ElTableColumn prop="id" label="Run ID" min-width="190" show-overflow-tooltip />
                <ElTableColumn prop="agentId" label="Agent" min-width="160" show-overflow-tooltip />
                <ElTableColumn prop="status" label="状态" width="110">
                  <template #default="{ row }">
                    <ElTag :type="statusType(row.status)" effect="plain">{{ row.status }}</ElTag>
                  </template>
                </ElTableColumn>
                <ElTableColumn prop="runType" label="类型" width="130" />
                <ElTableColumn prop="immutable" label="审计" width="90">
                  <template #default="{ row }">
                    <ElTag v-if="row.immutable" type="success" effect="plain">不可变</ElTag>
                  </template>
                </ElTableColumn>
              </ElTable>
            </ElCard>
          </ElCol>
          <ElCol :xl="10" :lg="10" :md="24" :sm="24" :xs="24">
            <ElCard shadow="never" class="panel">
              <template #header>
                <div class="panel-header">
                  <span>Trace 明细</span>
                  <ElButton size="small" plain :loading="actionLoading" @click="requestRawAccess">
                    申请原文
                  </ElButton>
                </div>
              </template>
              <ElDescriptions v-if="selectedRun" :column="1" border>
                <ElDescriptionsItem label="Run">{{ selectedRun.run.id }}</ElDescriptionsItem>
                <ElDescriptionsItem label="输入 Hash">{{
                  selectedRun.run.inputHash
                }}</ElDescriptionsItem>
                <ElDescriptionsItem label="输出 Hash">{{
                  selectedRun.run.outputHash
                }}</ElDescriptionsItem>
                <ElDescriptionsItem label="原文权限">
                  {{ selectedRun.accessPolicy.rawAccess ? '已授权' : '脱敏查看' }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="重跑次数">{{
                  selectedRun.replays.length
                }}</ElDescriptionsItem>
              </ElDescriptions>
              <ElTable v-if="selectedRun" :data="selectedRun.traceSteps" border class="mt-12px">
                <ElTableColumn prop="sequence" label="#" width="64" />
                <ElTableColumn prop="name" label="步骤" min-width="180" show-overflow-tooltip />
                <ElTableColumn prop="status" label="状态" width="110" />
                <ElTableColumn prop="latencyMs" label="耗时" width="110" />
              </ElTable>
              <ElEmpty v-else description="请选择 AI Run" />
            </ElCard>
          </ElCol>
        </ElRow>
      </ElTabPane>

      <ElTabPane label="反馈与评估" name="feedback">
        <ElRow :gutter="16">
          <ElCol :xl="12" :lg="12" :md="24" :sm="24" :xs="24">
            <ElCard shadow="never" class="panel">
              <template #header>
                <div class="panel-header">
                  <span>人工反馈池</span>
                  <ElButton
                    size="small"
                    plain
                    :loading="actionLoading"
                    @click="triageFirstFeedback"
                  >
                    归因首条
                  </ElButton>
                </div>
              </template>
              <ElTable :data="feedback" border height="320">
                <ElTableColumn prop="feedbackType" label="类型" width="150" />
                <ElTableColumn prop="rootCause" label="归因" width="160" />
                <ElTableColumn prop="status" label="状态" width="120" />
                <ElTableColumn prop="comment" label="说明" min-width="220" show-overflow-tooltip />
              </ElTable>
            </ElCard>
          </ElCol>
          <ElCol :xl="12" :lg="12" :md="24" :sm="24" :xs="24">
            <ElCard shadow="never" class="panel">
              <template #header>
                <div class="panel-header">
                  <span>评估实验室</span>
                  <ElButton size="small" plain :loading="actionLoading" @click="startEvaluation">
                    发起评测
                  </ElButton>
                </div>
              </template>
              <ElTable :data="evaluation?.sets || []" border height="320">
                <ElTableColumn prop="name" label="评估集" min-width="220" show-overflow-tooltip />
                <ElTableColumn prop="setType" label="类型" width="120" />
                <ElTableColumn prop="caseCount" label="样本" width="90" />
                <ElTableColumn prop="status" label="状态" width="110" />
              </ElTable>
            </ElCard>
          </ElCol>
        </ElRow>
      </ElTabPane>

      <ElTabPane label="版本与发布" name="release">
        <ElRow :gutter="16">
          <ElCol :xl="12" :lg="12" :md="24" :sm="24" :xs="24">
            <ElCard shadow="never" class="panel">
              <template #header>Capability Bundle</template>
              <ElTable :data="bundles?.bundles || []" border height="320">
                <ElTableColumn prop="name" label="组合" min-width="220" show-overflow-tooltip />
                <ElTableColumn prop="riskLevel" label="风险" width="100" />
                <ElTableColumn prop="status" label="状态" width="130">
                  <template #default="{ row }">
                    <ElTag :type="statusType(String(row.status))" effect="plain">{{
                      row.status
                    }}</ElTag>
                  </template>
                </ElTableColumn>
              </ElTable>
            </ElCard>
          </ElCol>
          <ElCol :xl="12" :lg="12" :md="24" :sm="24" :xs="24">
            <ElCard shadow="never" class="panel">
              <template #header>
                <div class="panel-header">
                  <span>发布计划</span>
                  <ElSpace>
                    <ElButton
                      size="small"
                      plain
                      :loading="actionLoading"
                      @click="submitReleaseGate"
                    >
                      提交门禁
                    </ElButton>
                    <ElButton size="small" plain :loading="actionLoading" @click="startShadowRun">
                      Shadow
                    </ElButton>
                  </ElSpace>
                </div>
              </template>
              <ElTable :data="releases?.plans || []" border height="320">
                <ElTableColumn prop="id" label="发布单" min-width="170" show-overflow-tooltip />
                <ElTableColumn prop="riskLevel" label="风险" width="100" />
                <ElTableColumn prop="status" label="状态" width="150" />
                <ElTableColumn
                  prop="changeSummary"
                  label="摘要"
                  min-width="240"
                  show-overflow-tooltip
                />
              </ElTable>
            </ElCard>
          </ElCol>
        </ElRow>
      </ElTabPane>

      <ElTabPane label="交付治理" name="delivery">
        <ElRow :gutter="16">
          <ElCol :xl="8" :lg="8" :md="24" :sm="24" :xs="24">
            <ElCard shadow="never" class="panel">
              <template #header>
                <div class="panel-header">
                  <span>业务包门禁</span>
                  <ElButton
                    size="small"
                    plain
                    :loading="actionLoading"
                    @click="installBusinessPack"
                  >
                    安装演练
                  </ElButton>
                </div>
              </template>
              <ElDescriptions v-if="packValidation" :column="1" border>
                <ElDescriptionsItem label="整体状态">{{
                  packValidation.ok ? '通过' : '失败'
                }}</ElDescriptionsItem>
                <ElDescriptionsItem label="业务包数量">{{
                  packValidation.results.length
                }}</ElDescriptionsItem>
              </ElDescriptions>
            </ElCard>
          </ElCol>
          <ElCol :xl="8" :lg="8" :md="24" :sm="24" :xs="24">
            <ElCard shadow="never" class="panel">
              <template #header>
                <div class="panel-header">
                  <span>OCR 质量</span>
                  <ElSpace>
                    <ElButton
                      size="small"
                      plain
                      :disabled="!firstLowConfidenceField"
                      :loading="actionLoading"
                      @click="correctFirstOcrField"
                    >
                      字段纠错
                    </ElButton>
                    <ElButton size="small" plain :loading="actionLoading" @click="startOcrEvaluation">
                      OCR评测
                    </ElButton>
                  </ElSpace>
                </div>
              </template>
              <ElDescriptions v-if="ocrQuality" :column="1" border>
                <ElDescriptionsItem label="文件成功"
                  >{{ ocrQuality.fileLevel.success }}/{{
                    ocrQuality.fileLevel.total
                  }}</ElDescriptionsItem
                >
                <ElDescriptionsItem label="Job 成功">{{
                  ocrQuality.jobLevel?.success || 0
                }}/{{ ocrQuality.jobLevel?.total || 0 }}</ElDescriptionsItem>
                <ElDescriptionsItem label="低置信度字段">{{
                  ocrQuality.fieldLevel.lowConfidence
                }}</ElDescriptionsItem>
                <ElDescriptionsItem label="解析字段">
                  {{ ocrQuality.fieldLevel.parseFieldCount || 0 }} ·
                  平均置信 {{ percent(ocrQuality.fieldLevel.averageFieldConfidence) }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="字段冲突">
                  {{ ocrQuality.fieldLevel.conflictFieldCount || 0 }} · 缺证据
                  {{ ocrQuality.fieldLevel.evidenceMissingFieldCount || 0 }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="必需字段缺失">
                  {{ ocrQuality.fieldLevel.missingRequiredFieldCount || 0 }}
                  <span v-if="topMissingRequiredField">
                    · {{ topMissingRequiredField.fieldCode }} × {{ topMissingRequiredField.count }}
                  </span>
                </ElDescriptionsItem>
                <ElDescriptionsItem v-if="topOcrFieldCode" label="首要字段">
                  {{ topOcrFieldCode.fieldCode }} · {{ topOcrFieldCode.count }}
                </ElDescriptionsItem>
                <ElDescriptionsItem v-if="topOcrFieldFlag" label="字段质量标记">
                  {{ topOcrFieldFlag.flag }} · {{ topOcrFieldFlag.count }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="字段失败">{{
                  ocrQuality.failurePools?.fieldFailures?.length || 0
                }}</ElDescriptionsItem>
                <ElDescriptionsItem label="证据完整度">
                  {{ percent(ocrQuality.evidenceLevel?.averageEvidenceCompleteness) }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="缺证据项">
                  {{ ocrQuality.evidenceLevel?.missingEvidence || 0 }} · 字段
                  {{ ocrQuality.evidenceLevel?.fieldEvidenceMissing || 0 }} / 表格
                  {{ ocrQuality.evidenceLevel?.tableEvidenceMissing || 0 }} / 印章
                  {{ ocrQuality.evidenceLevel?.sealEvidenceMissing || 0 }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="正式表格">
                  {{ ocrQuality.tableLevel?.formalTableCount || 0 }}/{{
                    ocrQuality.tableLevel?.tableCount || 0
                  }}
                  · {{ percent(ocrQuality.tableLevel?.formalTableRate) }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="启发表格">
                  {{ ocrQuality.tableLevel?.heuristicTableCount || 0 }} ·
                  {{ percent(ocrQuality.tableLevel?.heuristicTableRate) }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="业务行">
                  {{ ocrQuality.tableLevel?.businessRowCount || 0 }} 行 ·
                  {{ ocrQuality.tableLevel?.cellCount || 0 }} cells
                </ElDescriptionsItem>
                <ElDescriptionsItem label="必需表格缺失">
                  {{ ocrQuality.tableLevel?.missingRequiredTableCount || 0 }}
                  <span v-if="topMissingRequiredTable">
                    · {{ topMissingRequiredTable.tableCode }} × {{ topMissingRequiredTable.count }}
                  </span>
                </ElDescriptionsItem>
                <ElDescriptionsItem label="印章可读">
                  {{ ocrQuality.sealLevel?.readableSealCount || 0 }}/{{
                    ocrQuality.sealLevel?.sealCount || 0
                  }}
                  · {{ percent(ocrQuality.sealLevel?.readableSealRate) }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="片段融合章">
                  {{ ocrQuality.sealLevel?.fragmentSealCount || 0 }} ·
                  {{ percent(ocrQuality.sealLevel?.fragmentSealRate) }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="期望章类型">
                  <span v-if="topMatchedExpectedSealType">
                    命中 {{ topMatchedExpectedSealType.sealType }} ×
                    {{ topMatchedExpectedSealType.count }}
                  </span>
                  <span v-else>命中 0</span>
                  <span v-if="topMissingExpectedSealType">
                    · 缺 {{ topMissingExpectedSealType.sealType }} ×
                    {{ topMissingExpectedSealType.count }}
                  </span>
                </ElDescriptionsItem>
                <ElDescriptionsItem label="视觉章复核">
                  {{ ocrQuality.sealLevel?.reviewRequiredCount || 0 }}/{{
                    ocrQuality.sealLevel?.visualCandidateCount || 0
                  }}
                  · {{ percent(ocrQuality.sealLevel?.visualCandidateReviewRate) }}
                </ElDescriptionsItem>
                <ElDescriptionsItem v-if="topOcrQualityReason" label="首要质量原因">
                  {{ topOcrQualityReason.reason }} · {{ topOcrQualityReason.count }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="人工修正率">{{
                  percent(ocrQuality.fieldLevel.manualCorrectionRate)
                }}</ElDescriptionsItem>
                <ElDescriptionsItem label="引擎缓存">{{
                  ocrQuality.cacheMetrics?.engineCacheHits || 0
                }}/{{ ocrQuality.cacheMetrics?.engineRunCount || 0 }} ·
                  {{ percent(ocrQuality.cacheMetrics?.engineCacheHitRate) }}</ElDescriptionsItem>
                <ElDescriptionsItem label="候选缓存">{{
                  ocrQuality.cacheMetrics?.variantCacheHits || 0
                }}/{{ ocrQuality.cacheMetrics?.engineRunCount || 0 }} ·
                  {{ percent(ocrQuality.cacheMetrics?.variantCacheHitRate) }}</ElDescriptionsItem>
                <ElDescriptionsItem label="引擎耗时">{{
                  ocrQuality.cacheMetrics?.totalDurationMs || 0
                }} ms</ElDescriptionsItem>
                <ElDescriptionsItem label="运行时">
                  <ElTag :type="ocrRuntimeDoctor?.ok ? 'success' : 'warning'" effect="plain">
                    {{ ocrRuntimeDoctor?.status || 'unknown' }}
                  </ElTag>
                </ElDescriptionsItem>
                <ElDescriptionsItem label="Doctor">{{
                  ocrRuntimeDoctor?.summary?.fail || 0
                }} fail / {{ ocrRuntimeDoctor?.summary?.warn || 0 }} warn</ElDescriptionsItem>
                <ElDescriptionsItem v-if="firstRuntimeIssue" label="首要问题">
                  {{ firstRuntimeIssue.name }}：{{ firstRuntimeIssue.message }}
                </ElDescriptionsItem>
              </ElDescriptions>
              <ElTable
                :data="ocrRuns"
                border
                height="220"
                class="mt-12px"
                @row-click="(row) => loadOcrRunDetail(String(row.id || row.jobId))"
              >
                <ElTableColumn prop="id" label="Job" min-width="150" show-overflow-tooltip />
                <ElTableColumn prop="status" label="状态" width="95">
                  <template #default="{ row }">
                    <ElTag :type="statusType(String(row.status))" effect="plain">{{
                      row.status
                    }}</ElTag>
                  </template>
                </ElTableColumn>
                <ElTableColumn prop="profileId" label="Profile" min-width="140" show-overflow-tooltip />
              </ElTable>
              <ElDescriptions v-if="selectedOcrRun" :column="1" border class="mt-12px">
                <ElDescriptionsItem label="结果">{{
                  selectedOcrRun.job.parseResultId || '-'
                }}</ElDescriptionsItem>
                <ElDescriptionsItem label="字段">{{
                  selectedOcrResultSummary.fieldCount || 0
                }}</ElDescriptionsItem>
                <ElDescriptionsItem label="纠错">{{
                  selectedOcrRun.corrections.length
                }}</ElDescriptionsItem>
                <ElDescriptionsItem label="候选图">{{
                  selectedOcrGeneratedVariants.length
                }}/{{ selectedOcrRequestedVariants.length }}</ElDescriptionsItem>
                <ElDescriptionsItem v-if="selectedOcrMissingVariants.length" label="缺失候选">
                  {{ selectedOcrMissingVariants.join(', ') }}
                </ElDescriptionsItem>
              </ElDescriptions>
              <ElTable
                v-if="selectedOcrEngineRows.length"
                :data="selectedOcrEngineRows"
                border
                height="180"
                class="mt-12px"
              >
                <ElTableColumn prop="engine" label="引擎" min-width="180" show-overflow-tooltip />
                <ElTableColumn prop="status" label="状态" width="90">
                  <template #default="{ row }">
                    <ElTag :type="statusType(String(row.status))" effect="plain">{{
                      row.status
                    }}</ElTag>
                  </template>
                </ElTableColumn>
                <ElTableColumn prop="durationMs" label="耗时" width="95" />
                <ElTableColumn label="缓存" width="120">
                  <template #default="{ row }">
                    <ElSpace size="small">
                      <ElTag v-if="row.engineCacheHit" size="small" type="success" effect="plain">
                        引擎
                      </ElTag>
                      <ElTag v-if="row.variantCacheHit" size="small" type="info" effect="plain">
                        候选
                      </ElTag>
                      <span v-if="!row.engineCacheHit && !row.variantCacheHit">-</span>
                    </ElSpace>
                  </template>
                </ElTableColumn>
              </ElTable>
              <ElTable
                v-if="ocrFieldFailureRows.length"
                :data="ocrFieldFailureRows"
                border
                height="180"
                class="mt-12px"
              >
                <ElTableColumn prop="code" label="字段问题" min-width="150" show-overflow-tooltip />
                <ElTableColumn prop="fieldName" label="字段" min-width="110" show-overflow-tooltip />
                <ElTableColumn prop="fieldValue" label="值" min-width="130" show-overflow-tooltip />
                <ElTableColumn prop="confidence" label="置信度" width="95" />
              </ElTable>
              <ElTable
                v-if="ocrMissingEvidenceRows.length"
                :data="ocrMissingEvidenceRows"
                border
                height="180"
                class="mt-12px"
              >
                <ElTableColumn prop="targetType" label="缺证据类型" width="110" />
                <ElTableColumn prop="targetId" label="目标" min-width="120" show-overflow-tooltip />
                <ElTableColumn prop="parseResultId" label="结果" min-width="150" show-overflow-tooltip />
                <ElTableColumn prop="profileId" label="Profile" min-width="140" show-overflow-tooltip />
              </ElTable>
            </ElCard>
          </ElCol>
          <ElCol :xl="8" :lg="8" :md="24" :sm="24" :xs="24">
            <ElCard shadow="never" class="panel">
              <template #header>
                <div class="panel-header">
                  <span>事故与验收</span>
                  <ElButton size="small" plain :loading="actionLoading" @click="updateFirstRca">
                    更新 RCA
                  </ElButton>
                </div>
              </template>
              <ElDescriptions :column="1" border>
                <ElDescriptionsItem label="事故数">{{ incidents.length }}</ElDescriptionsItem>
                <ElDescriptionsItem label="RCA">{{ rcaItems.length }}</ElDescriptionsItem>
                <ElDescriptionsItem label="验收报告">{{
                  acceptanceReports.length
                }}</ElDescriptionsItem>
                <ElDescriptionsItem label="发布计划">{{
                  releases?.plans.length || 0
                }}</ElDescriptionsItem>
              </ElDescriptions>
            </ElCard>
          </ElCol>
        </ElRow>
        <ElRow :gutter="16" class="mt-16px">
          <ElCol :span="24">
            <ElCard shadow="never" class="panel">
              <template #header>
                <div class="panel-header">
                  <span>OCR 评估门禁</span>
                  <ElSpace>
                    <ElTag
                      v-if="latestOcrEvalRun"
                      :type="latestOcrEvalOk ? 'success' : 'danger'"
                      effect="plain"
                    >
                      {{ latestOcrEvalOk ? '门禁通过' : '门禁失败' }}
                    </ElTag>
                    <ElButton size="small" plain :loading="actionLoading" @click="startOcrEvaluation">
                      重新评测
                    </ElButton>
                  </ElSpace>
                </div>
              </template>
              <ElAlert
                v-if="!latestOcrEvalRun"
                type="info"
                show-icon
                :closable="false"
                title="暂无 OCR 评估记录，请先发起 OCR评测。"
              />
              <template v-else>
                <div class="gate-summary">
                  <div class="gate-summary-item">
                    <span>Profile</span>
                    <strong>{{ latestOcrEvalRun.profileId || 'all' }}</strong>
                  </div>
                  <div class="gate-summary-item">
                    <span>平均分</span>
                    <strong>{{ scorePercent(latestOcrEvalSummary.averageScore) }}</strong>
                  </div>
                  <div class="gate-summary-item">
                    <span>样本</span>
                    <strong
                      >{{ latestOcrEvalSummary.passed || 0 }}/{{
                        latestOcrEvalCaseTotal
                      }}</strong
                    >
                  </div>
                  <div class="gate-summary-item">
                    <span>门禁失败</span>
                    <strong>{{ ocrThresholdFailureRows.length }}</strong>
                  </div>
                </div>
                <ElRow :gutter="12" class="mt-12px">
                  <ElCol :xl="12" :lg="12" :md="24" :sm="24" :xs="24">
                    <ElTable :data="ocrScenarioRows" border height="220">
                      <ElTableColumn prop="scenario" label="场景" min-width="190" show-overflow-tooltip />
                      <ElTableColumn prop="averageScore" label="分数" width="95">
                        <template #default="{ row }">{{ scorePercent(row.averageScore) }}</template>
                      </ElTableColumn>
                      <ElTableColumn prop="passed" label="通过" width="90" />
                      <ElTableColumn prop="failed" label="失败" width="90" />
                      <ElTableColumn prop="ok" label="门禁" width="95">
                        <template #default="{ row }">
                          <ElTag :type="row.ok ? 'success' : 'danger'" effect="plain">
                            {{ row.ok ? '通过' : '失败' }}
                          </ElTag>
                        </template>
                      </ElTableColumn>
                    </ElTable>
                  </ElCol>
                  <ElCol :xl="12" :lg="12" :md="24" :sm="24" :xs="24">
                    <ElTable
                      v-if="ocrThresholdFailureRows.length"
                      :data="ocrThresholdFailureRows"
                      border
                      height="220"
                    >
                      <ElTableColumn prop="scope" label="范围" min-width="150" show-overflow-tooltip />
                      <ElTableColumn prop="metric" label="指标" min-width="170" show-overflow-tooltip />
                      <ElTableColumn prop="actual" label="实际" width="95">
                        <template #default="{ row }">{{ scorePercent(row.actual) }}</template>
                      </ElTableColumn>
                      <ElTableColumn prop="expected" label="门槛" width="95">
                        <template #default="{ row }">{{ scorePercent(row.expected) }}</template>
                      </ElTableColumn>
                    </ElTable>
                    <ElTable
                      v-else-if="ocrFindingCountRows.length"
                      :data="ocrFindingCountRows"
                      border
                      height="220"
                    >
                      <ElTableColumn prop="scope" label="范围" min-width="150" show-overflow-tooltip />
                      <ElTableColumn prop="code" label="失败原因" min-width="230" show-overflow-tooltip />
                      <ElTableColumn prop="count" label="次数" width="90" />
                    </ElTable>
                    <ElTable v-else :data="failedOcrCaseRows" border height="220">
                      <ElTableColumn prop="caseId" label="Case" min-width="190" show-overflow-tooltip />
                      <ElTableColumn prop="scenario" label="场景" min-width="160" show-overflow-tooltip />
                      <ElTableColumn prop="score" label="分数" width="95">
                        <template #default="{ row }">{{ scorePercent(row.score) }}</template>
                      </ElTableColumn>
                      <ElTableColumn prop="finding" label="诊断" min-width="160" show-overflow-tooltip />
                    </ElTable>
                  </ElCol>
                </ElRow>
              </template>
            </ElCard>
          </ElCol>
        </ElRow>
        <ElRow :gutter="16" class="mt-16px">
          <ElCol :xl="12" :lg="12" :md="24" :sm="24" :xs="24">
            <ElCard shadow="never" class="panel">
              <template #header>数据安全</template>
              <ElDescriptions :column="1" border>
                <ElDescriptionsItem label="访问授权">{{ accessGrants.length }}</ElDescriptionsItem>
                <ElDescriptionsItem label="导出申请">{{
                  costGovernance?.exports.length || 0
                }}</ElDescriptionsItem>
                <ElDescriptionsItem label="导出水印">启用</ElDescriptionsItem>
              </ElDescriptions>
            </ElCard>
          </ElCol>
          <ElCol :xl="12" :lg="12" :md="24" :sm="24" :xs="24">
            <ElCard shadow="never" class="panel">
              <template #header>成本预算</template>
              <ElDescriptions :column="1" border>
                <ElDescriptionsItem label="预算数">{{
                  costGovernance?.budgets.length || 0
                }}</ElDescriptionsItem>
                <ElDescriptionsItem label="Run 数">{{
                  costGovernance?.usage.runCount || 0
                }}</ElDescriptionsItem>
                <ElDescriptionsItem label="估算费用">{{
                  costGovernance?.usage.estimatedPrice || 0
                }}</ElDescriptionsItem>
              </ElDescriptions>
            </ElCard>
          </ElCol>
        </ElRow>
      </ElTabPane>
    </ElTabs>
  </div>
</template>

<style scoped lang="less">
.fde-console {
  min-height: 100%;
  padding: 16px;
  background: #f5f7fb;
}

.page-title,
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.page-title {
  margin-bottom: 16px;
}

.page-title h1 {
  margin: 0;
  font-size: 24px;
  color: var(--el-text-color-primary);
}

.page-title p,
.metric-label {
  margin: 4px 0 0;
  color: var(--el-text-color-secondary);
}

.metric-card,
.panel {
  border-radius: 8px;
}

.metric-card strong {
  display: block;
  margin-top: 8px;
  font-size: 24px;
  color: var(--el-text-color-primary);
}

.gate-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.gate-summary-item {
  min-height: 72px;
  padding: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-bg-color);
}

.gate-summary-item span {
  display: block;
  color: var(--el-text-color-secondary);
}

.gate-summary-item strong {
  display: block;
  margin-top: 8px;
  font-size: 18px;
  color: var(--el-text-color-primary);
}

@media (max-width: 768px) {
  .gate-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
