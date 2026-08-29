import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import type { StandardCanonicalContentItem, StandardKnowledgeRecord } from '@/api/aicheck'
import {
  beginCanonicalSectionLoad,
  canonicalAuthorityBadge,
  canonicalBlockWindow,
  canonicalCompletenessRows,
  canonicalDetailIdentity,
  canonicalItemLocateEvidence,
  canonicalLocationAfterIdentityChange,
  canonicalLocateKey,
  canonicalNextBlockPage,
  canonicalOverviewRows,
  canonicalPreviousBlockPage,
  canonicalSectionPayload,
  canonicalTabQuery,
  canonicalWarningMessages,
  completeCanonicalSectionLoad,
  createCanonicalDetailLoadState,
  failCanonicalSectionLoad,
  resetCanonicalDetailLoadState,
  visibleCanonicalSourceValues
} from './components/standardCanonicalPresentation'

const canonicalFixture = (): StandardKnowledgeRecord => ({
  id: 'SKR-1',
  knowledgeFileId: 'KF-1',
  canonicalVersion: 'standard-knowledge-canonical@1',
  identity: {
    standardCode: {
      id: 'FIELD-CODE',
      key: 'standardCode',
      value: 'NB/T 47013.10-2015',
      authority: 'current',
      selectedSourceId: 'PARSE-NEW',
      sources: [
        {
          value: 'NB/T 47013.10-2015',
          sourceId: 'PARSE-NEW',
          sourceType: 'new_mineru'
        },
        {
          value: 'NB/T 47013.10-2010',
          sourceId: 'PARSE-OLD',
          sourceType: 'legacy_ocr'
        }
      ]
    },
    standardNameZh: {
      id: 'FIELD-NAME',
      key: 'standardNameZh',
      value: '承压设备无损检测',
      authority: 'current',
      selectedSourceId: 'PARSE-NEW',
      sources: []
    }
  },
  version: {
    publicationDate: {
      id: 'FIELD-PUBLISHED',
      key: 'publicationDate',
      value: '2015-04-02',
      authority: 'current',
      selectedSourceId: 'PARSE-NEW',
      sources: []
    },
    effectiveDate: {
      id: 'FIELD-EFFECTIVE',
      key: 'effectiveDate',
      value: '2015-09-01',
      authority: 'current',
      selectedSourceId: 'PARSE-NEW',
      sources: []
    },
    issuingAuthority: {
      id: 'FIELD-AUTHORITY',
      key: 'issuingAuthority',
      value: '国家能源局',
      authority: 'current',
      selectedSourceId: 'PARSE-NEW',
      sources: []
    },
    status: {
      id: 'FIELD-STATUS',
      key: 'status',
      value: '现行',
      authority: 'current',
      selectedSourceId: 'PARSE-NEW',
      sources: []
    }
  },
  metadata: {},
  sections: [],
  clauses: [],
  tables: [],
  equations: [],
  images: [],
  seals: [],
  normativeReferences: [],
  replacementRelations: [],
  businessRelations: [],
  completeness: {
    overall: 'partial',
    missingCategories: ['normativeReferences'],
    normativeReferences: { status: 'missing', count: 0 }
  },
  evidence: [],
  provenance: [],
  history: []
})

const record = canonicalFixture()

