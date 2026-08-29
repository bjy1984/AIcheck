<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  ElAlert,
  ElCollapse,
  ElCollapseItem,
  ElEmpty,
  ElTabPane,
  ElTabs,
  ElTag
} from 'element-plus'
import {
  getKnowledgeFileCanonicalApi,
  type StandardCanonicalContentItem,
  type StandardCanonicalEvidence,
  type StandardCanonicalField,
  type StandardKnowledgeRecord,
  type StandardKnowledgeRecordSummary
} from '@/api/aicheck'
import { getAicheckErrorMessage } from '@/utils/aicheckError'
import ClauseContent from '@/components/ClauseContent/src/ClauseContent.vue'
import {
  CANONICAL_CATEGORY_LABELS,
  CANONICAL_FIELD_LABELS,
  CANONICAL_WARNING_COPY,
  canonicalOverviewRows,
  canonicalTabLoadRequest,
  type CanonicalTabLoadRequest,
  canonicalWarningMessages,
  visibleCanonicalSourceValues
} from './standardCanonicalPresentation'

const props = defineProps<{
  record: StandardKnowledgeRecord | StandardKnowledgeRecordSummary
}>()

const emit = defineEmits<{
  locate: [evidence: StandardCanonicalEvidence]
}>()

const activeTab = ref('overview')
const loadedRecord = ref<StandardKnowledgeRecord>()
const loadedHistory = ref(false)
const loading = ref(false)
const loadError = ref('')
const sourcePanels = ref<string[]>([])
let loadToken = 0

const overviewRows = computed(() => canonicalOverviewRows(props.record))
const warnings = computed(() => canonicalWarningMessages(props.record))
const extraMetadataRows = computed(() =>
  Object.entries(props.record.metadata).map(([key, field]) => ({
    key,
    label: CANONICAL_FIELD_LABELS[key] || key,
    value: String(field.value ?? '-'),
    field
  }))
)
const allFields = computed(() =>
  Object.entries({
    ...(loadedRecord.value || props.record).identity,
    ...(loadedRecord.value || props.record).version,
    ...(loadedRecord.value || props.record).metadata
  }).map(([key, field]) => ({ key, label: CANONICAL_FIELD_LABELS[key] || key, field }))
)
const completenessRows = computed(() =>
  Object.entries(props.record.completeness)
    .filter(([key]) => key !== 'overall' && key !== 'missingCategories')
    .map(([key, detail]) => {
      const data = detail && typeof detail === 'object' ? (detail as Record<string, unknown>) : {}
      const status = String(data.status || 'missing')
      return {
        key,
        label: CANONICAL_CATEGORY_LABELS[key] || key,
        status,
        count: typeof data.count === 'number' ? data.count : undefined,
        located: typeof data.located === 'number' ? data.located : undefined,
        total: typeof data.total === 'number' ? data.total : undefined,
        reason:
          status === 'missing' || status === 'partial'
            ? CANONICAL_WARNING_COPY[key] || `“${CANONICAL_CATEGORY_LABELS[key] || key}”信息不完整`
            : ''
      }
    })
)

const statusLabel = (status: string) => {
  const labels: Record<string, string> = {
    complete: '完整',
    partial: '部分完整',
    missing: '缺失',
    not_applicable: '不适用'
  }
  return labels[status] || status
}

const statusTagType = (status: string) => {
  if (status === 'complete') return 'success'
  if (status === 'not_applicable') return 'info'
  return 'warning'
}

const sourceTypeLabel = (sourceType?: string) => {
  const labels: Record<string, string> = {
    new_mineru: '当前 MinerU 识别',
    legacy_ocr: '旧 OCR 识别',
    visual_extraction: '视觉提取',
    structured_parse: '结构化解析'
  }
  return labels[String(sourceType || '')] || sourceType || '未知来源'
}

const formatValue = (value: unknown) => {
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }
  return JSON.stringify(value)
}

const selectedFieldEvidence = (field: StandardCanonicalField): StandardCanonicalEvidence => {
  const selected = field.sources.find((source) => source.sourceId === field.selectedSourceId)
  return {
    ...selected,
    key: field.id,
    value: field.value,
    quotedText: selected?.quotedText || String(field.value ?? '')
  }
}

