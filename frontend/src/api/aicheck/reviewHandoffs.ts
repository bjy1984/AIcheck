import request from '@/axios'
import type { EvidenceLink } from '@/types/aicheck'

export type HandoffSubject = {
  objectType: string
  objectId: string
  repairRound: number
  eventId?: string
}
export type Handoff = {
  id: string
  projectId: string
  readContext?: { runId: string; relation: 'received' | 'used_input' }
  draft: {
    schemaVersion: string
    snapshotHash: string
    kind: string
    subject: HandoffSubject
    source: { runId: string; stationId: string; nodeId: number }
    target: { runId: string; stationId: string; nodeId: number }
    payload: Record<string, unknown>
    evidenceRefs: EvidenceLink[]
  }
  evidenceDocuments?: Array<{
    documentVersionId: string
    documentId: string
    fileName?: string
    fileType?: string
  }>
  validation: {
    status: string
    inputSourceCheck?: { status: string }
    evidenceLocationCheck?: { status: string }
  }
  verification?: { status: string; authoritative: false; latestVerificationId?: string }
  verifications?: Array<{
    id: string
    outcome: string
    reviewedByUserId: string
    createdAt: string
    note: string
  }>
}
export type HandoffDecision = {
  snapshotHash: string
  expectedPreviousId: string | null
  subject: HandoffSubject
  outcome: 'verified' | 'rejected'
  objectMatchConfirmed: boolean
  evidenceSupportConfirmed: boolean
  note: string
}
const base = (projectId: string) => `/api/projects/${encodeURIComponent(projectId)}/review-handoffs`
export type HandoffTarget = {
  runId: string
  nodeId: number
  stationId: string
  status?: string
  createdAt?: string
}
export type HandoffCreate = {
  sourceRunId: string
  targetRunId: string
  kind: 'collaboration'
  subject: HandoffSubject & { eventId: string }
  payload: { request: string }
  evidenceRefs: EvidenceLink[]
}
export const listHandoffTargets = (projectId: string, sourceRunId: string, page: number) =>
  request.get<{ items: HandoffTarget[]; total: number }>({
    url: `${base(projectId)}/targets`,
    params: { sourceRunId, page, pageSize: 20 }
  })
export const createHandoff = (projectId: string, data: HandoffCreate, key: string, etag?: string) =>
  request.post<{ id: string }>({
    url: base(projectId),
    data,
    headers: { 'Idempotency-Key': key, ...(etag ? { 'If-Match': etag } : {}) }
  })
export const listHandoffs = (projectId: string, runId: string, page: number) =>
  request.get<{ items: Handoff[]; total: number }>({
    url: base(projectId),
    params: { targetRunId: runId, page, pageSize: 20 }
  })
export const getHandoff = (projectId: string, id: string, contextRunId?: string) =>
  request.get<Handoff>({
    url: `${base(projectId)}/${encodeURIComponent(id)}`,
    params: contextRunId ? { contextRunId } : undefined
  })
export const verifyHandoff = (projectId: string, id: string, data: HandoffDecision, key: string) =>
  request.post<Handoff>({
    url: `${base(projectId)}/${encodeURIComponent(id)}/verifications`,
    data,
    headers: { 'Idempotency-Key': key }
  })

export type HandoffSelection = {
  subject: HandoffSubject & { eventId: string }
  confirmedSameObject: true
  items: Array<{ handoffId: string; verificationId: string }>
}
export type HandoffDependencies = {
  reviewRunId: string
  status: 'current' | 'not_used' | 'requires_revalidation'
  requiresRevalidation: boolean
  handoffIds?: string[]
  message?: string
  automaticRerun: false
}
export const getHandoffDependencies = (projectId: string, runId: string) =>
  request.get<HandoffDependencies>({
    url: `/api/projects/${encodeURIComponent(projectId)}/review-runs/${encodeURIComponent(runId)}/handoff-dependencies`
  })

export type HandoffNodeStatuses = {
  projectId: string
  items: Array<{
    nodeId: number
    status: 'current' | 'not_used' | 'requires_revalidation' | 'unavailable'
    requiresRevalidation: boolean | null
  }>
}
export const getHandoffNodeStatuses = (projectId: string) =>
  request.get<HandoffNodeStatuses>({
    url: `/api/projects/${encodeURIComponent(projectId)}/review-handoff-node-statuses`
  })
