import request from '@/axios'

export type ImportantRule = {
  nodeId: number
  code: string
  name: string
  displayName?: string
  group: string
  sections: Array<{ title: string; text: string }>
  version: string
  source: string
}
export type ImportantFile = { documentId: string; versionId: string; fileName: string }
export type NodeRecommendation = {
  nodeId: number
  recommended: boolean
  message: string
  documents: Array<ImportantFile & { reason: string }>
}
export type ImportantEvidence = {
  documentId?: string
  documentVersionId?: string
  fileName?: string
  pageNo?: number
  quotedText?: string
  quote?: string
}
export type ImportantOutcome = {
  atomicCheckId: string
  name: string
  result: string
  reason?: string
  checks?: Array<{ code: string; actual?: unknown; expected?: unknown; passed?: boolean }>
  facts?: Array<{ label: string; evidence?: ImportantEvidence[] }>
}
export type ImportantRun = {
  id: string
  nodeId: number
  reviewRunId?: string
  status: string
  startedAt: string
  documents: ImportantFile[]
  documentsChanged: boolean
  rule: ImportantRule
  errorMessage?: string
  summary?: string
  atomicCheckOutcomes: ImportantOutcome[]
  automationLimitations?: Array<{
    atomicCheckId: string
    code: string
    requiresHumanReview: boolean
  }>
  findingDrafts: Array<{
    id?: string
    title: string
    description: string
    suggestedAction?: string
    evidenceRefs?: ImportantEvidence[]
  }>
}
const base = (id: string) => `/api/projects/${encodeURIComponent(id)}/inspection/important-review`
export const importantReviewApi = {
  config: (id: string) =>
    request.get<{ nodes: ImportantRule[]; enabled: boolean; disabledReason: string }>({
      url: base(id)
    }),
  analyze: (id: string, versions: string[]) =>
    request.post<{ nodes: NodeRecommendation[] }>({
      url: `${base(id)}/analyze`,
      data: { inputDocumentVersionIds: versions }
    }),
  start: (id: string, nodeId: number, versions: string[], key: string) =>
    request.post<{ runId: string }>({
      url: `${base(id)}/nodes/${nodeId}/runs`,
      data: { inputDocumentVersionIds: versions },
      headers: { 'Idempotency-Key': key }
    }),
  runs: (id: string) => request.get<{ items: ImportantRun[] }>({ url: `${base(id)}/runs` })
}
