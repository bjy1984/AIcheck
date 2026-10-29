<script setup lang="ts">
/**
 * P12 F4 盲审页：盲审人只看到项目/节点，不看 AI 结论与常规结论；判完才 reveal。
 * 橡皮图章指数 = 盲审差异率 − 同批常规差异率（优化计划 §17.3），不趋零，超阈值报警。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElEmpty,
  ElDrawer,
  ElInput,
  ElInputNumber,
  ElMessage,
  ElOption,
  ElSelect,
  ElSpace,
  ElTable,
  ElTableColumn,
  ElTag
} from 'element-plus'
import {
  getDocumentOriginalBlobApi,
  decideFdeBlindReviewApi,
  listFdeBlindReviewTasksApi,
  sampleFdeBlindReviewApi,
  type FdeBlindReviewTask,
  type FdeRubberStampIndex
} from '@/api/aicheck'
import { useRouter } from 'vue-router'
import {
  getBlindReviewMaterialsApi,
  type BlindReviewMaterial,
  type BlindReviewMaterials
} from '@/api/aicheck/blindReviewMaterials'
import StaticPageShell from './components/StaticPageShell.vue'
import StatusTag from './components/StatusTag.vue'
import { Icon } from '@/components/Icon'
import {
  ALERT_THRESHOLD,
  RESULT_OPTIONS,
  formatPct,
  indexAlert as computeIndexAlert,
  indexLabel as computeIndexLabel
} from './fdeBlindReviewModel'
import { useUserStore } from '@/store/modules/user'
import { getAicheckRoleLabel } from '@/utils/roleAccess'

const router = useRouter()
const materialsVisible = ref(false)
const materialsLoading = ref(false)
const materialsError = ref('')
const materials = ref<BlindReviewMaterials | null>(null)
const materialsTask = ref<FdeBlindReviewTask | null>(null)
const selectedMaterial = ref<BlindReviewMaterial | null>(null)
const materialUrl = ref('')
const materialType = ref('')
const materialLoading = ref(false)
const materialError = ref('')
const materialDownloading = ref(false)
const materialDownloadError = ref('')
let materialsRequest = 0
let materialRequest = 0
const clearMaterial = () => {
  materialRequest++
  if (materialUrl.value) URL.revokeObjectURL(materialUrl.value)
  materialUrl.value = ''
  selectedMaterial.value = null
  materialError.value = ''
  materialDownloadError.value = ''
  materialDownloading.value = false
  materialLoading.value = false
}
const closeMaterials = () => {
  materialsRequest++
  clearMaterial()
}
const previewMaterial = async (item: BlindReviewMaterial) => {
  clearMaterial()
  selectedMaterial.value = item
  const requestId = ++materialRequest
  materialLoading.value = true
  try {
    const response = await getDocumentOriginalBlobApi(item.originalUrl)
    if (requestId !== materialRequest) return
    materialUrl.value = URL.createObjectURL(response.data)
    materialType.value = response.data.type
  } catch (err) {
    if (requestId === materialRequest)
      materialError.value =
        err instanceof Error ? err.message : '原始版本加载失败，请重试或联系资料管理员。'
  } finally {
    if (requestId === materialRequest) materialLoading.value = false
  }
}
const downloadMaterial = async (item: BlindReviewMaterial) => {
  const requestId = materialRequest
  materialDownloading.value = true
  materialDownloadError.value = ''
  try {
    const response = await getDocumentOriginalBlobApi(item.downloadUrl)
    if (requestId !== materialRequest) return
    const url = URL.createObjectURL(response.data)
    const link = document.createElement('a')
    link.href = url
    link.download = item.fileName
    link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (err) {
    if (requestId === materialRequest)
      materialDownloadError.value =
        err instanceof Error ? err.message : '原始文件下载失败，请重试。'
  } finally {
    if (requestId === materialRequest) materialDownloading.value = false
  }
}
const openMaterials = async (task: FdeBlindReviewTask) => {
  clearMaterial()
  const requestId = ++materialsRequest
  materialsTask.value = task
  materialsVisible.value = true
  materialsLoading.value = true
  materialsError.value = ''
  materials.value = null
  try {
    const response = await getBlindReviewMaterialsApi(task.id)
    if (requestId !== materialsRequest) return
    materials.value = response.data
  } catch (err) {
    if (requestId === materialsRequest)
      materialsError.value = err instanceof Error ? err.message : '资料清单加载失败，请重试。'
  } finally {
    if (requestId === materialsRequest) materialsLoading.value = false
  }
}
onBeforeUnmount(closeMaterials)

const userStore = useUserStore()
const userLabel = computed(() => {
  const user = userStore.getUserInfo
  const name = user?.displayName || user?.username || '当前用户'
  const role = getAicheckRoleLabel(user?.role)
  return name === role ? name : `${name} · ${role}`
})
const reviewerName = computed(() => {
  const user = userStore.getUserInfo
  return user?.displayName || user?.username || ''
})

const loading = ref(false)
const sampling = ref(false)
const saving = ref('')
const error = ref('')
const tasks = ref<FdeBlindReviewTask[]>([])
const index = ref<FdeRubberStampIndex | null>(null)
const statusFilter = ref<'open' | 'done' | ''>('open')
const ratio = ref(10)
const windowDays = ref(7)
const drafts = ref<Record<string, { result: string; comment: string }>>({})

const draftFor = (task: FdeBlindReviewTask) => {
  if (!drafts.value[task.id]) drafts.value[task.id] = { result: '', comment: '' }
  return drafts.value[task.id]
}

const visibleTasks = computed(() =>
  tasks.value.filter((task) => !statusFilter.value || task.status === statusFilter.value)
)
const openCount = computed(() => tasks.value.filter((task) => task.status === 'open').length)
const doneCount = computed(() => tasks.value.filter((task) => task.status === 'done').length)

const indexLabel = computed(() => computeIndexLabel(index.value))
const indexAlert = computed(() => computeIndexAlert(index.value))

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    const res = await listFdeBlindReviewTasksApi({ reveal: true })
    tasks.value = res.data?.tasks || []
    index.value = res.data?.rubberStampIndex || null
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载盲审任务失败'
  } finally {
    loading.value = false
  }
}

const sample = async () => {
  sampling.value = true
  try {
    const res = await sampleFdeBlindReviewApi({
      ratio: ratio.value / 100,
      windowDays: windowDays.value || null
    })
    ElMessage.success(`本次抽到 ${res.data?.sampled || 0} 个节点`)
    await load()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '抽样失败')
  } finally {
    sampling.value = false
  }
}

const decide = async (task: FdeBlindReviewTask) => {
  const draft = draftFor(task)
  if (!draft.result) {
    ElMessage.warning('先给出独立结论。')
    return
  }
  saving.value = task.id
  try {
    const res = await decideFdeBlindReviewApi(task.id, {
      result: draft.result,
      reviewerName: reviewerName.value || undefined,
      comment: draft.comment || undefined
    })
    const updated = res.data?.task
    if (updated) tasks.value = tasks.value.map((item) => (item.id === task.id ? updated : item))
    index.value = res.data?.rubberStampIndex || index.value
    delete drafts.value[task.id]
    ElMessage.success('已记录盲审结论')
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '提交失败')
  } finally {
    saving.value = ''
  }
}

const menuSections = computed(() => [
  {
    id: 'status',
    title: '任务',
    defaultOpen: true,
    items: [
      {
        index: 'status:open',
        label: '待盲审',
        badge: String(openCount.value),
        active: statusFilter.value === 'open'
      },
      {
        index: 'status:done',
        label: '已判',
        badge: String(doneCount.value),
        active: statusFilter.value === 'done'
      },
      {
        index: 'status:',
        label: '全部',
        badge: String(tasks.value.length),
        active: statusFilter.value === ''
      }
    ]
  }
])
const handleMenuSelect = (item: { index?: string }) => {
  const key = item?.index || ''
  if (key.startsWith('status:'))
    statusFilter.value = key.slice('status:'.length) as 'open' | 'done' | ''
}

const rightCards = computed(() => [
  {
    title: '橡皮图章指数',
    rows: [
      { label: '指数', value: indexLabel.value },
      { label: '盲审差异率', value: formatPct(index.value?.blindDivergence) },
      { label: '常规差异率', value: formatPct(index.value?.regularDivergence) },
      { label: '样本数', value: String(index.value?.sampleSize || 0) }
    ],
    note: `指数 = 盲审差异率 − 同批常规差异率。样本 ≥5 且指数 < ${ALERT_THRESHOLD} 提示需复核常规审查的独立性，结合样本进一步确认。`
  }
])

onMounted(load)
</script>

<template>
  <div class="blind-review">
    <StaticPageShell
      :refreshing="loading"
      brand-mark="盲"
      title="盲审抽样"
      :status="loading ? '加载中' : `${openCount} 待判`"
      :status-tone="loading ? 'orange' : openCount ? 'orange' : 'green'"
      search-placeholder="搜索项目、节点"
      search-scope="fde"
      task-area="fde"
      :user-label="userLabel"
      workspace-mode="wide"
      right-panel-mode="drawer"
      right-collapsed-default
      right-toggle-label="盲审质量"
      boundary-collapsed-default
      :top-stats="[
        { label: '待盲审', value: openCount, tone: 'orange' },
        { label: '已判', value: doneCount, tone: 'green' }
      ]"
      menu-title="盲审任务"
      menu-root="FDE 控制台"
      :menu-sections="menuSections"
      boundary-title="盲审规则"
      boundary-badge="不显示 AI 结论"
      boundary-tone="orange"
      :boundary-rows="[
        { label: '谁来判', value: '不是该节点常规审查人的另一名审查人' },
        { label: '看什么', value: '只看资料，不看 AI 与常规结论' }
      ]"
      right-title="橡皮图章指数"
      :right-subtitle="`抽样比例 ${ratio}% · ${windowDays ? `近 ${windowDays} 天` : '全部时间'}`"
      :right-cards="rightCards"
      @menu-select="handleMenuSelect"
    >
      <div class="page-title">
        <div>
          <h1>盲审抽样</h1>
          <p>依据原始资料独立判定，提交后可查看与 AI、常规审查的差异。</p>
        </div>
        <ElSpace wrap>
          <ElButton size="small" @click="router.push('/fde/dashboard')">返回 FDE 总览</ElButton>
          <span class="muted">比例</span>
          <ElInputNumber
            aria-label="抽样比例（百分比）"
            v-model="ratio"
            :min="1"
            :max="100"
            size="small"
            style="width: 100px"
          />
          <span class="muted">% · 近</span>
          <ElInputNumber
            aria-label="抽样时间窗口（天，0为全部）"
            v-model="windowDays"
            :min="0"
            :max="90"
            size="small"
            style="width: 100px"
          />
          <span class="muted">天（0 表示全部时间）</span>
          <ElButton size="small" type="primary" plain :loading="sampling" @click="sample">
            抽样
          </ElButton>
          <ElButton size="small" plain :loading="loading" @click="load"
            ><Icon v-if="!loading" icon="vi-ep:refresh" :size="16" aria-hidden="true" /><span
              >刷新</span
            ></ElButton
          >
        </ElSpace>
      </div>

      <ElAlert
        v-if="indexAlert"
        type="error"
        show-icon
        :closable="false"
        title="盲审质量指标达到复核阈值，请在“盲审质量”中查看样本与差异；当前任务仍须独立判定。"
        class="mb-12px"
      />
      <ElAlert
        v-if="error"
        type="error"
        show-icon
        :closable="false"
        :title="error"
        class="mb-12px"
      />

      <ElCard shadow="never" class="panel">
        <ElEmpty
          v-if="!loading && !visibleTasks.length"
          :description="
            statusFilter === 'done'
              ? '暂无已完成的盲审；可切换待判查看任务'
              : '暂无待判任务，可调整时间与比例后抽样'
          "
        />
        <ElTable v-else :data="visibleTasks" border row-key="id">
          <ElTableColumn label="节点" min-width="160">
            <template #default="{ row }">
              <div class="cell-stack">
                <span>{{ row.projectId }} · 节点 {{ row.nodeId }}</span>
                <details class="record-references">
                  <summary>任务与批次编号</summary>
                  <div>任务：{{ row.id }}</div>
                  <div>批次：{{ row.batchId }}</div>
                </details>
              </div>
            </template>
          </ElTableColumn>
          <ElTableColumn label="审查依据" width="130">
            <template #default="{ row }">
              <ElButton size="small" @click="openMaterials(row)">查看原始资料</ElButton>
            </template>
          </ElTableColumn>
          <ElTableColumn label="状态" width="90">
            <template #default="{ row }">
              <StatusTag
                size="small"
                :status="row.status"
                :label="row.status === 'done' ? '已判' : '待判'"
              />
            </template>
          </ElTableColumn>
          <ElTableColumn label="独立结论" min-width="320">
            <template #default="{ row }">
              <div v-if="row.status === 'done'" class="cell-stack">
                <span>
                  盲审：<strong>{{ row.blindResult }}</strong>
                  <span class="muted">（{{ row.blindReviewerName || '—' }}）</span>
                </span>
                <span class="muted"
                  >AI：{{ row.aiResult || '—' }} · 常规：{{ row.regularResult || '—' }}</span
                >
                <span v-if="row.blindComment" class="muted">{{ row.blindComment }}</span>
              </div>
              <ElSpace v-else wrap>
                <ElSelect
                  v-model="draftFor(row).result"
                  size="small"
                  placeholder="结论"
                  style="width: 130px"
                >
                  <ElOption
                    v-for="option in RESULT_OPTIONS"
                    :key="option"
                    :value="option"
                    :label="option"
                  />
                </ElSelect>
                <ElInput
                  v-model="draftFor(row).comment"
                  size="small"
                  placeholder="依据（可选）"
                  style="width: 220px"
                />
              </ElSpace>
            </template>
          </ElTableColumn>
          <ElTableColumn label="差异" width="120">
            <template #default="{ row }">
              <template v-if="row.status === 'done'">
                <ElTag size="small" :type="row.divergesFromAi ? 'danger' : 'info'" effect="plain">
                  {{ row.divergesFromAi ? '与 AI 不同' : '与 AI 相同' }}
                </ElTag>
              </template>
              <span v-else class="muted">—</span>
            </template>
          </ElTableColumn>
          <ElTableColumn label="" width="90" fixed="right">
            <template #default="{ row }">
              <ElButton
                v-if="row.status === 'open'"
                size="small"
                type="primary"
                plain
                :loading="saving === row.id"
                @click="decide(row)"
              >
                提交
              </ElButton>
            </template>
          </ElTableColumn>
        </ElTable>
      </ElCard>
      <ElDrawer
        v-model="materialsVisible"
        title="盲审原始资料"
        size="min(980px, 95vw)"
        append-to-body
        @close="closeMaterials"
      >
        <p v-if="materialsTask"
          >{{ materialsTask.projectId }} · 节点 {{ materialsTask.nodeId }} · 任务
          {{ materialsTask.id }}</p
        >
        <ElAlert
          type="info"
          :closable="false"
          title="只展示该次审查输入的原始资料版本，不展示 AI 与常规结论。"
        />
        <p v-if="materialsLoading" role="status">正在加载资料清单…</p>
        <ElAlert
          v-if="materialsError"
          type="error"
          :closable="false"
          :title="materialsError"
          class="mt-12px"
        >
          <ElButton v-if="materialsTask" @click="openMaterials(materialsTask)"
            >重试资料清单</ElButton
          >
        </ElAlert>
        <ElAlert
          v-if="materials?.unavailableReason"
          type="warning"
          :closable="false"
          :title="materials.unavailableReason"
          class="mt-12px"
        />
        <ElAlert
          v-if="materials?.unavailableCount"
          type="warning"
          :closable="false"
          :title="`${materials.unavailableCount} 个原始版本缺失或无权访问，请联系管理员核实。`"
          class="mt-12px"
        />
        <ElTable
          v-if="materials"
          :data="materials.materials"
          border
          class="mt-12px"
          empty-text="暂无可确认的原始资料"
        >
          <ElTableColumn prop="fileName" label="原始文件" min-width="180" />
          <ElTableColumn prop="documentVersionId" label="审查时版本" min-width="180" />
          <ElTableColumn label="操作" width="110" fixed="right">
            <template #default="{ row }"
              ><ElButton size="small" @click="previewMaterial(row)">查看此版本</ElButton></template
            >
          </ElTableColumn>
        </ElTable>
        <h3 v-if="selectedMaterial"
          >{{ selectedMaterial.fileName }} · {{ selectedMaterial.documentVersionId }}</h3
        >
        <p v-if="materialLoading" role="status">正在加载原文…</p>
        <ElAlert v-if="materialError" type="error" :title="materialError" :closable="false">
          <ElButton v-if="selectedMaterial" @click="previewMaterial(selectedMaterial)"
            >重试原文</ElButton
          >
        </ElAlert>
        <ElButton
          v-if="selectedMaterial"
          :loading="materialDownloading"
          @click="downloadMaterial(selectedMaterial)"
          ><Icon
            v-if="!materialDownloading"
            icon="vi-ep:download"
            :size="16"
            aria-hidden="true"
          /><span>下载此版本原始文件</span></ElButton
        >
        <ElAlert
          v-if="materialDownloadError"
          type="error"
          :closable="false"
          :title="materialDownloadError"
        />
        <template v-if="materialUrl">
          <iframe
            v-if="materialType === 'application/pdf'"
            :src="materialUrl"
            title="盲审原始 PDF"
            style="width: 100%; height: 65vh; border: 0"
          ></iframe>
          <img
            v-else-if="materialType.startsWith('image/')"
            :src="materialUrl"
            :alt="selectedMaterial?.fileName"
            style="max-width: 100%"
          />
          <p v-else>此格式请下载后使用对应软件查看。</p>
        </template>
      </ElDrawer>
    </StaticPageShell>
  </div>
</template>

<style scoped lang="less">
.blind-review {
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

  .panel {
    border-radius: 8px;
  }

  .record-references {
    font-size: 12px;
    color: var(--el-text-color-secondary);
    overflow-wrap: anywhere;

    summary {
      cursor: pointer;
    }
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
