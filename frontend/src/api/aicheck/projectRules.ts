import request from '@/axios'

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
}
export type RuleDraftInput = Pick<ProjectRule, 'inspectionItem' | 'standardText' | 'witnessText'>
const base = (projectId: string) => `/api/projects/${encodeURIComponent(projectId)}/rules/versions`
const headers = (etag?: string) => ({
  'Idempotency-Key': crypto.randomUUID(),
  ...(etag ? { 'If-Match': etag } : {})
})
export const listProjectRules = (projectId: string) =>
  request.get<{ items: ProjectRule[] }>({ url: base(projectId) })
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