const selectedItemEvidence = (item: StandardCanonicalContentItem): StandardCanonicalEvidence => {
  const selected = item.sources.find((source) => source.sourceId === item.selectedSourceId)
  return {
    ...selected,
    key: item.id,
    pageNo: selected?.pageNo ?? item.pageNo,
    bbox: selected?.bbox ?? item.bbox,
    quotedText: selected?.quotedText || item.text || item.caption || item.latex || item.title || ''
  }
}

const locateField = (field?: StandardCanonicalField) => {
  if (field) emit('locate', selectedFieldEvidence(field))
}

const locateItem = (item: StandardCanonicalContentItem) => {
  emit('locate', selectedItemEvidence(item))
}

const tableColumns = (item: StandardCanonicalContentItem) => {
  if (item.columnNames?.length) return item.columnNames
  const firstRow = item.normalizedRows?.[0]
  return firstRow ? Object.keys(firstRow) : []
}

const loadCanonical = async (request: CanonicalTabLoadRequest) => {
  const includeHistory = request.includeHistory
  if (loadedRecord.value && (!includeHistory || loadedHistory.value)) return
  const token = ++loadToken
  loading.value = true
  loadError.value = ''
  try {
    const response = await getKnowledgeFileCanonicalApi(props.record.knowledgeFileId, {
      ...request
    })
    if (token !== loadToken) return
    if (!response?.data) throw new Error('标准 canonical 全集接口未返回有效数据。')
    loadedRecord.value = response.data
    loadedHistory.value = includeHistory
  } catch (error) {
    if (token !== loadToken) return
    loadError.value = getAicheckErrorMessage(error, '标准 canonical 全集加载失败，请稍后重试。')
  } finally {
    if (token === loadToken) loading.value = false
  }
}

const handleTabChange = (name: string | number) => {
  const request = canonicalTabLoadRequest(String(name))
  if (request) void loadCanonical(request)
}

watch(
  () => props.record.knowledgeFileId,
  () => {
    loadToken += 1
    activeTab.value = 'overview'
    loadedRecord.value = undefined
    loadedHistory.value = false
    loading.value = false
    loadError.value = ''
    sourcePanels.value = []
  }
)
</script>

