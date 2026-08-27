type ProjectTreeGroupLike = {
  nodes?: Array<{ nodeId?: number }>
}

export const resolveLoadableProjectNodeId = (
  preferredNodeId: number | undefined,
  groups: ProjectTreeGroupLike[]
): number | undefined => {
  const ids = groups.flatMap((group) =>
    (group.nodes || []).map((node) => Number(node.nodeId || 0)).filter((nodeId) => nodeId > 0)
  )
  return preferredNodeId && ids.includes(preferredNodeId) ? preferredNodeId : ids[0]
}

export const canLoadProjectNode = (nodeId: number, groups: ProjectTreeGroupLike[]) =>
  resolveLoadableProjectNodeId(nodeId, groups) === nodeId
