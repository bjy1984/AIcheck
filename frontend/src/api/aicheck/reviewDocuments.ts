import request from '@/axios'
import type { HandoffSelection } from './reviewHandoffs'
import type { RuleObjectMappingRequest } from './projectRules'
import type { DocumentAsset } from '@/types/aicheck'

export type ReviewDocument = DocumentAsset & {
  bodyUploaded?: boolean
  jevRoutingDecision?: {
    status: string
    model: string
    documentVersionId: string
    nodeScores?: Array<{ nodeId: number; choice: 'yes' | 'no' | 'uncertain'; confidence: number }>
    /** 后端认可的建议：选「是」、把握值够，且没被监检员否决过 */
    suggestedNodeIds?: number[]
    /** 监检员已判定不属于的节点：原始分数只留作审计，不再提示 */
    humanRejectedNodeIds?: number[]
  }
}

export type ReviewDocumentSelection = {
  versions: Array<{
    documentId: string
    versionId: string
    fileName: string
    versionNo?: string
    pageRange?: { start: number; end: number }
  }>
  handoffSelection?: HandoffSelection
  /** 记录表有多个对象时，只审这些（与 conditionObjectMapping 二选一） */
  selectedObjectIds?: string[]
  pageScopeExplicit?: boolean
  conditionObjectMapping?: RuleObjectMappingRequest
  reviewMode: 'formal' | 'gap_precheck'
}

export const listReviewDocuments = (
  projectId: string,
  params: { keyword: string; page: number; pageSize: number }
) =>
  request.get<{ items: ReviewDocument[]; total: number }>({
    url: `/api/projects/${projectId}/documents`,
    params
  })

export const getReviewVersionOriginal = async (
  projectId: string,
  documentId: string,
  versionId: string
) => {
  const response = await request.get<Blob>({
    url: `/api/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(documentId)}/original`,
    params: { versionId, disposition: 'inline' },
    responseType: 'blob'
  })
  if (!(response.data instanceof Blob) || response.data.type.includes('application/json'))
    throw new Error('所选版本原文不可用')
  return response.data
}
