import type {
  InspectionAuditOverviewNode,
  InspectionNodeConclusionGroup,
  InspectionStation
} from '@/types/aicheck'
import { friendlyCheckCode, friendlyCheckReason } from './auditLabels'

/** 展开后各组的顺序：先要处理的，再通过，最后没审的（2026-11-03 效果图第三版）。 */
export const STATION_GROUP_ORDER: InspectionNodeConclusionGroup[] = [
  'failed',
  'needs_materials',
  'needs_human',
  'passed',
  'not_started'
]

export const STATION_GROUP_LABELS: Record<InspectionNodeConclusionGroup, string> = {
  failed: '未通过',
  needs_materials: '待补资料',
  needs_human: '需人工确认',
  passed: '通过',
  not_started: '未开始审核'
}

export type StationGroupCounts = Record<InspectionNodeConclusionGroup, number>

export type StationOverviewNode = InspectionAuditOverviewNode & {
  group: InspectionNodeConclusionGroup
}

export type StationOverview = {
  stationId: string
  stationName: string
  counts: StationGroupCounts
  nodes: StationOverviewNode[]
}

const emptyCounts = (): StationGroupCounts => ({
  failed: 0,
  needs_materials: 0,
  needs_human: 0,
  passed: 0,
  not_started: 0
})

const groupOf = (row: InspectionAuditOverviewNode): InspectionNodeConclusionGroup =>
  row.conclusion?.group && STATION_GROUP_ORDER.includes(row.conclusion.group)
    ? row.conclusion.group
    : 'not_started'

/**
 * 按工位归组。工位清单来自后端（固定 A～I）；不在任何工位里的节点归到「其他」，
 * 不丢——总数必须和项目节点数对得上，否则监检会以为有节点漏审。
 */
export const buildStationOverview = (
  rows: InspectionAuditOverviewNode[],
  stations: InspectionStation[] = []
): { totals: StationGroupCounts; confirmedPassed: number; stations: StationOverview[] } => {
  const totals = emptyCounts()
  let confirmedPassed = 0
  const byNode = new Map(rows.map((row) => [row.node.nodeId, row]))
  const placed = new Set<number>()
  const build = (stationId: string, stationName: string, nodeIds: number[]): StationOverview => {
    const counts = emptyCounts()
    const nodes: StationOverviewNode[] = []
    for (const nodeId of nodeIds) {
      const row = byNode.get(nodeId)
      if (!row || placed.has(nodeId)) continue
      placed.add(nodeId)
      const group = groupOf(row)
      counts[group] += 1
      nodes.push({ ...row, group })
    }
    return { stationId, stationName, counts, nodes }
  }
  const result = stations
    .map((station) => build(station.stationId, station.stationName, station.nodeIds))
    .filter((station) => station.nodes.length)
  const rest = rows.map((row) => row.node.nodeId).filter((nodeId) => !placed.has(nodeId))
  if (rest.length) result.push(build('其他', '其他节点', rest))
  for (const station of result) {
    for (const node of station.nodes) {
      totals[node.group] += 1
      if (node.group === 'passed' && node.conclusion?.confirmed) confirmedPassed += 1
    }
  }
  return { totals, confirmedPassed, stations: result }
}

/** 行内一句原因：人工意见原文优先，其次不过的检查项（翻成中文），再次原因码。 */
export const conclusionReason = (row: InspectionAuditOverviewNode): string => {
  const reason = row.conclusion?.reason
  if (!reason) return ''
  if (reason.humanOpinion) return `监检意见：${reason.humanOpinion}`
  const checks = (reason.checkCodes || []).map((code) => friendlyCheckCode(code)).filter(Boolean)
  if (checks.length) return `未过：${checks.join('；')}`
  return reason.reasonCode ? friendlyCheckReason(reason.reasonCode) : ''
}

/** 结论来源标签：人工已确认 / AI 判定·待确认 / 不适用 / 复核中 / 复核失败。 */
export const conclusionSourceTag = (
  row: InspectionAuditOverviewNode
): { text: string; tone: 'success' | 'info' | 'warning' | 'danger' } | null => {
  const conclusion = row.conclusion
  if (!conclusion) return null
  if (conclusion.group === 'not_started') {
    if (conclusion.runState === 'running') return { text: '复核中', tone: 'info' }
    if (conclusion.runState === 'failed') return { text: '复核失败', tone: 'danger' }
    return null
  }
  if (conclusion.notApplicable) return { text: '不适用', tone: 'info' }
  return conclusion.confirmed
    ? { text: '已确认', tone: 'success' }
    : { text: 'AI 判定·待确认', tone: 'info' }
}

/** 每组的动作：未通过写意见、待补资料去看缺什么、需人工去确认、未审开始审核；通过不放按钮。 */
export const STATION_GROUP_ACTIONS: Partial<Record<InspectionNodeConclusionGroup, string>> = {
  failed: '写监检意见',
  needs_materials: '查看缺项',
  needs_human: '去确认',
  not_started: '开始审核'
}