assert.deepEqual(
  canonicalOverviewRows(record).map((row) => row.label),
  ['标准编号', '标准名称', '发布日期', '实施日期', '发布机构', '状态']
)
assert.equal(canonicalOverviewRows(record)[2].value, '2015-04-02')
assert.deepEqual(canonicalWarningMessages(record), ['缺少规范性引用关系'])
assert.deepEqual(visibleCanonicalSourceValues(record.identity.standardCode), [
  { value: 'NB/T 47013.10-2015', sourceType: 'new_mineru', selected: true },
  { value: 'NB/T 47013.10-2010', sourceType: 'legacy_ocr', selected: false }
])
assert.equal(canonicalTabQuery('overview'), undefined)
assert.equal(canonicalTabQuery('completeness'), undefined)
assert.deepEqual(canonicalTabQuery('structure'), {
  section: 'structure',
  arrays: ['sections', 'clauses', 'blocks'],
  params: { contentGroup: 'structure', includeBlocks: true, includeHistory: false }
})
assert.deepEqual(canonicalTabQuery('tables'), {
  section: 'tables',
  arrays: ['tables', 'equations', 'images', 'seals'],
  params: { contentGroup: 'tables', includeBlocks: false, includeHistory: false }
})
assert.deepEqual(canonicalTabQuery('relations'), {
  section: 'relations',
  arrays: ['normativeReferences', 'replacementRelations', 'businessRelations'],
  params: { contentGroup: 'relations', includeBlocks: false, includeHistory: false }
})
assert.deepEqual(canonicalTabQuery('history'), {
  section: 'history',
  arrays: ['history'],
  params: { contentGroup: 'history', includeBlocks: false, includeHistory: true }
})

const conflictingLocationItem: StandardCanonicalContentItem = {
  id: 'CLAUSE-CONFLICT',
  authority: 'current',
  selectedSourceId: 'SELECTED',
  pageNo: 2,
  bbox: [70, 80, 90, 100],
  text: '冲突位置',
  sources: [
    { sourceId: 'SELECTED', sourceType: 'new_mineru', pageNo: 2 },
    { sourceId: 'SUPPORTING', sourceType: 'legacy_ocr', pageNo: 7, bbox: [70, 80, 90, 100] }
  ]
}
assert.deepEqual(canonicalItemLocateEvidence(conflictingLocationItem), {
  sourceId: 'SELECTED',
  sourceType: 'new_mineru',
  pageNo: 2,
  key: 'CLAUSE-CONFLICT',
  quotedText: '冲突位置'
})

const promotedLocationItem: StandardCanonicalContentItem = {
  ...conflictingLocationItem,
  pageNo: 7
}
assert.deepEqual(canonicalItemLocateEvidence(promotedLocationItem), {
  sourceId: 'SUPPORTING',
  sourceType: 'legacy_ocr',
  pageNo: 7,
  bbox: [70, 80, 90, 100],
  key: 'CLAUSE-CONFLICT',
  quotedText: '冲突位置'
})

assert.equal(canonicalAuthorityBadge('legacy_only'), 'legacy_only')
assert.equal(canonicalAuthorityBadge('current'), '')
assert.notEqual(
  canonicalLocateKey({ key: 'FIELD-CODE', sourceId: 'PARSE-NEW', pageNo: 1 }),
  canonicalLocateKey({ key: 'FIELD-CODE', sourceId: 'PARSE-OLD', pageNo: 1 })
)
assert.notEqual(
  canonicalLocateKey({ key: 'FIELD-CODE', pageNo: 1, quotedText: '新识别值' }),
  canonicalLocateKey({ key: 'FIELD-CODE', pageNo: 1, value: '冲突旧值' }),
  '缺少 sourceId/contentHash 的冲突值仍必须产生不同定位 key'
)
const deterministicLocateEvidence = {
  key: 'FIELD-CODE',
  sourceId: '',
  pageNo: 0,
  bbox: null,
  contentHash: '',
  quotedText: '缺少来源元数据但值相同'
}
assert.equal(
  canonicalLocateKey(deterministicLocateEvidence),
  canonicalLocateKey({ ...deterministicLocateEvidence }),
  '完整身份材料相同时定位 key 必须确定'
)
assert.notEqual(
  canonicalLocateKey(deterministicLocateEvidence),
  canonicalLocateKey({ ...deterministicLocateEvidence, quotedText: '缺少来源元数据但值不同' })
)

const completeness = {
  overall: 'partial' as const,
  missingCategories: ['identity'],
  identity: { status: 'partial', missing: ['standardCode', 'standardNameZh'] }
}
assert.deepEqual(canonicalCompletenessRows(completeness)[0], {
  key: 'identity',
  label: '标准身份',
  status: 'partial',
  count: undefined,
  located: undefined,
  total: undefined,
  missingFields: ['标准编号', '标准名称'],
  reason: '标准编号或标准名称不完整；缺少字段：标准编号、标准名称'
})

