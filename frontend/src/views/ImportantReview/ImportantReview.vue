<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCheckbox,
  ElCollapse,
  ElCollapseItem,
  ElDialog,
  ElDrawer,
  ElEmpty,
  ElInput,
  ElMessage,
  ElPagination,
  ElSwitch,
  ElTable,
  ElTableColumn,
  ElTag
} from 'element-plus'
import { Document, Upload } from '@element-plus/icons-vue'
import { listReviewDocuments, type ReviewDocument } from '@/api/aicheck/reviewDocuments'
import {
  importantReviewApi,
  type ImportantRule,
  type ImportantRun,
  type NodeRecommendation,
  type ImportantEvidence
} from '@/api/aicheck/importantReview'
import type { EvidenceLink } from '@/types/aicheck'
import router from '@/router'
import EvidenceLocatorDialog from '@/views/AICheck/components/EvidenceLocatorDialog.vue'
import { getAicheckErrorMessage } from '@/utils/aicheckError'
import { parseStatus, executionStatus, nodeConclusion, tagType } from './presentation'
import { uploadImportantFiles } from './upload'
import ImportantResults from './ImportantResults.vue'

const props = defineProps<{ projectId: string; active: boolean }>()
const files = ref<ReviewDocument[]>([])
const selected = ref<Record<string, ReviewDocument>>({})
const keyword = ref('')
const onlySelected = ref(false)
const page = ref(1)
const total = ref(0)
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const pollingError = ref('')
const enabled = ref(false)
const disabledReason = ref('')
const catalog = ref<ImportantRule[]>([])
const recommendations = ref<NodeRecommendation[]>([])
const selectedNodes = ref<number[]>([])
const nodeFiles = ref<Record<number, string[]>>({})
const runs = ref<ImportantRun[]>([])
const currentRunIds = ref<string[]>()
const collapsed = ref(false)
const rule = ref<ImportantRule>()
const fileNode = ref<ImportantRule>()
const evidence = ref<EvidenceLink>()
const evidenceVisible = ref(false)
const evidenceLabel = ref('')
const expanded = ref<string[]>([])
const resultFilter = ref('全部')
const input = ref<HTMLInputElement>()
const startErrors = ref<Array<{ nodeId: number; message: string }>>([])
const pendingNodes = ref<number[]>([])
const attempts = new Map<string, string>()
let generation = 0
let listGeneration = 0
let pollTimer: ReturnType<typeof setTimeout> | undefined
const selectedFiles = computed(() => Object.values(selected.value))
const chosenVersions = computed(() => selectedFiles.value.map((file) => file.currentVersionId))
const shownFiles = computed(() =>
  onlySelected.value
    ? selectedFiles.value
        .filter((file) => file.fileName.includes(keyword.value))
        .slice((page.value - 1) * 10, page.value * 10)
    : files.value
)
const shownTotal = computed(() =>
  onlySelected.value
    ? selectedFiles.value.filter((file) => file.fileName.includes(keyword.value)).length
    : total.value
)
const groups = computed(() =>
  ['设计文件', '元件与材料', '焊接'].map((name) => ({
    name,
    nodes: catalog.value.filter((node) => node.group === name)
  }))
)
const candidates = (id: number) => recommendations.value.find((node) => node.nodeId === id)
const versionsFor = (id: number) =>
  (nodeFiles.value[id] || chosenVersions.value).filter((version) =>
    Boolean(selected.value[version])
  )
const allVisibleSelected = computed(
  () =>
    shownFiles.value.length > 0 &&
    shownFiles.value.every((file) => !!selected.value[file.currentVersionId])
)
const filteredRuns = computed(() =>
  runs.value.filter(
    (run) =>
      resultFilter.value === '全部' ||
      (resultFilter.value === '未完成'
        ? executionStatus(run.status) !== '已完成'
        : ['不符合', '证据不足', '预警', '待人工复核'].includes(nodeConclusion(run)))
  )
)
const running = computed(() =>
  runs.value.some((run) => ['排队中', '审查中'].includes(executionStatus(run.status)))
)
const canStart = computed(
  () =>
    enabled.value &&
    selectedNodes.value.length > 0 &&
    selectedFiles.value.length > 0 &&
    !busy.value &&
    !running.value &&
    selectedNodes.value.every((id) => versionsFor(id).length > 0)
)

