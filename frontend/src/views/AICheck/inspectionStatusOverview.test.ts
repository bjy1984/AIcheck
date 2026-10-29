import assert from 'node:assert/strict'
import { computed, nextTick, reactive, ref } from 'vue'
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
const inspectionNodePage = ref(5)
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
let scrollTarget = ''
const select = handler('./Workbench.vue', 'selectInspectionStatus', {
  inspectionAuditStatusFilter,
  inspectionOnlyAttentionNodes,
  inspectionNodePage,
  nextTick,
  document: {
    getElementById: (id: string) => ({
      scrollIntoView: () => {
        scrollTarget = id
      }
    })
  }
})
const attentionChanged = handler('./Workbench.vue', 'changeInspectionAttentionFilter', {
  inspectionAuditStatusFilter,
  inspectionNodePage
})
const visibleIds = () => visible.value.map((row: { node: { nodeId: number } }) => row.node.nodeId)
assert.deepEqual(
  visibleIds(),
  [1, 2],
  'the existing default continues to show nodes needing action'
)
await select('completed')
assert.deepEqual(
  visibleIds(),
  [1],
  'a status matches any audit item in a node, not only its aggregate state'
)
assert.equal(
  aggregateNodeStatus(inspectionAuditOverviewNodeMap.value.get(1)?.items).tone,
  'attention'
)
assert.equal(inspectionNodePage.value, 1, 'chart navigation returns to the first visible page')
assert.equal(inspectionOnlyAttentionNodes.value, false)
assert.equal(scrollTarget, 'inspection-overview-nodes')
await select('failed')
assert.deepEqual(visibleIds(), [2], 'failed is separate from needs-attention')
await select('in_progress')
assert.deepEqual(visibleIds(), [3])
inspectionAuditOverviewNodeMap.value.delete(3)
assert.deepEqual(visibleIds(), [], 'empty filtered results never fall back to unrelated nodes')
await select(null)
assert.deepEqual(visibleIds(), [1, 2, 3, 4], 'clearing chart filter restores all nodes')
await select('not_started')
inspectionOnlyAttentionNodes.value = true
attentionChanged()
assert.equal(inspectionAuditStatusFilter.value, null)
assert.deepEqual(visibleIds(), [1, 2], 'the existing attention checkbox clears the chart filter')
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
