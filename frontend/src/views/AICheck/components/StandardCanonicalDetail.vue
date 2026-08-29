<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  ElAlert,
  ElButton,
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
  CANONICAL_BLOCK_BATCH_SIZE,
  CANONICAL_FIELD_LABELS,
  beginCanonicalSectionLoad,
  canonicalAuthorityBadge,
  canonicalBlockPage,
  canonicalCompletenessRows,
  canonicalDetailIdentity,
  canonicalFieldLocateEvidence,
  canonicalItemLocateEvidence,
  canonicalNextBlockLimit,
  canonicalOverviewRows,
  canonicalSectionPayload,
  canonicalTabQuery,
  canonicalWarningMessages,
  completeCanonicalSectionLoad,
  createCanonicalDetailLoadState,
  failCanonicalSectionLoad,
  resetCanonicalDetailLoadState,
  visibleCanonicalSourceValues
} from './standardCanonicalPresentation'

const props = defineProps<{
  record: StandardKnowledgeRecord | StandardKnowledgeRecordSummary
  documentId?: string
}>()

const emit = defineEmits<{
  locate: [evidence: StandardCanonicalEvidence]
}>()

const activeTab = ref('overview')
const sourcePanels = ref<string[]>([])
const blockVisibleLimit = ref(CANONICAL_BLOCK_BATCH_SIZE)
const fileKey = computed(() => canonicalDetailIdentity(props.record, props.documentId))
const loadState = ref(createCanonicalDetailLoadState(fileKey.value))
const structureLoad = computed(() => loadState.value.sections.structure)
const tablesLoad = computed(() => loadState.value.sections.tables)
const relationsLoad = computed(() => loadState.value.sections.relations)
const historyLoad = computed(() => loadState.value.sections.history)
const structureRecord = computed(() => structureLoad.value.data)
const blockPage = computed(() =>
  canonicalBlockPage(structureRecord.value?.blocks || [], blockVisibleLimit.value)
)
const visibleBlocks = computed(() => blockPage.value.items)
const tablesRecord = computed(() => tablesLoad.value.data)
const relationsRecord = computed(() => relationsLoad.value.data)
const historyRecord = computed(() => historyLoad.value.data)

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
    ...(historyRecord.value || props.record).identity,
    ...(historyRecord.value || props.record).version,
    ...(historyRecord.value || props.record).metadata
  }).map(([key, field]) => ({ key, label: CANONICAL_FIELD_LABELS[key] || key, field }))
)
const completenessRows = computed(() => canonicalCompletenessRows(props.record.completeness))

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

const locateField = (field?: StandardCanonicalField) => {
  if (field) emit('locate', canonicalFieldLocateEvidence(field))
}

const locateItem = (item: StandardCanonicalContentItem) => {
  emit('locate', canonicalItemLocateEvidence(item))
}

const tableColumns = (item: StandardCanonicalContentItem) => {
  if (item.columnNames?.length) return item.columnNames
  const firstRow = item.normalizedRows?.[0]
  return firstRow ? Object.keys(firstRow) : []
}

const showMoreBlocks = () => {
  blockVisibleLimit.value = canonicalNextBlockLimit(blockVisibleLimit.value, blockPage.value.total)
}

const loadCanonical = async (tab: string) => {
  const query = canonicalTabQuery(tab)
  if (
    !query ||
    loadState.value.sections[query.section].data ||
    loadState.value.sections[query.section].loading
  )
    return
  const started = beginCanonicalSectionLoad(loadState.value, query.section)
  loadState.value = started.state
  try {
    const response = await getKnowledgeFileCanonicalApi(props.record.knowledgeFileId, {
      ...query.params
    })
    if (!response?.data) throw new Error('标准 canonical 全集接口未返回有效数据。')
    loadState.value = completeCanonicalSectionLoad(
      loadState.value,
      started.token,
      canonicalSectionPayload(query, response.data)
    )
  } catch (error) {
    loadState.value = failCanonicalSectionLoad(
      loadState.value,
      started.token,
      getAicheckErrorMessage(error, '标准 canonical 全集加载失败，请稍后重试。')
    )
  }
}

const handleTabChange = (name: string | number) => {
  void loadCanonical(String(name))
}

watch(
  fileKey,
  () => {
    loadState.value = resetCanonicalDetailLoadState(loadState.value, fileKey.value)
    activeTab.value = 'overview'
    blockVisibleLimit.value = CANONICAL_BLOCK_BATCH_SIZE
    sourcePanels.value = []
  },
  { flush: 'sync' }
)
</script>

