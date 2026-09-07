/**
 * P9 R4：一键分析工程级视图——节点优先级表 + 共性风险。
 * 每个节点的结论只由 12.3 决策表推导（buildWorkbenchAiConclusion），这里只做排序与汇总。
 */
import type {
  ProjectAnalysisSummary,
  ProjectAnalysisSummaryNode
} from '@/api/aicheck/projectAnalysis'

import {
  buildWorkbenchAiConclusion,
  nodeRunFindingViews,
  type WorkbenchAiConclusion,
  type WorkbenchAiVerdict
} from './workbenchReviewPresentation'

export type ProjectAnalysisSummaryRow = {
  nodeId: number
  nodeName: string
  verdict: WorkbenchAiVerdict
  tone: WorkbenchAiConclusion['tone']
  headline: string
  action: WorkbenchAiConclusion['action']
  maxSeverity: string
  maxSeverityLabel: string
  needAction: number
  confirm: number
  insufficient: number
  findingCount: number
  partialCoverage: boolean
}

const VERDICT_RANK: Record<WorkbenchAiVerdict, number> = {
  需处理: 0,
  待确认: 1,
  证据不足: 2,
  未见问题: 3
}
const SEVERITY_RANK: Record<string, number> = { critical: 4, high: 3, medium: 2, low: 1 }
const SEVERITY_LABELS: Record<string, string> = {
  critical: '严重',
  high: '重要',
  medium: '一般',
  low: '提示'
}

const maxSeverity = (severities: string[]) =>
  severities.reduce(
    (best, current) =>
      (SEVERITY_RANK[current] || 0) > (SEVERITY_RANK[best] || 0) ? current : best,
    ''
  )

export const projectAnalysisSummaryRow = (
  node: ProjectAnalysisSummaryNode
): ProjectAnalysisSummaryRow => {
  const findings = nodeRunFindingViews({ findings: node.findingDrafts })
  const conclusion = buildWorkbenchAiConclusion({ findings })
  const grounded = [...conclusion.groups.needAction, ...conclusion.groups.confirm]
  const severity = maxSeverity(grounded.map((item) => item.severity))
  return {
    nodeId: node.nodeId,
    nodeName: node.nodeName,
    verdict: conclusion.verdict,
    tone: conclusion.tone,
    headline: conclusion.headline,
    action: conclusion.action,
    maxSeverity: severity,
    maxSeverityLabel: SEVERITY_LABELS[severity] || '',
    needAction: conclusion.counts.needAction,
    confirm: conclusion.counts.confirm,
    insufficient: conclusion.counts.insufficient,
    findingCount: findings.length,
    partialCoverage: (node.failedEvidenceShardIds || []).length > 0
  }
}

/** 需处理 → 待确认 → 证据不足 → 未见问题；同档按需处理条数、最高严重度、节点号。 */
export const projectAnalysisPriorityRows = (
  summary: Pick<ProjectAnalysisSummary, 'nodes'> | null | undefined
): ProjectAnalysisSummaryRow[] =>
  (summary?.nodes || [])
    .map(projectAnalysisSummaryRow)
    .sort(
      (left, right) =>
        VERDICT_RANK[left.verdict] - VERDICT_RANK[right.verdict] ||
        right.needAction - left.needAction ||
        (SEVERITY_RANK[right.maxSeverity] || 0) - (SEVERITY_RANK[left.maxSeverity] || 0) ||
        right.insufficient - left.insufficient ||
        left.nodeId - right.nodeId
    )

export const projectAnalysisSummaryTotals = (rows: ProjectAnalysisSummaryRow[]) => ({
  nodes: rows.length,
  needAction: rows.filter((row) => row.verdict === '需处理').length,
  confirm: rows.filter((row) => row.verdict === '待确认').length,
  insufficient: rows.filter((row) => row.verdict === '证据不足').length,
  clean: rows.filter((row) => row.verdict === '未见问题').length
})
