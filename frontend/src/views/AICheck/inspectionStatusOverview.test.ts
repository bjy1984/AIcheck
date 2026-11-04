import assert from 'node:assert/strict'
import { computed, reactive, ref } from 'vue'
import { handler } from './workflowTestHarness'
import { aggregateNodeStatus, nodeNeedsAttention } from './nodeAggregateStatus'
import {
  aggregateStatusKey,
  auditItemsMatchStatus,
  type InspectionStatusFilter
} from './inspectionStatusOverview'
import { indexCountScale, indexCountWidth, indexRecordCount } from './knowledgeIndexCounts'

const inspectionAuditStatusFilter = ref<InspectionStatusFilter | null>(null)
const inspectionOnlyAttentionNodes = ref(true)
const inspectionProjectNodeRows = ref([1, 2, 3, 4].map((nodeId) => ({ node: { nodeId } })))
const inspectionAuditOverviewNodeMap = ref(
  new Map([
    [
      1,
      {
        items: [
          { key: 'ocr', label: 'OCR', status: 'needs_attention' },
          { key: 'ai', label: 'AI', status: 'completed' }
        ]
      }
    ],
    [2, { items: [{ key: 'ocr', label: 'OCR', status: 'failed' }] }],
    [3, { items: [{ key: 'ocr', label: 'OCR', status: 'in_progress' }] }],
    [4, { items: [{ key: 'ocr', label: 'OCR', status: 'not_started' }] }]
  ])
)
const visible = handler('./Workbench.vue', 'inspectionVisibleNodeRows', {
  computed,
  inspectionAuditStatusFilter,
  inspectionOnlyAttentionNodes,
  inspectionProjectNodeRows,
  inspectionAuditOverviewNodeMap,
  auditItemsMatchStatus,
  nodeNeedsAttention
})
const visibleIds = () => visible.value.map((row: { node: { nodeId: number } }) => row.node.nodeId)
assert.deepEqual(
  visibleIds(),
  [1, 2],
  'the existing default continues to show nodes needing action'
)
// 状态图例筛选（selectInspectionStatus / changeInspectionAttentionFilter）随旧总览一起移除，
// 2026-11-03 起项目总览按工位分组（StationAuditOverview，测试见 components/stationOverview.test.ts）。
assert.equal(
  aggregateNodeStatus(inspectionAuditOverviewNodeMap.value.get(1)?.items).tone,
  'attention'
)
assert.equal(aggregateStatusKey(undefined), 'unknown')
assert.equal(aggregateStatusKey([{ status: 'needs_attention' }]), 'needs_attention')
assert.equal(aggregateStatusKey([{ status: 'needs_attention' }, { status: 'failed' }]), 'failed')
assert.equal(
  aggregateStatusKey([{ status: 'completed' }, { status: 'in_progress' }]),
  'in_progress'
)
assert.equal(auditItemsMatchStatus([{ status: 'not_completed' }], 'completed'), false)

// Index record totals are comparable counts; vector counts can exceed chunks.
const scale = indexCountScale([
  { chunkCount: 10, vectorCount: 20 },
  { chunkCount: 40, vectorCount: 0 }
])
assert.equal(scale, 40)
assert.equal(indexCountWidth(20, scale), 50)
assert.equal(indexCountWidth(10, scale), 25)
assert.equal(indexCountWidth(0, scale), 0)
assert.equal(indexCountWidth(undefined, scale), null, 'missing records must not render as zero')
assert.equal(indexRecordCount(NaN), null)
assert.equal(indexRecordCount(-1), null)
assert.equal(indexCountScale([]), 1)

// Summary colours must reflect observed data, never a fixed topic colour.
const metricSource = ref<number | undefined>(undefined)
const sectionLoaded = reactive({ files: false, reasoning: false })
const pageIndexLoaded = ref(false)
const knowledgeScorecard = ref<{ blockers: string[] } | null>(null)
const knowledgeCards = handler('./KnowledgeOverview.vue', 'knowledgeAuditCards', {
  computed,
  getOverviewMetricNumber: () => metricSource.value,
  sectionLoaded,
  filePagination: { total: 0 },
  files: ref([]),
  knowledgeTopTaskCounts: { vectorLoaded: false, vectorTotal: 0 },
  pageIndexLoaded,
  pageIndexNodes: ref([]),
  knowledgeScorecard,
  reasoningPagination: { total: 0 }
})
assert.deepEqual(
  knowledgeCards.value.map((card: { tone: string }) => card.tone),
  ['gray', 'gray', 'gray', 'gray']
)
knowledgeScorecard.value = { blockers: [] }
assert.equal(
  knowledgeCards.value[3].tone,
  'gray',
  'zero blockers alone is not proof of a healthy evaluation'
)
knowledgeScorecard.value = { blockers: ['missing evidence'] }
assert.equal(knowledgeCards.value[3].tone, 'red')
metricSource.value = 0
pageIndexLoaded.value = true
sectionLoaded.files = true
assert.deepEqual(
  knowledgeCards.value.slice(0, 3).map((card: { tone: string }) => card.tone),
  ['blue', 'blue', 'blue']
)
console.log('Inspection status navigation and index count presentation passed')
