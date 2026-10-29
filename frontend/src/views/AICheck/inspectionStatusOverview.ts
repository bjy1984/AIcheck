export type InspectionStatusFilter =
  | 'not_started'
  | 'in_progress'
  | 'needs_attention'
  | 'failed'
  | 'completed'

const aliases: Record<InspectionStatusFilter, ReadonlyArray<string>> = {
  not_started: ['not_started', '未开始'],
  in_progress: ['in_progress', 'processing', 'running', '处理中', '推理中', '执行中'],
  needs_attention: ['needs_attention', 'attention', '需关注', '待人工确认'],
  failed: ['failed', 'execution_failed', '执行失败'],
  completed: ['completed', 'done', '已完成']
}

export const auditItemsMatchStatus = (
  items: ReadonlyArray<{ status: string }> | undefined,
  status: InspectionStatusFilter
) => (items || []).some((item) => aliases[status].includes(item.status))

export const aggregateStatusKey = (items: ReadonlyArray<{ status: string }> | undefined) => {
  if (!items?.length) return 'unknown'
  if (auditItemsMatchStatus(items, 'failed')) return 'failed'
  if (auditItemsMatchStatus(items, 'needs_attention')) return 'needs_attention'
  if (auditItemsMatchStatus(items, 'in_progress')) return 'in_progress'
  if (items.every((item) => aliases.completed.includes(item.status))) return 'completed'
  return 'not_started'
}
