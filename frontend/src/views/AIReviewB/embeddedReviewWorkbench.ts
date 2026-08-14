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

export type ReviewSidebarLayoutInput = {
  embedded: boolean
  leftCollapsed: boolean
  rightCollapsed: boolean
}

export type ReviewSidebarLayout = {
  layoutClasses: string[]
  leftLabel: string
  rightLabel: string
  leftExpanded: boolean
  rightExpanded: boolean
}

export const resolveReviewSidebarLayout = (
  input: ReviewSidebarLayoutInput
): ReviewSidebarLayout => {
  const leftCollapsed = !input.embedded && input.leftCollapsed
  const rightCollapsed = !input.embedded && input.rightCollapsed

  return {
    layoutClasses: [
      ...(leftCollapsed ? ['is-left-collapsed'] : []),
      ...(rightCollapsed ? ['is-right-collapsed'] : [])
    ],
    leftLabel: leftCollapsed ? '展开节点导航' : '收起节点导航',
    rightLabel: rightCollapsed ? '展开上下文' : '收起上下文',
    leftExpanded: !leftCollapsed,
    rightExpanded: !rightCollapsed
  }
}
