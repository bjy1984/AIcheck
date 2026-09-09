import type { ProjectTreePayload } from '@/api/aicheck'
import type { HandoffNodeStatuses } from '@/api/aicheck/reviewHandoffs'

export const withHandoffStatuses = (
  groups: ProjectTreePayload['groups'],
  report?: HandoffNodeStatuses
): ProjectTreePayload['groups'] =>
  groups.map((group) => ({
    ...group,
    nodes: group.nodes.map((node) => {
      const matches =
        report?.projectId === node.projectId && Array.isArray(report?.items)
          ? report.items.filter((row) => row && row.nodeId === node.nodeId)
          : []
      const row = matches.length === 1 ? matches[0] : undefined
      const valid =
        row &&
        ((row.status === 'requires_revalidation' && row.requiresRevalidation === true) ||
          (['current', 'not_used'].includes(row.status) && row.requiresRevalidation === false))
      return { ...node, handoffRevalidation: valid ? row.status : 'unavailable' }
    })
  }))
