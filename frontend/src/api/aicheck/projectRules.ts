import request from '@/axios'
import type { RuleConditions } from '@/views/AIReviewB/ruleConditionModel'

export interface RuleAtomicOption {
  id: string
  name: string
  nodeId: number
}

export interface ProjectRule {
  ruleKey?: string
  id: string
  projectId?: string
  nodeIds: number[]
  status: string
  version: string
  etag: string
  inspectionItem: string
  standardText: string
  witnessText: string
  executionConditions?: RuleConditions
}
export type RuleDraftInput = Pick<
  ProjectRule,
  'inspectionItem' | 'standardText' | 'witnessText' | 'executionConditions'
>
const base = (projectId: string) => `/api/projects/${encodeURIComponent(projectId)}/rules/versions`
const headers = (etag?: string) => ({
  'Idempotency-Key': crypto.randomUUID(),
  ...(etag ? { 'If-Match': etag } : {})
})
export const listProjectRules = (projectId: string) =>
  request.get<{ items: ProjectRule[]; atomicChecks: RuleAtomicOption[] }>({ url: base(projectId) })
export const createProjectRule = (projectId: string, nodeId: number, data: RuleDraftInput) =>
  request.post<{ rule: ProjectRule }>({
    url: base(projectId),
    data: { ...data, nodeIds: [nodeId] },
    headers: headers()
  })
export const saveProjectRule = (projectId: string, rule: ProjectRule, data: RuleDraftInput) =>
  request.patch<{ rule: ProjectRule }>({
    url: `${base(projectId)}/${encodeURIComponent(rule.id)}`,
    data,
    headers: headers(rule.etag)
  })
export const forkProjectRule = (projectId: string, rule: ProjectRule) =>
  request.post<{ rule: ProjectRule }>({
    url: `${base(projectId)}/${encodeURIComponent(rule.id)}/fork`,
    data: {},
    headers: headers()
  })

export interface RuleFactCandidate {
  candidateId: string
  value: unknown
  unit?: string
  objectType?: string
  objectId?: string
  evidenceRefs: Array<{
    documentVersionId: string
    fieldId?: string
    pageNo?: number
    bbox?: number[]
  }>
}
export interface RuleObjectMapping {
  subject: { objectType: string; objectId: string }
  fields: Record<string, string>
  confirmedSameObject: boolean
}
export interface RuleObjectMappingRequest {
  selection: RuleObjectMapping
  ruleVersionId: string
  ruleRevision: number
  sourceSnapshotHash: string
}
export interface RuleTrialResult {
  sourcePageRanges?: Record<string, { start: number; end: number }> | null
  sourceDocuments?: Array<{
    documentId: string
    versionId: string
    fileName: string
    versionNo?: string
    pageRange?: { start: number; end: number }
  }>
  factCandidates?: Record<string, RuleFactCandidate[]>
  objectMappingSnapshot?: { snapshotHash: string; selection: RuleObjectMapping }
  result: string
  ruleRevision: number
  sourceMode?: string
  sourceReviewRunId?: string
  sourceSnapshotHash?: string
  factDiagnostics?: Record<string, string>
  bindingPlan?: { replacements: Array<{ atomicCheckId: string }>; retainedAtomicCheckIds: string[] }
  checks: Array<{ id: string; field: string; result: string; reason: string }>
}
export const trialProjectRule = (
  projectId: string,
  rule: ProjectRule,
  source:
    | { facts: Record<string, unknown>; reviewRunId?: never }
    | { reviewRunId: string; facts?: never; objectMapping?: RuleObjectMapping }
) =>
  request.post<RuleTrialResult>({
    url: `${base(projectId)}/${encodeURIComponent(rule.id)}/trial`,
    data: source,
    headers: headers(rule.etag)
  })

export type RuleReleaseAction = 'publish' | 'rollback'
export interface RuleReleaseInput {
  reason: string
  targetVersionId?: string
}
export interface RuleReleasePreview {
  previewId: string
  expiresAt: string
  impact: {
    nodeIds: number[]
    warnings: string[]
    changes: Array<{
      field: string
      label: string
      before: unknown
      after: unknown
      fromRuleVersionId?: string
      fromRuleScope?: 'project' | 'platform'
    }>
  }
}
export const previewProjectRuleRelease = (
  projectId: string,
  ruleId: string,
  action: RuleReleaseAction,
  data: RuleReleaseInput
) =>
  request.post<RuleReleasePreview>({
    url: `${base(projectId)}/${encodeURIComponent(ruleId)}/${action}-preview`,
    data
  })
export const applyProjectRuleRelease = (
  projectId: string,
  rule: ProjectRule,
  action: RuleReleaseAction,
  data: RuleReleaseInput & { previewId: string },
  idempotencyKey: string
) =>
  request.post<{ rule: ProjectRule; target?: ProjectRule }>({
    url: `${base(projectId)}/${encodeURIComponent(rule.id)}/${action}`,
    data,
    headers: { 'If-Match': rule.etag, 'Idempotency-Key': idempotencyKey }
  })

export interface RuleDraftSuggestion {
  draft: RuleDraftInput
  questions: string[]
  promptVersion: string
  requiresHumanConfirmation: true
  saved: false
}
export const suggestProjectRule = (projectId: string, nodeId: number, description: string) =>
  request.post<RuleDraftSuggestion>({
    url: `/api/projects/${encodeURIComponent(projectId)}/rules/draft-suggestion`,
    data: { nodeId, description }
  })
