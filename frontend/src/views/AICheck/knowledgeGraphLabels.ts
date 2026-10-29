export type GraphLabelLevel = 'overview' | 'sections' | 'detail'

/** Filtering may clear a hidden selection, but must never select a different result. */
export function visibleGraphSelection(selectedId: string, visibleIds: ReadonlySet<string>): string {
  return selectedId && visibleIds.has(selectedId) ? selectedId : ''
}

/** Zoom is relative to the fitted graph; labels stay fixed-size while nodes spread apart. */
export function graphLabelLevel(zoom: number): GraphLabelLevel {
  if (zoom >= 5) return 'detail'
  return zoom >= 2 ? 'sections' : 'overview'
}

export function showGraphNodeLabel(
  type: string,
  level: GraphLabelLevel,
  nodeCount: number,
  searchMatch = false
): boolean {
  if (searchMatch || nodeCount <= 24 || level === 'detail') return true
  if (type === 'business_pack' || type === 'domain_module') return true
  return level === 'sections' && ['inspection_node', 'project', 'agent'].includes(type)
}

/** Neighbors are derived from the original matches, never from neighbors already added. */
export function graphSearchContext(
  matches: ReadonlySet<string>,
  allowed: ReadonlySet<string>,
  edges: readonly { source: string; target: string }[]
): Set<string> {
  const visible = new Set(matches)
  for (const edge of edges) {
    if (matches.has(edge.source) && allowed.has(edge.target)) visible.add(edge.target)
    if (matches.has(edge.target) && allowed.has(edge.source)) visible.add(edge.source)
  }
  return visible
}
