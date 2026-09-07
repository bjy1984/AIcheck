<script setup lang="ts">
/**
 * P12 F4 盲审页：盲审人只看到项目/节点，不看 AI 结论与常规结论；判完才 reveal。
 * 橡皮图章指数 = 盲审差异率 − 同批常规差异率（优化计划 §17.3），不趋零，超阈值报警。
 */
import { computed, onMounted, ref } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElEmpty,
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
  decideFdeBlindReviewApi,
  listFdeBlindReviewTasksApi,
  sampleFdeBlindReviewApi,
  type FdeBlindReviewTask,
  type FdeRubberStampIndex
} from '@/api/aicheck'
import StaticPageShell from './components/StaticPageShell.vue'
import {
  ALERT_THRESHOLD,
  RESULT_OPTIONS,
  formatPct,
  indexAlert as computeIndexAlert,
  indexLabel as computeIndexLabel
} from './fdeBlindReviewModel'
import { useUserStore } from '@/store/modules/user'
import { getAicheckRoleLabel } from '@/utils/roleAccess'

const userStore = useUserStore()
const userLabel = computed(() => {
  const user = userStore.getUserInfo
  return `${user?.displayName || user?.username || '当前用户'} · ${getAicheckRoleLabel(user?.role)}`
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
    ElMessage.success(`本周抽到 ${res.data?.sampled || 0} 个节点`)
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
    note: `指数 = 盲审差异率 − 同批常规差异率。样本 ≥5 且指数 < ${ALERT_THRESHOLD} 视为常规审查在照抄 AI，触发培训与展示层调整。`
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
      search-scope="admin"
      task-area="admin"
      :user-label="userLabel"
      workspace-mode="wide"
      right-panel-mode="drawer"
      right-toggle-label="指数"
      boundary-collapsed-default
      :top-stats="[
        { label: '待盲审', value: openCount, tone: 'orange' },
        { label: '已判', value: doneCount, tone: 'green' },
        { label: '指数', value: indexLabel, tone: indexAlert ? 'red' : 'blue' }
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
      right-subtitle="每周随机 10% 已完成节点"
      :right-cards="rightCards"
      @menu-select="handleMenuSelect"
    >
      <div class="page-title">
        <div>
          <h1>盲审抽样</h1>
          <p>独立判定后才揭示 AI 与常规结论；差异越小，橡皮图章风险越高</p>
        </div>
        <ElSpace>
          <span class="muted">比例</span>
          <ElInputNumber v-model="ratio" :min="1" :max="100" size="small" style="width: 100px" />
          <span class="muted">% · 近</span>
          <ElInputNumber
            v-model="windowDays"
            :min="0"
            :max="90"
            size="small"
            style="width: 100px"
          />
          <span class="muted">天</span>
          <ElButton size="small" type="primary" plain :loading="sampling" @click="sample">
            抽样
          </ElButton>
          <ElButton size="small" plain :loading="loading" @click="load">刷新</ElButton>
        </ElSpace>
      </div>

      <ElAlert
        v-if="indexAlert"
        type="error"
        show-icon
        :closable="false"
        title="橡皮图章指数低于阈值：常规审查与 AI 几乎完全一致，需安排培训并调整结论卡展示"
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
        <ElEmpty v-if="!loading && !visibleTasks.length" description="没有盲审任务，点右上角抽样" />
        <ElTable v-else :data="visibleTasks" border row-key="id">
          <ElTableColumn prop="id" label="任务" width="130" show-overflow-tooltip />
          <ElTableColumn label="节点" min-width="160">
            <template #default="{ row }">
              <div class="cell-stack">
                <span>{{ row.projectId }} · 节点 {{ row.nodeId }}</span>
                <span class="muted">批次 {{ row.batchId }}</span>
              </div>
            </template>
          </ElTableColumn>
          <ElTableColumn label="状态" width="90">
            <template #default="{ row }">
              <ElTag size="small" :type="row.status === 'done' ? 'success' : 'warning'">
                {{ row.status === 'done' ? '已判' : '待判' }}
              </ElTag>
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
