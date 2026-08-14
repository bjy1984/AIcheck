export type ReviewWorkbenchContext =
  | { source: 'standalone' }
  | { source: 'waiting' }
  | { source: 'embedded'; projectId: string; nodeId: number }

export const resolveReviewWorkbenchContext = (input: {
  embedded: boolean
  projectId?: string
  nodeId?: number
}): ReviewWorkbenchContext => {
  if (!input.embedded) return { source: 'standalone' }
  const projectId = String(input.projectId || '').trim()
  const nodeId = Number(input.nodeId || 0)
  if (!projectId || !Number.isFinite(nodeId) || nodeId <= 0) return { source: 'waiting' }
  return { source: 'embedded', projectId, nodeId }
}