const recordGenerationOne = {
  ...record,
  knowledgeFileId: 'KF-A',
  documentId: 'DOC-A',
  documentVersionId: 'DV-A',
  sourceFingerprint: 'sha256:generation-one',
  canonicalVersion: 'standard-knowledge-canonical@1',
  kbVersion: 'kb-v1'
}
const recordGenerationTwo = {
  ...recordGenerationOne,
  sourceFingerprint: 'sha256:generation-two'
}
const fileA = canonicalDetailIdentity(recordGenerationOne, 'DOC-A')
const regeneratedFileA = canonicalDetailIdentity(recordGenerationTwo, 'DOC-A')
assert.notEqual(fileA, regeneratedFileA)
assert.equal(
  canonicalLocationAfterIdentityChange({ key: 'canonical:old-location' }, fileA, regeneratedFileA),
  undefined,
  '同文件 canonical fingerprint 变化时必须清空已选定位'
)
let loadState = createCanonicalDetailLoadState(fileA)
const structureStart = beginCanonicalSectionLoad(loadState, 'structure')
loadState = structureStart.state
assert.equal(loadState.sections.structure.loading, true)
assert.equal(loadState.sections.history.loading, false)
loadState = failCanonicalSectionLoad(loadState, structureStart.token, '章节失败')
assert.equal(loadState.sections.structure.error, '章节失败')
assert.equal(loadState.sections.history.error, '')

const historyStart = beginCanonicalSectionLoad(loadState, 'history')
loadState = historyStart.state
assert.equal(loadState.sections.history.loading, true)
assert.equal(loadState.sections.structure.loading, false)
assert.equal(loadState.sections.structure.error, '章节失败')
const fileBState = resetCanonicalDetailLoadState(loadState, regeneratedFileA)
assert.equal(fileBState.sections.structure.data, undefined)
assert.equal(fileBState.sections.structure.error, '')
assert.equal(fileBState.sections.history.loading, false)
assert.equal(fileBState.generation, loadState.generation + 1)
assert.deepEqual(
  completeCanonicalSectionLoad(fileBState, historyStart.token, record),
  fileBState,
  '旧文件的迟到响应必须被 generation token 丢弃'
)

const tablePayload = canonicalSectionPayload(canonicalTabQuery('tables')!, {
  ...record,
  sections: [{ ...conflictingLocationItem, id: 'SECTION-HIDDEN' }],
  clauses: [{ ...conflictingLocationItem, id: 'CLAUSE-HIDDEN' }],
  blocks: [{ ...conflictingLocationItem, id: 'BLOCK-HIDDEN' }],
  tables: [{ ...conflictingLocationItem, id: 'TABLE-VISIBLE' }]
})
assert.equal(tablePayload.tables.length, 1)
assert.equal(tablePayload.sections.length, 0)
assert.equal(tablePayload.clauses.length, 0)
assert.equal(tablePayload.blocks, undefined)

const fiveThousandBlocks = Array.from({ length: 5000 }, (_, index) => ({ id: `BLOCK-${index}` }))
const initialBlockWindow = canonicalBlockWindow(fiveThousandBlocks, 0)
assert.deepEqual(
  [initialBlockWindow.items[0].id, initialBlockWindow.items.at(-1)?.id],
  ['BLOCK-0', 'BLOCK-119']
)
const nextBlockPage = canonicalNextBlockPage(initialBlockWindow.pageIndex, 5000)
const nextBlockWindow = canonicalBlockWindow(fiveThousandBlocks, nextBlockPage)
assert.deepEqual(
  [nextBlockWindow.items[0].id, nextBlockWindow.items.at(-1)?.id],
  ['BLOCK-120', 'BLOCK-239']
)
const lastBlockWindow = canonicalBlockWindow(fiveThousandBlocks, 999)
assert.deepEqual(
  [lastBlockWindow.pageIndex, lastBlockWindow.items[0].id, lastBlockWindow.items.at(-1)?.id],
  [41, 'BLOCK-4920', 'BLOCK-4999']
)
assert.ok(
  [initialBlockWindow, nextBlockWindow, lastBlockWindow].every(
    (window) => window.items.length <= 120
  ),
  '任一正文窗口挂载节点不得超过 120'
)
assert.equal(canonicalNextBlockPage(lastBlockWindow.pageIndex, 5000), 41)
assert.equal(canonicalPreviousBlockPage(0), 0)
assert.equal(canonicalPreviousBlockPage(2), 1)

