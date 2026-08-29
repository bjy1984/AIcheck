import type {
  StandardCanonicalCompleteness,
  StandardCanonicalContentItem,
  StandardCanonicalEvidence,
  StandardCanonicalField,
  StandardCanonicalContentGroup,
  StandardKnowledgeRecord,
  StandardKnowledgeRecordScoped,
  StandardKnowledgeRecordSummary
} from '@/api/aicheck'
import { normalizeBbox } from '@/utils/bboxHighlight'

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

export type CanonicalCompletenessRow = {
  key: string
  label: string
  status: string
  count?: number
  located?: number
  total?: number
  missingFields: string[]
  reason: string
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

export const canonicalCompletenessRows = (
  completeness: StandardCanonicalCompleteness
): CanonicalCompletenessRow[] =>
  Object.entries(completeness)
    .filter(([key]) => key !== 'overall' && key !== 'missingCategories')
    .map(([key, detail]) => {
      const data = detail && typeof detail === 'object' ? (detail as Record<string, unknown>) : {}
      const status = String(data.status || 'missing')
      const missingFields = Array.isArray(data.missing)
        ? data.missing.map((field) => CANONICAL_FIELD_LABELS[String(field)] || String(field))
        : []
      const categoryMessage =
        status === 'missing' || status === 'partial'
          ? CANONICAL_WARNING_COPY[key] || `“${CANONICAL_CATEGORY_LABELS[key] || key}”信息不完整`
          : ''
      return {
        key,
        label: CANONICAL_CATEGORY_LABELS[key] || key,
        status,
        count: typeof data.count === 'number' ? data.count : undefined,
        located: typeof data.located === 'number' ? data.located : undefined,
        total: typeof data.total === 'number' ? data.total : undefined,
        missingFields,
        reason: [
          categoryMessage,
          missingFields.length ? `缺少字段：${missingFields.join('、')}` : ''
        ]
          .filter(Boolean)
          .join('；')
      }
    })

const bboxEquals = (left?: number[] | null, right?: number[] | null) => {
  const normalizedLeft = normalizeBbox(left)
  const normalizedRight = normalizeBbox(right)
  return Boolean(
    normalizedLeft &&
      normalizedRight &&
      normalizedLeft.every((value, index) => value === normalizedRight[index])
  )
}

export const canonicalItemLocateEvidence = (
  item: StandardCanonicalContentItem
): StandardCanonicalEvidence => {
  const selected = item.sources.find((source) => source.sourceId === item.selectedSourceId)
  const selectedHasCompleteBox = Boolean(selected?.pageNo && normalizeBbox(selected.bbox))
  const promoted =
    item.pageNo && normalizeBbox(item.bbox)
      ? item.sources.find(
          (source) => source.pageNo === item.pageNo && bboxEquals(source.bbox, item.bbox)
        )
      : undefined
  const locatedSource = selectedHasCompleteBox ? selected : promoted || selected
  return {
    ...locatedSource,
    key: item.id,
    quotedText:
      locatedSource?.quotedText || item.text || item.caption || item.latex || item.title || ''
  }
}

export const canonicalFieldLocateEvidence = (
  field: StandardCanonicalField
): StandardCanonicalEvidence => {
  const selected = field.sources.find((source) => source.sourceId === field.selectedSourceId)
  return {
    ...selected,
    key: field.id,
    value: field.value,
    quotedText: selected?.quotedText || String(field.value ?? '')
  }
}

export const canonicalAuthorityBadge = (authority: StandardCanonicalContentItem['authority']) =>
  authority === 'legacy_only' ? 'legacy_only' : ''

const canonicalValueText = (value: unknown) => {
  if (value === undefined) return ''
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

const shortStableHash = (value: string) => {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return (hash >>> 0).toString(16).padStart(8, '0')
}

export const canonicalLocateKey = (evidence: StandardCanonicalEvidence) => {
  const material = JSON.stringify({
    ownerKey: evidence.key ?? '',
    sourceId: evidence.sourceId ?? '',
    pageNo: evidence.pageNo ?? '',
    bbox: normalizeBbox(evidence.bbox) ?? [],
    contentHash: evidence.contentHash ?? '',
    text: evidence.quotedText ?? canonicalValueText(evidence.value)
  })
  return `canonical:${encodeURIComponent(String(evidence.key ?? ''))}:${shortStableHash(material)}`
}

export type CanonicalSectionKey = 'structure' | 'tables' | 'relations' | 'history'
export type CanonicalArrayKey =
  | 'sections'
  | 'clauses'
  | 'blocks'
  | 'tables'
  | 'equations'
  | 'images'
  | 'seals'
  | 'normativeReferences'
  | 'replacementRelations'
  | 'businessRelations'
  | 'history'

export type CanonicalTabQuery = {
  section: CanonicalSectionKey
  arrays: CanonicalArrayKey[]
  params: {
    contentGroup: StandardCanonicalContentGroup
    includeBlocks: boolean
    includeHistory: boolean
  }
}

const CANONICAL_TAB_QUERIES: Record<CanonicalSectionKey, CanonicalTabQuery> = {
  structure: {
    section: 'structure',
    arrays: ['sections', 'clauses', 'blocks'],
    params: { contentGroup: 'structure', includeBlocks: true, includeHistory: false }
  },
  tables: {
    section: 'tables',
    arrays: ['tables', 'equations', 'images', 'seals'],
    params: { contentGroup: 'tables', includeBlocks: false, includeHistory: false }
  },
  relations: {
    section: 'relations',
    arrays: ['normativeReferences', 'replacementRelations', 'businessRelations'],
    params: { contentGroup: 'relations', includeBlocks: false, includeHistory: false }
  },
  history: {
    section: 'history',
    arrays: ['history'],
    params: { contentGroup: 'history', includeBlocks: false, includeHistory: true }
  }
}

export const canonicalTabQuery = (tab: string): CanonicalTabQuery | undefined =>
  CANONICAL_TAB_QUERIES[tab as CanonicalSectionKey]

export const canonicalSectionPayload = (
  query: CanonicalTabQuery,
  record: StandardKnowledgeRecordScoped
): StandardKnowledgeRecord => {
  const payload: StandardKnowledgeRecord = {
    ...record,
    sections: [],
    clauses: [],
    blocks: undefined,
    tables: [],
    equations: [],
    images: [],
    seals: [],
    normativeReferences: [],
    replacementRelations: [],
    businessRelations: [],
    evidence: [],
    provenance: [],
    history: undefined
  }
  for (const key of query.arrays) {
    if (key === 'history') payload.history = record.history
    else if (key === 'blocks') payload.blocks = record.blocks
    else Object.assign(payload, { [key]: record[key] || [] })
  }
  return payload
}

export type CanonicalSectionLoad = {
  data?: StandardKnowledgeRecord
  loading: boolean
  error: string
  requestId: number
}

export type CanonicalDetailLoadState = {
  fileKey: string
  generation: number
  sections: Record<CanonicalSectionKey, CanonicalSectionLoad>
}

export type CanonicalSectionLoadToken = {
  fileKey: string
  generation: number
  section: CanonicalSectionKey
  requestId: number
}

const emptyCanonicalSectionLoad = (): CanonicalSectionLoad => ({
  loading: false,
  error: '',
  requestId: 0
})

type CanonicalGenerationRecord = Pick<
  StandardKnowledgeRecord | StandardKnowledgeRecordSummary,
  'knowledgeFileId' | 'documentVersionId' | 'sourceFingerprint' | 'canonicalVersion' | 'kbVersion'
> & { documentId?: string }

export const canonicalDetailIdentity = (
  record: CanonicalGenerationRecord,
  fallbackDocumentId?: string
) =>
  [
    record.documentId || fallbackDocumentId,
    record.knowledgeFileId,
    record.documentVersionId,
    record.sourceFingerprint,
    record.canonicalVersion,
    record.kbVersion
  ]
    .map((value) => encodeURIComponent(String(value || '')))
    .join(':')

export const canonicalLocationAfterIdentityChange = <T>(
  location: T | undefined,
  previousIdentity: string,
  nextIdentity: string
): T | undefined => (previousIdentity === nextIdentity ? location : undefined)

export const CANONICAL_BLOCK_BATCH_SIZE = 120

export const canonicalBlockPage = <T>(
  blocks: readonly T[],
  requestedLimit = CANONICAL_BLOCK_BATCH_SIZE
) => {
  const total = blocks.length
  const visibleCount = Math.min(total, Math.max(0, Math.floor(requestedLimit)))
  return {
    items: blocks.slice(0, visibleCount),
    visibleCount,
    total,
    hasMore: visibleCount < total
  }
}

export const canonicalNextBlockLimit = (
  currentLimit: number,
  total: number,
  batchSize = CANONICAL_BLOCK_BATCH_SIZE
) => Math.min(Math.max(0, total), Math.max(batchSize, currentLimit + batchSize))

export const createCanonicalDetailLoadState = (
  fileKey: string,
  generation = 0
): CanonicalDetailLoadState => ({
  fileKey,
  generation,
  sections: {
    structure: emptyCanonicalSectionLoad(),
    tables: emptyCanonicalSectionLoad(),
    relations: emptyCanonicalSectionLoad(),
    history: emptyCanonicalSectionLoad()
  }
})

export const resetCanonicalDetailLoadState = (
  state: CanonicalDetailLoadState,
  fileKey: string
): CanonicalDetailLoadState => createCanonicalDetailLoadState(fileKey, state.generation + 1)

export const beginCanonicalSectionLoad = (
  state: CanonicalDetailLoadState,
  section: CanonicalSectionKey
): { state: CanonicalDetailLoadState; token: CanonicalSectionLoadToken } => {
  const requestId = state.sections[section].requestId + 1
  return {
    state: {
      ...state,
      sections: {
        ...state.sections,
        [section]: { ...state.sections[section], loading: true, error: '', requestId }
      }
    },
    token: { fileKey: state.fileKey, generation: state.generation, section, requestId }
  }
}

const tokenMatches = (state: CanonicalDetailLoadState, token: CanonicalSectionLoadToken) =>
  state.fileKey === token.fileKey &&
  state.generation === token.generation &&
  state.sections[token.section].requestId === token.requestId

export const completeCanonicalSectionLoad = (
  state: CanonicalDetailLoadState,
  token: CanonicalSectionLoadToken,
  data: StandardKnowledgeRecord
): CanonicalDetailLoadState => {
  if (!tokenMatches(state, token)) return state
  return {
    ...state,
    sections: {
      ...state.sections,
      [token.section]: { ...state.sections[token.section], data, loading: false, error: '' }
    }
  }
}

export const failCanonicalSectionLoad = (
  state: CanonicalDetailLoadState,
  token: CanonicalSectionLoadToken,
  error: string
): CanonicalDetailLoadState => {
  if (!tokenMatches(state, token)) return state
  return {
    ...state,
    sections: {
      ...state.sections,
      [token.section]: { ...state.sections[token.section], loading: false, error }
    }
  }
}