<template>
  <div class="canonical-detail">
    <ElTabs v-model="activeTab" class="canonical-tabs" @tab-change="handleTabChange">
      <ElTabPane label="概览" name="overview" lazy>
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

      <ElTabPane label="章节条款" name="structure" lazy>
        <div
          v-if="activeTab === 'structure'"
          v-loading="structureLoad.loading"
          class="canonical-pane"
        >
          <ElAlert
            v-if="structureLoad.error"
            :title="structureLoad.error"
            type="warning"
            :closable="false"
            class="canonical-alert"
          />
          <template v-if="structureRecord">
            <div v-if="structureRecord.sections.length" class="canonical-section">
              <div class="canonical-section-title">章节 {{ structureRecord.sections.length }}</div>
              <button
                v-for="item in structureRecord.sections"
                :key="item.id"
                type="button"
                class="content-card"
                @click="locateItem(item)"
              >
                <span class="content-title">
                  <strong>{{ item.title || item.sectionPath?.join(' / ') || '未命名章节' }}</strong>
                  <ElTag
                    v-if="canonicalAuthorityBadge(item.authority)"
                    size="small"
                    type="warning"
                    effect="plain"
                  >
                    {{ canonicalAuthorityBadge(item.authority) }}
                  </ElTag>
                </span>
                <span>{{ item.text }}</span>
                <small v-if="item.pageNo">第 {{ item.pageNo }} 页</small>
              </button>
            </div>
            <div v-if="structureRecord.clauses.length" class="canonical-section">
              <div class="canonical-section-title">条款 {{ structureRecord.clauses.length }}</div>
              <button
                v-for="item in structureRecord.clauses"
                :key="item.id"
                type="button"
                class="content-card"
                @click="locateItem(item)"
              >
                <span class="content-title">
                  <strong>{{ item.clauseNo || item.title || '未编号条款' }}</strong>
                  <ElTag
                    v-if="canonicalAuthorityBadge(item.authority)"
                    size="small"
                    type="warning"
                    effect="plain"
                  >
                    {{ canonicalAuthorityBadge(item.authority) }}
                  </ElTag>
                </span>
                <span>{{ item.text }}</span>
                <small v-if="item.pageNo">第 {{ item.pageNo }} 页</small>
              </button>
            </div>
            <div v-if="structureRecord.blocks?.length" class="canonical-section">
              <div class="canonical-section-title">正文 {{ blockPage.total }} 段</div>
              <button
                v-for="item in visibleBlocks"
                :key="item.id"
                type="button"
                class="content-card"
                @click="locateItem(item)"
              >
                <span class="content-title">
                  <strong>{{ item.title || item.sectionPath?.join(' / ') || '正文段落' }}</strong>
                  <ElTag
                    v-if="canonicalAuthorityBadge(item.authority)"
                    size="small"
                    type="warning"
                    effect="plain"
                  >
                    {{ canonicalAuthorityBadge(item.authority) }}
                  </ElTag>
                </span>
                <span>{{ item.text }}</span>
                <small v-if="item.pageNo">第 {{ item.pageNo }} 页</small>
              </button>
              <ElButton v-if="blockPage.hasMore" plain size="small" @click="showMoreBlocks">
                加载更多
              </ElButton>
            </div>
            <ElEmpty
              v-if="
                !structureRecord.sections.length &&
                !structureRecord.clauses.length &&
                !structureRecord.blocks?.length
              "
              :image-size="60"
              description="暂无章节条款"
            />
          </template>
        </div>
      </ElTabPane>

      <ElTabPane label="表格公式" name="tables" lazy>
        <div v-if="activeTab === 'tables'" v-loading="tablesLoad.loading" class="canonical-pane">
          <ElAlert
            v-if="tablesLoad.error"
            :title="tablesLoad.error"
            type="warning"
            :closable="false"
            class="canonical-alert"
          />
          <template v-if="tablesRecord">
            <div v-if="tablesRecord.tables.length" class="canonical-section">
              <div class="canonical-section-title">表格 {{ tablesRecord.tables.length }}</div>
              <div v-for="item in tablesRecord.tables" :key="item.id" class="table-card">
                <button type="button" class="content-card table-meta" @click="locateItem(item)">
                  <span class="content-title">
                    <strong>{{ item.caption || item.title || '结构化表格' }}</strong>
                    <ElTag
                      v-if="canonicalAuthorityBadge(item.authority)"
                      size="small"
                      type="warning"
                      effect="plain"
                    >
                      {{ canonicalAuthorityBadge(item.authority) }}
                    </ElTag>
                  </span>
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

            <div v-if="tablesRecord.equations.length" class="canonical-section">
              <div class="canonical-section-title">公式 {{ tablesRecord.equations.length }}</div>
              <button
                v-for="item in tablesRecord.equations"
                :key="item.id"
                type="button"
                class="content-card equation-card"
                @click="locateItem(item)"
              >
                <ElTag
                  v-if="canonicalAuthorityBadge(item.authority)"
                  size="small"
                  type="warning"
                  effect="plain"
                >
                  {{ canonicalAuthorityBadge(item.authority) }}
                </ElTag>
                <ClauseContent block-type="equation" :latex="item.latex" :text="item.text" />
                <small v-if="item.pageNo">第 {{ item.pageNo }} 页</small>
              </button>
            </div>

            <div
              v-if="tablesRecord.images.length || tablesRecord.seals.length"
              class="canonical-section"
            >
              <div class="canonical-section-title">
                图片 / 印章 {{ tablesRecord.images.length + tablesRecord.seals.length }}
              </div>
              <button
                v-for="item in [...tablesRecord.images, ...tablesRecord.seals]"
                :key="item.id"
                type="button"
                class="content-card"
                @click="locateItem(item)"
              >
                <span class="content-title">
                  <strong>{{ item.caption || item.title || item.text || '图像证据' }}</strong>
                  <ElTag
                    v-if="canonicalAuthorityBadge(item.authority)"
                    size="small"
                    type="warning"
                    effect="plain"
                  >
                    {{ canonicalAuthorityBadge(item.authority) }}
                  </ElTag>
                </span>
                <small v-if="item.pageNo">第 {{ item.pageNo }} 页</small>
              </button>
            </div>
            <ElEmpty
              v-if="
                !tablesRecord.tables.length &&
                !tablesRecord.equations.length &&
                !tablesRecord.images.length &&
                !tablesRecord.seals.length
              "
              :image-size="60"
              description="暂无表格、公式或图像证据"
            />
          </template>
        </div>
      </ElTabPane>

      <ElTabPane label="引用关系" name="relations" lazy>
        <div
          v-if="activeTab === 'relations'"
          v-loading="relationsLoad.loading"
          class="canonical-pane"
        >
          <ElAlert
            v-if="relationsLoad.error"
            :title="relationsLoad.error"
            type="warning"
            :closable="false"
            class="canonical-alert"
          />
          <template v-if="relationsRecord">
            <div
              v-for="group in [
                { label: '规范性引用', items: relationsRecord.normativeReferences },
                { label: '替代关系', items: relationsRecord.replacementRelations },
                { label: '业务关系', items: relationsRecord.businessRelations }
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
                <span class="content-title">
                  <strong>
                    {{
                      item.targetStandardCode ||
                      item.targetClauseNo ||
                      item.title ||
                      item.purpose ||
                      '关联条目'
                    }}
                  </strong>
                  <ElTag
                    v-if="canonicalAuthorityBadge(item.authority)"
                    size="small"
                    type="warning"
                    effect="plain"
                  >
                    {{ canonicalAuthorityBadge(item.authority) }}
                  </ElTag>
                </span>
                <span>{{ item.text }}</span>
                <small v-if="item.pageNo">第 {{ item.pageNo }} 页</small>
              </button>
            </div>
            <ElEmpty
              v-if="
                !relationsRecord.normativeReferences.length &&
                !relationsRecord.replacementRelations.length &&
                !relationsRecord.businessRelations.length
              "
              :image-size="60"
              description="暂无引用或业务关系"
            />
          </template>
        </div>
      </ElTabPane>

      <ElTabPane label="完整度" name="completeness" lazy>
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

      <ElTabPane label="来源历史" name="history" lazy>
        <div v-if="activeTab === 'history'" v-loading="historyLoad.loading" class="canonical-pane">
          <ElAlert
            v-if="historyLoad.error"
            :title="historyLoad.error"
            type="warning"
            :closable="false"
            class="canonical-alert"
          />
          <template v-if="historyRecord">
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
                  v-for="source in historyRecord.history || []"
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
                  v-if="!historyRecord.history?.length"
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

.content-title {
  display: flex;
  width: 100%;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
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
