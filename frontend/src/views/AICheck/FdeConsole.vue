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
  createFdeEvaluationRunApi,
  getFdeAiRunApi,
  getFdeCapabilityBundlesApi,
  getFdeDashboardApi,
  getFdeEvaluationSetsApi,
  getFdeOcrQualityApi,
  listFdeAcceptanceReportsApi,
  listFdeAiRunsApi,
  listFdeFeedbackApi,
  listFdeIncidentsApi,
  listFdeReleasesApi,
  replayFdeAiRunApi,
  triageFdeFeedbackApi,
  validateFdeBusinessPacksApi
} from '@/api/aicheck'
import type {
  BusinessPackValidateAllPayload,
  FdeAiRun,
  FdeAiRunDetailPayload,
  FdeCapabilityBundlePayload,
  FdeDashboardPayload,
  FdeEvaluationPayload,
  FdeFeedback,
  FdeOcrQualityPayload,
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
const incidents = ref<Array<Record<string, unknown>>>([])
const acceptanceReports = ref<Array<Record<string, unknown>>>([])
const packValidation = ref<BusinessPackValidateAllPayload | null>(null)

const percent = (value?: number | string) => {
  const numeric = Number(value || 0)
  if (Number.isNaN(numeric)) return value || '-'
  return `${Math.round(numeric * 100)}%`
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
      incidentRes,
      acceptanceRes,
      validationRes
    ] = await Promise.all([
      getFdeDashboardApi(),
      listFdeAiRunsApi({ pageSize: 20 }),
      listFdeFeedbackApi(),
      getFdeEvaluationSetsApi(),
      getFdeCapabilityBundlesApi(),
      listFdeReleasesApi(),
      getFdeOcrQualityApi(),
      listFdeIncidentsApi(),
      listFdeAcceptanceReportsApi(),
      validateFdeBusinessPacksApi()
    ])
    dashboard.value = dashboardRes.data
    aiRuns.value = aiRunRes.data.items
    feedback.value = feedbackRes.data
    evaluation.value = evaluationRes.data
    bundles.value = bundleRes.data
    releases.value = releaseRes.data
    ocrQuality.value = ocrRes.data
    incidents.value = incidentRes.data
    acceptanceReports.value = acceptanceRes.data
    packValidation.value = validationRes.data
    if (aiRuns.value[0]) {
      await loadRunDetail(aiRuns.value[0].id)
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
              <template #header>Trace 明细</template>
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
              <template #header>发布计划</template>
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
              <template #header>业务包门禁</template>
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
              <template #header>OCR 质量</template>
              <ElDescriptions v-if="ocrQuality" :column="1" border>
                <ElDescriptionsItem label="文件成功"
                  >{{ ocrQuality.fileLevel.success }}/{{
                    ocrQuality.fileLevel.total
                  }}</ElDescriptionsItem
                >
                <ElDescriptionsItem label="低置信度字段">{{
                  ocrQuality.fieldLevel.lowConfidence
                }}</ElDescriptionsItem>
                <ElDescriptionsItem label="人工修正率">{{
                  percent(ocrQuality.fieldLevel.manualCorrectionRate)
                }}</ElDescriptionsItem>
              </ElDescriptions>
            </ElCard>
          </ElCol>
          <ElCol :xl="8" :lg="8" :md="24" :sm="24" :xs="24">
            <ElCard shadow="never" class="panel">
              <template #header>事故与验收</template>
              <ElDescriptions :column="1" border>
                <ElDescriptionsItem label="事故数">{{ incidents.length }}</ElDescriptionsItem>
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
</style>