<template>
  <div class="canonical-detail">
    <ElTabs v-model="activeTab" class="canonical-tabs" @tab-change="handleTabChange">
      <ElTabPane label="概览" name="overview">
        <div class="canonical-pane">
          <ElAlert
            v-if="warnings.length"
            title="标准信息需要补全"
            :description="warnings.join('；')"
            type="warning"
            :closable="false"
            show-icon
            class="canonical-alert"
          />
          <div class="canonical-overview-list">
            <button
              v-for="row in overviewRows"
              :key="row.key"
              type="button"
              class="canonical-field"
              @click="locateField(row.field)"
            >
              <span class="canonical-field-label">{{ row.label }}</span>
              <span class="canonical-field-value">{{ row.value }}</span>
              <ElTag
                v-if="row.field?.authority === 'legacy_only'"
                size="small"
                type="warning"
                effect="plain"
              >
                legacy_only
              </ElTag>
              <span v-if="row.field?.sources.some((source) => source.pageNo)" class="locate-note">
                定位原文
              </span>
            </button>
          </div>

          <div v-if="extraMetadataRows.length" class="canonical-section">
            <div class="canonical-section-title">适用信息</div>
            <button
              v-for="row in extraMetadataRows"
              :key="row.key"
              type="button"
              class="canonical-field"
              @click="locateField(row.field)"
            >
              <span class="canonical-field-label">{{ row.label }}</span>
              <span class="canonical-field-value">{{ row.value }}</span>
              <ElTag
                v-if="row.field.authority === 'legacy_only'"
                size="small"
                type="warning"
                effect="plain"
              >
                legacy_only
              </ElTag>
            </button>
          </div>
        </div>
      </ElTabPane>

      <ElTabPane label="章节条款" name="structure">
        <div v-loading="loading" class="canonical-pane">
          <ElAlert
            v-if="loadError"
            :title="loadError"
            type="warning"
            :closable="false"
            class="canonical-alert"
          />
          <template v-if="loadedRecord">
            <div v-if="loadedRecord.sections.length" class="canonical-section">
              <div class="canonical-section-title">章节 {{ loadedRecord.sections.length }}</div>
              <button
                v-for="item in loadedRecord.sections"
                :key="item.id"
                type="button"
                class="content-card"
                @click="locateItem(item)"
              >
                <strong>{{ item.title || item.sectionPath?.join(' / ') || '未命名章节' }}</strong>
                <span>{{ item.text }}</span>
                <small v-if="item.pageNo">第 {{ item.pageNo }} 页</small>
              </button>
            </div>
            <div v-if="loadedRecord.clauses.length" class="canonical-section">
              <div class="canonical-section-title">条款 {{ loadedRecord.clauses.length }}</div>
              <button
                v-for="item in loadedRecord.clauses"
                :key="item.id"
                type="button"
                class="content-card"
                @click="locateItem(item)"
              >
                <strong>{{ item.clauseNo || item.title || '未编号条款' }}</strong>
                <span>{{ item.text }}</span>
                <small v-if="item.pageNo">第 {{ item.pageNo }} 页</small>
              </button>
            </div>
            <ElEmpty
              v-if="!loadedRecord.sections.length && !loadedRecord.clauses.length"
              :image-size="60"
              description="暂无章节条款"
            />
          </template>
        </div>
      </ElTabPane>

      <ElTabPane label="表格公式" name="tables">
        <div v-loading="loading" class="canonical-pane">
          <ElAlert
            v-if="loadError"
            :title="loadError"
            type="warning"
            :closable="false"
            class="canonical-alert"
          />
          <template v-if="loadedRecord">
            <div v-if="loadedRecord.tables.length" class="canonical-section">
              <div class="canonical-section-title">表格 {{ loadedRecord.tables.length }}</div>
              <div v-for="item in loadedRecord.tables" :key="item.id" class="table-card">
                <button type="button" class="content-card table-meta" @click="locateItem(item)">
                  <strong>{{ item.caption || item.title || '结构化表格' }}</strong>
                  <small v-if="item.pageNo">第 {{ item.pageNo }} 页</small>
                </button>
                <div v-if="item.normalizedRows?.length" class="canonical-table-scroll">
                  <table class="canonical-table">
                    <thead v-if="item.headerReliable !== false">
                      <tr>
                        <th v-for="column in tableColumns(item)" :key="column">{{ column }}</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="(row, index) in item.normalizedRows" :key="index">
                        <td v-for="column in tableColumns(item)" :key="column">
                          {{ formatValue(row[column]) }}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <div v-else-if="item.cells?.length" class="cell-list">
                  <span v-for="(cell, index) in item.cells" :key="index">{{
                    cell.text || '-'
                  }}</span>
                </div>
              </div>
            </div>

            <div v-if="loadedRecord.equations.length" class="canonical-section">
              <div class="canonical-section-title">公式 {{ loadedRecord.equations.length }}</div>
              <button
                v-for="item in loadedRecord.equations"
                :key="item.id"
                type="button"
                class="content-card equation-card"
                @click="locateItem(item)"
              >
                <ClauseContent block-type="equation" :latex="item.latex" :text="item.text" />
                <small v-if="item.pageNo">第 {{ item.pageNo }} 页</small>
              </button>
            </div>

            <div
              v-if="loadedRecord.images.length || loadedRecord.seals.length"
              class="canonical-section"
            >
              <div class="canonical-section-title">
                图片 / 印章 {{ loadedRecord.images.length + loadedRecord.seals.length }}
              </div>
              <button
                v-for="item in [...loadedRecord.images, ...loadedRecord.seals]"
                :key="item.id"
                type="button"
                class="content-card"
                @click="locateItem(item)"
              >
                <strong>{{ item.caption || item.title || item.text || '图像证据' }}</strong>
                <small v-if="item.pageNo">第 {{ item.pageNo }} 页</small>
              </button>
            </div>
            <ElEmpty
              v-if="
                !loadedRecord.tables.length &&
                !loadedRecord.equations.length &&
                !loadedRecord.images.length &&
                !loadedRecord.seals.length
              "
              :image-size="60"
              description="暂无表格、公式或图像证据"
            />
          </template>
        </div>
      </ElTabPane>

      <ElTabPane label="引用关系" name="relations">
        <div v-loading="loading" class="canonical-pane">
          <ElAlert
            v-if="loadError"
            :title="loadError"
            type="warning"
            :closable="false"
            class="canonical-alert"
          />
          <template v-if="loadedRecord">
            <div
              v-for="group in [
                { label: '规范性引用', items: loadedRecord.normativeReferences },
                { label: '替代关系', items: loadedRecord.replacementRelations },
                { label: '业务关系', items: loadedRecord.businessRelations }
              ]"
              :key="group.label"
              class="canonical-section"
            >
              <div class="canonical-section-title">{{ group.label }} {{ group.items.length }}</div>
              <button
                v-for="item in group.items"
                :key="item.id"
                type="button"
                class="content-card"
                @click="locateItem(item)"
              >
                <strong>
                  {{
                    item.targetStandardCode ||
                    item.targetClauseNo ||
                    item.title ||
                    item.purpose ||
                    '关联条目'
                  }}
                </strong>
                <span>{{ item.text }}</span>
                <small v-if="item.pageNo">第 {{ item.pageNo }} 页</small>
              </button>
            </div>
            <ElEmpty
              v-if="
                !loadedRecord.normativeReferences.length &&
                !loadedRecord.replacementRelations.length &&
                !loadedRecord.businessRelations.length
              "
              :image-size="60"
              description="暂无引用或业务关系"
            />
          </template>
        </div>
      </ElTabPane>

      <ElTabPane label="完整度" name="completeness">
        <div class="canonical-pane">
          <div class="completeness-summary">
            <span>总体完整度</span>
            <ElTag :type="props.record.completeness.overall === 'complete' ? 'success' : 'warning'">
              {{ statusLabel(props.record.completeness.overall) }}
            </ElTag>
          </div>
          <div v-for="row in completenessRows" :key="row.key" class="completeness-row">
            <div>
              <strong>{{ row.label }}</strong>
              <div v-if="row.reason" class="missing-reason">{{ row.reason }}</div>
              <div v-else-if="row.total !== undefined" class="completeness-count">
                已定位 {{ row.located || 0 }} / {{ row.total }}
              </div>
              <div v-else-if="row.count !== undefined" class="completeness-count">
                {{ row.count }} 项
              </div>
            </div>
            <ElTag :type="statusTagType(row.status)" size="small" effect="plain">
              {{ statusLabel(row.status) }}
            </ElTag>
          </div>
        </div>
      </ElTabPane>

      <ElTabPane label="来源历史" name="history">
        <div v-loading="loading" class="canonical-pane">
          <ElAlert
            v-if="loadError"
            :title="loadError"
            type="warning"
            :closable="false"
            class="canonical-alert"
          />
          <template v-if="loadedRecord && loadedHistory">
            <p class="history-note">
              主详情始终使用当前选中值；冲突旧值和原始识别结果仅在下方折叠项中追溯。
            </p>
            <ElCollapse v-model="sourcePanels">
              <ElCollapseItem
                v-for="entry in allFields.filter((item) => item.field.sources.length)"
                :key="entry.field.id"
                :name="entry.field.id"
              >
                <template #title>
                  <span class="source-title">{{ entry.label }}</span>
                  <span class="source-count">{{ entry.field.sources.length }} 个来源</span>
                </template>
                <button
                  v-for="(source, index) in visibleCanonicalSourceValues(entry.field)"
                  :key="`${entry.field.id}-${index}`"
                  type="button"
                  class="source-value"
                  @click="
                    emit('locate', {
                      ...entry.field.sources[index],
                      key: entry.field.id
                    })
                  "
                >
                  <span>{{ source.value || '（空值）' }}</span>
                  <small>{{ sourceTypeLabel(source.sourceType) }}</small>
                  <ElTag v-if="source.selected" size="small" type="success" effect="plain">
                    当前选中
                  </ElTag>
                </button>
              </ElCollapseItem>
              <ElCollapseItem name="parse-history" title="解析结果历史">
                <div
                  v-for="source in loadedRecord.history || []"
                  :key="source.sourceId"
                  class="history-source"
                >
                  <strong>{{ sourceTypeLabel(source.sourceType) }}</strong>
                  <span>{{ source.sourceId }}</span>
                  <small>
                    字段 {{ source.fieldCount || 0 }} · 正文 {{ source.blockCount || 0 }} · 表格
                    {{ source.tableCount || 0 }} · 印章 {{ source.sealCount || 0 }}
                  </small>
                </div>
                <ElEmpty
                  v-if="!loadedRecord.history?.length"
                  :image-size="48"
                  description="暂无解析历史"
                />
              </ElCollapseItem>
            </ElCollapse>
          </template>
        </div>
      </ElTabPane>
    </ElTabs>
  </div>
