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
  verification?: { status: string; authoritative: false }
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
export const listHandoffs = (projectId: string, runId: string, page: number) =>
  request.get<{ items: Handoff[]; total: number }>({
    url: base(projectId),
    params: { targetRunId: runId, page, pageSize: 20 }
  })
export const getHandoff = (projectId: string, id: string) =>
  request.get<Handoff>({ url: `${base(projectId)}/${encodeURIComponent(id)}` })
export const verifyHandoff = (projectId: string, id: string, data: HandoffDecision, key: string) =>
  request.post<Handoff>({
    url: `${base(projectId)}/${encodeURIComponent(id)}/verifications`,
    data,
    headers: { 'Idempotency-Key': key }
  })
