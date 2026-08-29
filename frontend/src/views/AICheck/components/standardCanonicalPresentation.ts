import type {
  StandardCanonicalField,
  StandardKnowledgeRecord,
  StandardKnowledgeRecordSummary
} from '@/api/aicheck'

type CanonicalSummaryRecord = Pick<
  StandardKnowledgeRecord | StandardKnowledgeRecordSummary,
  'identity' | 'version' | 'metadata' | 'completeness'
>

export const CANONICAL_WARNING_COPY: Record<string, string> = {
  identity: '标准编号或标准名称不完整',
  version: '标准版本信息不完整',
  metadata: '标准适用范围等元数据不完整',
  fullText: '标准全文结构不完整',
  sections: '章节结构不完整',
  clauses: '条款结构不完整',
  tables: '表格结构不完整',
  equations: '公式结构不完整',
  images: '图片信息不完整',
  seals: '印章信息不完整',
  normativeReferences: '缺少规范性引用关系',
  replacementRelations: '标准替代关系不完整',
  businessRelations: '关联业务规则或监检节点不完整',
  evidenceLocation: '部分信息无法定位原文',
  history: '历史识别来源不完整'
}

export const CANONICAL_CATEGORY_LABELS: Record<string, string> = {
  identity: '标准身份',
  version: '版本信息',
  metadata: '标准元数据',
  fullText: '标准全文',
  sections: '章节',
  clauses: '条款',
  tables: '表格',
  equations: '公式',
  images: '图片',
  seals: '印章',
  normativeReferences: '规范性引用',
  replacementRelations: '替代关系',
  businessRelations: '业务关系',
  evidenceLocation: '原文定位',
  history: '来源历史'
}

export const CANONICAL_FIELD_LABELS: Record<string, string> = {
  standardCode: '标准编号',
  standardNameZh: '标准名称',
  publicationDate: '发布日期',
  effectiveDate: '实施日期',
  issuingAuthority: '发布机构',
  status: '状态',
  scope: '适用范围',
  classification: '标准分类',
  replacementStandardCode: '替代标准'
}

export type CanonicalOverviewRow = {
  key: string
  label: string
  value: string
  field?: StandardCanonicalField
}

const overviewRow = (
  key: string,
  label: string,
  field?: StandardCanonicalField
): CanonicalOverviewRow => ({
  key,
  label,
  value: String(field?.value ?? '-'),
  field
})

export const canonicalOverviewRows = (record: CanonicalSummaryRecord): CanonicalOverviewRow[] => [
  overviewRow('standardCode', '标准编号', record.identity.standardCode),
  overviewRow('standardNameZh', '标准名称', record.identity.standardNameZh),
  overviewRow('publicationDate', '发布日期', record.version.publicationDate),
  overviewRow('effectiveDate', '实施日期', record.version.effectiveDate),
  overviewRow('issuingAuthority', '发布机构', record.version.issuingAuthority),
  overviewRow('status', '状态', record.version.status)
]

export const canonicalWarningMessages = (record: CanonicalSummaryRecord): string[] =>
  record.completeness.missingCategories.map(
    (key) => CANONICAL_WARNING_COPY[key] || `“${CANONICAL_CATEGORY_LABELS[key] || key}”信息不完整`
  )

export const visibleCanonicalSourceValues = (field: StandardCanonicalField) =>
  field.sources.map((source) => ({
    value: String(source.value ?? ''),
    sourceType: source.sourceType,
    selected: source.sourceId === field.selectedSourceId
  }))

export type CanonicalTabLoadRequest = {
  includeBlocks: false
  includeHistory: boolean
}

export const canonicalTabLoadRequest = (tab: string): CanonicalTabLoadRequest | undefined => {
  if (tab === 'history') return { includeBlocks: false, includeHistory: true }
  if (['structure', 'tables', 'relations'].includes(tab)) {
    return { includeBlocks: false, includeHistory: false }
  }
  return undefined
}