const component = readFileSync(
  fileURLToPath(new URL('./components/StandardCanonicalDetail.vue', import.meta.url)),
  'utf8'
)
const presentation = readFileSync(
  fileURLToPath(new URL('./components/standardCanonicalPresentation.ts', import.meta.url)),
  'utf8'
)
const dialog = readFileSync(
  fileURLToPath(new URL('./components/FileDetailDialog.vue', import.meta.url)),
  'utf8'
)
const overview = readFileSync(
  fileURLToPath(new URL('./KnowledgeOverview.vue', import.meta.url)),
  'utf8'
)

for (const tab of ['概览', '章节条款', '表格公式', '引用关系', '完整度', '来源历史']) {
  assert.match(component, new RegExp(`label="${tab}"`), `标准详情缺少“${tab}”页签`)
}
for (const tab of ['structure', 'tables', 'relations', 'history']) {
  assert.match(
    component,
    new RegExp(`<ElTabPane[^>]*name="${tab}"[^>]*lazy`),
    `${tab} 页签必须延迟实例化`
  )
  assert.match(
    component,
    new RegExp(`v-if="activeTab === '${tab}'"`),
    `${tab} 页签隐藏时不得实例化大数组内容`
  )
}
assert.match(component, /getKnowledgeFileCanonicalApi/, '全集必须通过 canonical API 获取')
assert.match(component, /@tab-change="handleTabChange"/, '全集 API 必须由页签打开事件触发')
assert.match(component, /v-for="item in visibleBlocks"/, '正文块必须只实例化当前渐进窗口')
assert.match(component, />\s*加载更多\s*</, '正文块必须提供加载更多入口')
assert.doesNotMatch(
  component,
  /v-for="item in structureRecord\.blocks"/,
  '不得一次实例化全部正文块'
)
assert.doesNotMatch(presentation, /shortStableHash/, '定位 key 不得使用 32 位摘要')
assert.doesNotMatch(
  component,
  /onMounted\([^)]*getKnowledgeFileCanonicalApi/s,
  '概览打开时不得预取全集'
)
assert.doesNotMatch(component, /v-html/, '标准表格和来源内容不得直接渲染来源 HTML')
assert.doesNotMatch(component, /没有识别出证书编号、设计压力/, '标准详情不得显示项目资料告警')
assert.match(
  component,
  /canonicalAuthorityBadge\(item\.authority\)/,
  '结构化条目必须接入权威性徽标'
)

const canonicalStart = dialog.indexOf('<StandardCanonicalDetail')
const projectFallback = dialog.indexOf('<template v-else>', canonicalStart)
const projectWarning = dialog.indexOf('没有识别出证书编号、设计压力', canonicalStart)
assert.ok(canonicalStart >= 0, '公共文件详情必须接入标准 canonical 详情')
assert.ok(projectFallback > canonicalStart, '项目资料 OCR 界面必须放在标准详情的 v-else 分支')
assert.ok(projectWarning > projectFallback, '项目资料告警只能出现在非标准文档分支')
assert.match(
  dialog,
  /canonicalDetailIdentity\(standardCanonical\.value, document\.value\?\.id\)/,
  '文件定位状态必须使用与分区缓存相同的 canonical generation identity'
)
assert.match(
  overview,
  /const isStandardFile =[\s\S]{0,500}source\.sourceType === 'standard'[\s\S]{0,500}materialTypeCode: 'standard_reference'/,
  '知识库打开标准文件时必须保留标准模式，不能因旧详情缺少资料类型而落回项目资料 UI'
)
