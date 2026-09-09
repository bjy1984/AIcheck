import request from '@/axios'
import type { RuleConditions } from '@/views/AIReviewB/ruleConditionModel'

export interface RuleAtomicOption {
  id: string
  name: string
  nodeId: number
}

export interface ProjectRule {
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
export interface RuleTrialResult {
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