function searchFiles() {
  page.value = 1
  void loadFiles()
}
async function loadFiles() {
  const context = generation,
    search = ++listGeneration
  if (!props.projectId || onlySelected.value) {
    loading.value = false
    return
  }
  loading.value = true
  try {
    const response = await listReviewDocuments(props.projectId, {
      keyword: keyword.value.trim(),
      page: page.value,
      pageSize: 10
    })
    if (context !== generation || search !== listGeneration) return
    files.value = response.data.items
    total.value = response.data.total
    // Keep the selected version stable; update parse status only when that exact version is returned.
    for (const file of files.value)
      if (selected.value[file.currentVersionId]) selected.value[file.currentVersionId] = file
  } catch (cause) {
    if (context === generation && search === listGeneration)
      error.value = getAicheckErrorMessage(cause, '资料加载失败，请重试。')
  } finally {
    if (context === generation && search === listGeneration) loading.value = false
  }
}
async function loadRuns() {
  const context = generation
  try {
    const response = await importantReviewApi.runs(props.projectId)
    if (context !== generation) return
    const first = runs.value.length === 0
    runs.value = currentRunIds.value
      ? response.data.items.filter((run) => currentRunIds.value?.includes(run.id))
      : response.data.items
    if (first) expanded.value = runs.value.slice(0, 2).map((run) => run.id)
    pollingError.value = ''
  } catch (cause) {
    if (context === generation)
      pollingError.value = getAicheckErrorMessage(cause, '审查状态刷新失败，保留上次结果。')
  }
}
async function poll() {
  clearTimeout(pollTimer)
  if (!props.active || !props.projectId) return
  const context = generation
  await loadRuns()
  if (context !== generation || !props.active) return
  if (!collapsed.value && !onlySelected.value) await loadFiles()
  if (context === generation && props.active) pollTimer = setTimeout(poll, 8000)
}
function toggleFile(file: ReviewDocument, checked: boolean) {
  if (busy.value || file.bodyUploaded === false) return
  if (checked) {
    if (selectedFiles.value.length >= 500) {
      ElMessage.warning('单次最多选择500份资料')
      return
    }
    selected.value[file.currentVersionId] = file
  } else delete selected.value[file.currentVersionId]
  recommendations.value = []
  nodeFiles.value = {}
}
function toggleVisible(checked: boolean) {
  shownFiles.value.forEach((file) => toggleFile(file, checked))
}
function toggleNode(id: number, checked: boolean) {
  selectedNodes.value = checked
    ? [...new Set([...selectedNodes.value, id])]
    : selectedNodes.value.filter((value) => value !== id)
}
async function analyze() {
  const context = generation
  busy.value = true
  error.value = ''
  try {
    const response = await importantReviewApi.analyze(props.projectId, chosenVersions.value)
    if (context !== generation) return
    recommendations.value = response.data.nodes
    selectedNodes.value = response.data.nodes
      .filter((node) => node.recommended)
      .map((node) => node.nodeId)
    // All explicitly chosen files remain available, including unclassified comprehensive files.
    nodeFiles.value = {}
  } catch (cause) {
    if (context === generation) error.value = getAicheckErrorMessage(cause, '节点分析失败。')
  } finally {
    if (context === generation) busy.value = false
  }
}
async function start() {
  if (!canStart.value) return
  const context = generation,
    projectId = props.projectId
  const planned = selectedNodes.value.map((nodeId) => ({
    nodeId,
    versions: [...versionsFor(nodeId)].sort()
  }))
  busy.value = true
  startErrors.value = []
  currentRunIds.value = []
  runs.value = []
  pendingNodes.value = planned.map((row) => row.nodeId)
  for (const target of planned) {
    if (context !== generation) break
    const fingerprint = JSON.stringify([projectId, target.nodeId, target.versions])
    const key = attempts.get(fingerprint) || `important-review-${crypto.randomUUID()}`
    attempts.set(fingerprint, key)
    try {
      const response = await importantReviewApi.start(
        projectId,
        target.nodeId,
        target.versions,
        key
      )
      if (context !== generation) break
      currentRunIds.value.push(response.data.runId)
      attempts.delete(fingerprint)
    } catch (cause) {
      if (context !== generation) break
      startErrors.value.push({
        nodeId: target.nodeId,
        message: getAicheckErrorMessage(cause, '发起失败，请重试。')
      })
    }
    if (context === generation)
      pendingNodes.value = pendingNodes.value.filter((id) => id !== target.nodeId)
  }
  if (context !== generation) return
  busy.value = false
  await loadRuns()
  if (context !== generation) return
  if (runs.value.length) {
    collapsed.value = true
    expanded.value = runs.value.slice(0, 2).map((run) => run.id)
  }
}
async function upload(event: Event) {
  const target = event.target as HTMLInputElement
  const chosen = Array.from(target.files || [])
  target.value = ''
  if (!chosen.length) return
  const context = generation
  busy.value = true
  error.value = ''
  try {
    const result = await uploadImportantFiles(props.projectId, chosen)
    if (context !== generation) return
    if (result.completionWarnings?.length)
      ElMessage.warning('文件已上传，解析派发需重试，请查看资料状态。')
    else ElMessage.success('资料已上传，解析完成后可用于审查。')
    page.value = 1
    onlySelected.value = false
    await loadFiles()
  } catch (cause) {
    if (context === generation)
      error.value = getAicheckErrorMessage(cause, '上传失败，请查看资料状态后重试。')
  } finally {
    if (context === generation) busy.value = false
  }
}
function preview(item: ImportantEvidence, run?: ImportantRun, label = '') {
  const file = run?.documents.find(
    (file) => file.versionId === item.documentVersionId || file.documentId === item.documentId
  )
  const documentId = item.documentId || file?.documentId
  const versionId = item.documentVersionId || file?.versionId
  if (!documentId || !versionId) {
    ElMessage.warning('该引用缺少固定文件版本，无法定位原文。')
    return
  }
  evidence.value = {
    id: `${versionId}-${item.pageNo || 1}`,
    objectType: 'documentVersion',
    documentId,
    documentVersionId: versionId,
    fileName: item.fileName || file?.fileName || '原文',
    pageNo: item.pageNo,
    quotedText: item.quotedText || item.quote,
    projectId: props.projectId
  } as EvidenceLink
  evidenceLabel.value = label
  evidenceVisible.value = true
}
function setNodeFile(version: string, checked: boolean) {
  if (!fileNode.value) return
  const id = fileNode.value.nodeId
  nodeFiles.value[id] = checked
    ? [...new Set([...versionsFor(id), version])]
    : versionsFor(id).filter((value) => value !== version)
}
watch([page, onlySelected], () => {
  void loadFiles()
})
watch(
  () => props.active,
  () => {
    if (props.active) void poll()
    else {
      clearTimeout(pollTimer)
      rule.value = undefined
      fileNode.value = undefined
      evidenceVisible.value = false
    }
  }
)
watch(
  () => props.projectId,
  async (id) => {
    const context = ++generation
    ++listGeneration
    clearTimeout(pollTimer)
    files.value = []
    selected.value = {}
    runs.value = []
    currentRunIds.value = undefined
    catalog.value = []
    recommendations.value = []
    selectedNodes.value = []
    nodeFiles.value = {}
    pendingNodes.value = []
    startErrors.value = []
    attempts.clear()
    page.value = 1
    total.value = 0
    onlySelected.value = false
    keyword.value = ''
    collapsed.value = false
    rule.value = undefined
    fileNode.value = undefined
    evidenceVisible.value = false
    evidence.value = undefined
    busy.value = false
    loading.value = false
    error.value = ''
    pollingError.value = ''
    enabled.value = false
    if (!id) return
    try {
      const response = await importantReviewApi.config(id)
      if (context !== generation) return
      catalog.value = response.data.nodes
      enabled.value = response.data.enabled
      disabledReason.value = response.data.disabledReason
      await loadFiles()
      if (context === generation) await poll()
    } catch (cause) {
      if (context === generation) error.value = getAicheckErrorMessage(cause, '专项审查加载失败。')
    }
  },
  { immediate: true }
)
onBeforeUnmount(() => {
  generation++
  clearTimeout(pollTimer)
})
</script>

