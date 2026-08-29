import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import type { StandardKnowledgeRecord } from '@/api/aicheck'
import {
  canonicalOverviewRows,
  canonicalTabLoadRequest,
  canonicalWarningMessages,
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
assert.equal(canonicalTabLoadRequest('overview'), undefined)
assert.equal(canonicalTabLoadRequest('completeness'), undefined)
for (const tab of ['structure', 'tables', 'relations']) {
  assert.deepEqual(canonicalTabLoadRequest(tab), { includeBlocks: false, includeHistory: false })
}
assert.deepEqual(canonicalTabLoadRequest('history'), {
  includeBlocks: false,
  includeHistory: true
})

const component = readFileSync(
  fileURLToPath(new URL('./components/StandardCanonicalDetail.vue', import.meta.url)),
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
assert.match(component, /getKnowledgeFileCanonicalApi/, '全集必须通过 canonical API 获取')
assert.match(component, /@tab-change="handleTabChange"/, '全集 API 必须由页签打开事件触发')
assert.doesNotMatch(
  component,
  /onMounted\([^)]*getKnowledgeFileCanonicalApi/s,
  '概览打开时不得预取全集'
)
assert.doesNotMatch(component, /v-html/, '标准表格和来源内容不得直接渲染来源 HTML')
assert.doesNotMatch(component, /没有识别出证书编号、设计压力/, '标准详情不得显示项目资料告警')

const canonicalStart = dialog.indexOf('<StandardCanonicalDetail')
const projectFallback = dialog.indexOf('<template v-else>', canonicalStart)
const projectWarning = dialog.indexOf('没有识别出证书编号、设计压力', canonicalStart)
assert.ok(canonicalStart >= 0, '公共文件详情必须接入标准 canonical 详情')
assert.ok(projectFallback > canonicalStart, '项目资料 OCR 界面必须放在标准详情的 v-else 分支')
assert.ok(projectWarning > projectFallback, '项目资料告警只能出现在非标准文档分支')
assert.match(
  overview,
  /const isStandardFile =[\s\S]{0,500}source\.sourceType === 'standard'[\s\S]{0,500}materialTypeCode: 'standard_reference'/,
  '知识库打开标准文件时必须保留标准模式，不能因旧详情缺少资料类型而落回项目资料 UI'
)