</template>

<style scoped>
.canonical-detail,
.canonical-tabs {
  min-width: 0;
  height: 100%;
}

.canonical-pane {
  min-height: 180px;
  padding: 0 2px 12px;
}

.canonical-alert {
  margin-bottom: 10px;
}

.canonical-overview-list,
.canonical-section {
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.canonical-section {
  margin-top: 14px;
}

.canonical-section-title {
  font-size: 13px;
  font-weight: 600;
  color: #334155;
}

.canonical-field,
.content-card,
.source-value {
  display: flex;
  width: 100%;
  padding: 9px 10px;
  font: inherit;
  color: #334155;
  text-align: left;
  cursor: pointer;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 7px;
  gap: 8px;
  align-items: flex-start;
}

.canonical-field:hover,
.content-card:hover,
.source-value:hover {
  background: #fff7ed;
  border-color: #f59e0b;
}

.canonical-field-label {
  width: 72px;
  flex: 0 0 auto;
  font-size: 12px;
  color: #64748b;
}

.canonical-field-value {
  min-width: 0;
  flex: 1;
  overflow-wrap: anywhere;
}

.locate-note {
  font-size: 11px;
  color: #b45309;
}

.content-card {
  flex-direction: column;
  gap: 4px;
}

.content-card span {
  line-height: 1.65;
  overflow-wrap: anywhere;
}

.content-card small,
.source-value small,
.history-source small {
  color: #94a3b8;
}

.table-card {
  overflow: hidden;
  border: 1px solid #e2e8f0;
  border-radius: 7px;
}

.table-meta {
  border: 0;
  border-radius: 0;
}

.canonical-table-scroll {
  overflow-x: auto;
}

.canonical-table {
  width: 100%;
  min-width: 360px;
  font-size: 12px;
  border-collapse: collapse;
}

.canonical-table th,
.canonical-table td {
  padding: 6px 8px;
  text-align: left;
  white-space: nowrap;
  border-top: 1px solid #e2e8f0;
  border-right: 1px solid #e2e8f0;
}

.canonical-table th {
  color: #475569;
  background: #f1f5f9;
}

.cell-list {
  display: flex;
  padding: 8px;
  font-size: 12px;
  gap: 6px;
  flex-wrap: wrap;
}

.cell-list span {
  padding: 2px 5px;
  background: #f1f5f9;
  border-radius: 4px;
}

.equation-card {
  overflow-x: auto;
}

.completeness-summary,
.completeness-row {
  display: flex;
  padding: 10px;
  border-bottom: 1px solid #eef2f6;
  gap: 10px;
  align-items: flex-start;
  justify-content: space-between;
}

.missing-reason,
.completeness-count {
  margin-top: 3px;
  font-size: 12px;
  color: #b45309;
}

.completeness-count {
  color: #64748b;
}

.history-note {
  margin: 0 0 10px;
  font-size: 12px;
  line-height: 1.6;
  color: #64748b;
}

.source-title {
  font-weight: 600;
}

.source-count {
  margin-left: 8px;
  font-size: 12px;
  color: #94a3b8;
}

.source-value {
  margin-bottom: 6px;
  align-items: center;
}

.source-value > span {
  min-width: 0;
  flex: 1;
  overflow-wrap: anywhere;
}

.history-source {
  display: grid;
  padding: 8px 0;
  border-bottom: 1px solid #eef2f6;
  gap: 3px;
}

:deep(.canonical-tabs > .el-tabs__content) {
  height: calc(100% - 54px);
  overflow-y: auto;
}

:deep(.canonical-tabs .el-tabs__item) {
  padding: 0 10px;
  font-size: 12px;
}
</style>