<template>
  <div class="important-review">
    <ElAlert v-if="error" :title="error" type="error" show-icon @close="error = ''" />
    <ElAlert
      v-if="disabledReason"
      :title="disabledReason"
      type="warning"
      :closable="false"
      show-icon
    />
    <section class="important-card" aria-label="工程资料">
      <div class="section-head">
        <div class="section-heading"
          ><Document class="section-icon" /><h2>工程资料</h2
          ><span class="hint">{{
            collapsed
              ? '审查文件版本已固定，可展开查看或选择新资料'
              : '当前工程全部可访问资料，未绑定节点资料也可参与审查'
          }}</span></div
        >
        <ElButton v-if="collapsed" link type="primary" @click="collapsed = false"
          >展开资料</ElButton
        >
        <div v-else class="toolbar">
          <ElInput
            v-model="keyword"
            placeholder="搜索文件名称"
            clearable
            aria-label="搜索文件名称"
            @change="searchFiles"
          />
          <ElButton :icon="Upload" :disabled="busy" @click="input?.click()">上传资料</ElButton>
          <ElSwitch v-model="onlySelected" active-text="仅看已选" @change="page = 1" />
          <ElButton v-if="runs.length" link @click="collapsed = true">收起</ElButton>
        </div>
        <input ref="input" type="file" multiple hidden @change="upload" />
      </div>
      <template v-if="!collapsed">
        <ElTable
          :data="shownFiles"
          size="small"
          v-loading="loading"
          stripe
          border
          row-key="currentVersionId"
          empty-text="暂无资料，请上传或调整搜索条件"
        >
          <ElTableColumn width="52"
            ><template #header
              ><ElCheckbox
                :model-value="allVisibleSelected"
                :disabled="busy"
                aria-label="选择当前页资料"
                @change="toggleVisible(Boolean($event))" /></template
            ><template #default="{ row }"
              ><ElCheckbox
                :model-value="!!selected[row.currentVersionId]"
                :disabled="busy || row.bodyUploaded === false || !row.currentVersionId"
                :aria-label="`选择 ${row.fileName}`"
                @change="toggleFile(row, Boolean($event))" /></template
          ></ElTableColumn>
          <ElTableColumn prop="fileName" label="文件名称" min-width="260" />
          <ElTableColumn label="解析状态" width="135"
            ><template #default="{ row }"
              ><ElTag :type="tagType(parseStatus(row))" effect="light">{{
                parseStatus(row)
              }}</ElTag></template
            ></ElTableColumn
          >
          <ElTableColumn label="操作" width="115"
            ><template #default="{ row }"
              ><ElButton
                link
                type="primary"
                :disabled="row.bodyUploaded === false"
                @click="
                  preview({
                    documentId: row.id,
                    documentVersionId: row.currentVersionId,
                    fileName: row.fileName
                  })
                "
                >查看原文</ElButton
              ></template
            ></ElTableColumn
          >
        </ElTable>
        <div class="section-footer"
          ><span
            >已选 <b>{{ selectedFiles.length }}</b> 份
            <span class="hint">支持跨页保留勾选</span></span
          ><div class="toolbar"
            ><ElPagination
              v-model:current-page="page"
              :page-size="10"
              :total="shownTotal"
              layout="prev, pager, next"
            /><ElButton @click="loadFiles">刷新资料</ElButton
            ><ElButton
              type="primary"
              :disabled="!selectedFiles.length || !enabled || busy"
              :loading="busy"
              @click="analyze"
              >分析适用节点</ElButton
            ></div
          ></div
        >
      </template>
    </section>

    <section class="important-card" aria-label="本次审查节点">
      <div class="section-head"
        ><div class="section-heading"
          ><Document class="section-icon" /><h2>{{
            !currentRunIds && runs.length && collapsed ? '最近审查节点' : '本次审查节点'
          }}</h2></div
        ><span class="hint">系统推荐供参考，可调整；开始后固定文件与规则版本</span></div
      >
      <div v-if="collapsed && runs.length" class="reviewed-nodes">
        <ElButton v-for="run in runs" :key="run.id" plain type="primary" @click="rule = run.rule">
          {{ run.rule.code }} {{ run.rule.displayName || run.rule.name }}
        </ElButton>
        <ElButton link type="primary" @click="collapsed = false">调整审查范围</ElButton>
      </div>
      <template v-else>
        <div class="node-groups"
          ><section v-for="group in groups" :key="group.name" class="node-group"
            ><h3
              >{{ group.name }} <span class="hint">（{{ group.nodes.length }} 个节点）</span></h3
            ><div v-for="node in group.nodes" :key="node.nodeId" class="node-row"
              ><ElCheckbox
                :model-value="selectedNodes.includes(node.nodeId)"
                :disabled="busy"
                :aria-label="`选择 ${node.code}`"
                @change="toggleNode(node.nodeId, Boolean($event))"
              /><span class="node-name"
                ><span>{{ node.code }}</span> {{ node.displayName || node.name }}</span
              ><div class="node-tools"
                ><ElButton link type="primary" @click="fileNode = node"
                  >本次资料 {{ versionsFor(node.nodeId).length }} 份</ElButton
                ><ElButton link type="primary" @click="rule = node">审查规则</ElButton
                ><small>{{
                  candidates(node.nodeId)?.documents.length
                    ? `候选匹配 ${candidates(node.nodeId)?.documents.length} 份，完整性待核查`
                    : '适用性待确认，可手动选择'
                }}</small></div
              ></div
            ></section
          ></div
        >
        <div class="section-footer"
          ><span class="notice">匹配资料为 0 不代表节点不适用；资料不完整时仅审查已有内容。</span
          ><ElButton type="primary" :disabled="!canStart" :loading="busy" @click="start"
            >开始审查（已选 {{ selectedNodes.length }} 个节点，{{
              selectedFiles.length
            }}
            份文件）</ElButton
          ></div
        >
      </template>
      <p v-if="running" class="hint">所选工程仍有专项任务运行中，完成后可再次发起。</p>
      <p v-if="pendingNodes.length" class="hint"
        >正在创建任务：{{
          pendingNodes.map((id) => `R${String(id).padStart(2, '0')}`).join('、')
        }}</p
      >
      <ElAlert
        v-for="failure in startErrors"
        :key="failure.nodeId"
        :title="`R${failure.nodeId} 未发起：${failure.message}`"
        type="error"
        :closable="false"
      />
    </section>

    <section class="important-card" aria-label="审查结果">
      <div class="section-head"
        ><div class="section-heading"
          ><Document class="section-icon" /><h2>审查结果</h2
          ><span class="hint">专项辅助意见，需监检人员复核后形成正式结论</span></div
        ><div class="toolbar"
          ><ElButton
            v-for="filter in ['全部', '待处理', '未完成']"
            :key="filter"
            :type="resultFilter === filter ? 'primary' : 'default'"
            plain
            @click="resultFilter = filter"
            >{{ filter }}</ElButton
          ><ElButton @click="loadRuns">刷新结果</ElButton
          ><ElButton @click="expanded = expanded.length ? [] : filteredRuns.map((run) => run.id)">{{
            expanded.length ? '收起全部' : '展开全部'
          }}</ElButton></div
        ></div
      >
      <ElAlert v-if="pollingError" :title="pollingError" type="warning" :closable="false" />
      <ElEmpty
        v-if="!filteredRuns.length"
        :description="
          runs.length ? '当前筛选下没有结果' : '尚未开始审查，请先选择资料并确认审查范围'
        "
      />
      <ElCollapse v-model="expanded"
        ><ElCollapseItem v-for="run in filteredRuns" :key="run.id" :name="run.id"
          ><template #title
            ><div class="result-heading"
              ><strong>{{ run.rule.code }} {{ run.rule.displayName || run.rule.name }}</strong
              ><span class="result-status"
                >执行状态：<ElTag :type="tagType(executionStatus(run.status))">{{
                  executionStatus(run.status)
                }}</ElTag
                >业务结论：<ElTag :type="tagType(nodeConclusion(run))">{{
                  nodeConclusion(run)
                }}</ElTag
                ><ElTag v-if="run.documentsChanged" type="warning"
                  >资料已更新，原结果待更新</ElTag
                ></span
              ></div
            ></template
          >
          <div class="run-meta"
            ><span>{{ run.startedAt }} · 本次采用 {{ run.documents.length }} 份资料</span
            ><ElButton link type="primary" @click="rule = run.rule">查看本次规则</ElButton
            ><details
              ><summary>查看固定资料版本</summary
              ><div v-for="file in run.documents" :key="file.versionId"
                ><ElButton
                  link
                  type="primary"
                  @click="
                    preview(
                      {
                        documentId: file.documentId,
                        documentVersionId: file.versionId,
                        fileName: file.fileName
                      },
                      run
                    )
                  "
                  >{{ file.fileName }}</ElButton
                ><span class="hint">{{ file.versionId }}</span></div
              ></details
            ></div
          >
          <ElAlert
            v-if="run.status === 'waiting_human_input'"
            type="warning"
            :closable="false"
            title="任务等待补充信息，请到 AI审查 中处理后继续。"
          >
            <ElButton
              link
              type="primary"
              @click="
                router.push({
                  path: '/workbench/inspection',
                  query: { projectId, nodeId: run.nodeId, view: 'ai' }
                })
              "
              >打开 AI审查</ElButton
            >
          </ElAlert>
          <ImportantResults
            :run="run"
            @rule="rule = run.rule"
            @evidence="(item, label) => preview(item, run, label)"
          /> </ElCollapseItem
      ></ElCollapse>
    </section>

    <ElDrawer
      :model-value="!!rule"
      :title="`审查规则 · ${rule?.code || ''} ${rule?.name || ''}`"
      size="min(640px, 95vw)"
      @close="rule = undefined"
    >
      <template v-if="rule"
        ><ElAlert
          title="请结合逐项结果与原文证据复核；未覆盖的要求需补充人工核查。"
          type="info"
          :closable="false"
        /><section v-for="section in rule.sections" :key="section.title" class="rule-section"
          ><h3>{{ section.title }}</h3
          ><p>{{ section.text }}</p></section
        ><p class="hint"
          >来源：{{ rule.source }} · {{ rule.code }}<br />规则版本：{{
            rule.version.slice(0, 12)
          }}</p
        ></template
      >
    </ElDrawer>
    <ElDialog
      :model-value="!!fileNode"
      :title="`${fileNode?.code || ''} 本次审查资料`"
      width="min(660px, 95vw)"
      @close="fileNode = undefined"
      ><p class="hint">从工程已选资料中调整，仅影响本次审查，不修改永久节点绑定。</p
      ><div v-for="file in selectedFiles" :key="file.currentVersionId" class="file-choice"
        ><ElCheckbox
          :model-value="
            fileNode ? versionsFor(fileNode.nodeId).includes(file.currentVersionId) : false
          "
          :disabled="busy"
          @change="setNodeFile(file.currentVersionId, Boolean($event))"
          >{{ file.fileName }}</ElCheckbox
        ></div
      ><ElEmpty v-if="!selectedFiles.length" description="请先从工程资料列表选择文件" /><template
        #footer
        ><ElButton type="primary" @click="fileNode = undefined">完成</ElButton></template
      ></ElDialog
    >
    <ElDrawer v-model="evidenceVisible" title="原文证据" size="min(740px, 95vw)"
      ><p v-if="evidenceLabel">对应核查项：{{ evidenceLabel }}</p
      ><EvidenceLocatorDialog
        v-model="evidenceVisible"
        inline
        compact
        :project-id="projectId"
        :evidence="evidence"
        :extracted-fields="[]"
    /></ElDrawer>
  </div>
</template>

<style scoped src="./importantReview.css"></style>
