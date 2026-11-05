/**
 * 节点页顶部那一行：现在到哪一步、要我做什么（2026-11-04 节点页简化）。
 *
 * 原来同一个状态在步骤条、状态行、AI 审查标题、本次复核卡、四格计数里各说一遍，
 * 「当前节点形成 N 条审查发现，所有结果均需人工确认」一页出现三四次。现在只在标题旁
 * 给一个徽标、标题下给一行摘要，下面的区块不再重复。资料计数也从这里出，
 * 资料卡、摘要行、结论区的阻断提示用的是同一份数字。
 */
import type { ReviewOpinion } from '@/types/aicheck'

export type NodeMaterialRow = {
  id: string
  name: string
  requiredType: string
  responsibleParty: string
  matchedFileNames: string[]
  status: string
}

export type MaterialSeverity = 'blocking' | 'attention' | 'optional' | 'done'

const isOptional = (row: NodeMaterialRow) => row.requiredType === '可选'
const isDone = (row: NodeMaterialRow) => row.status === '已确认'
/** 待确认＝挂上了但没人确认；未找到＝压根没挂。 */
export const isPendingMaterial = (row: NodeMaterialRow) =>
  row.status === '待确认' || row.status === '已驳回'

/** 必传缺失挡结论，条件必传缺失要判断，可选没交只是没交——三档不能一样红。 */
export const materialSeverity = (row: NodeMaterialRow): MaterialSeverity => {
  if (isDone(row)) return 'done'
  if (isOptional(row)) return 'optional'
  return row.requiredType === '必传' ? 'blocking' : 'attention'
}

export type NodeMaterialStats = {
  requiredTotal: number
  requiredDone: number
  /** 必传且没挂任何资料。 */
  missing: number
  /** 挂了资料但还没人确认（含被驳回的）。 */
  pending: number
  /** 条件必传没挂。 */
  attention: number
  /** 可选没交。 */
  optional: number
}

export const materialStats = (rows: NodeMaterialRow[]): NodeMaterialStats => {
  const required = rows.filter((row) => !isOptional(row))
  return {
    requiredTotal: required.length,
    requiredDone: required.filter(isDone).length,
    missing: rows.filter((row) => materialSeverity(row) === 'blocking' && !isPendingMaterial(row))
      .length,
    pending: rows.filter((row) => !isDone(row) && isPendingMaterial(row)).length,
    attention: rows.filter(
      (row) => materialSeverity(row) === 'attention' && !isPendingMaterial(row)
    ).length,
    optional: rows.filter((row) => isOptional(row) && !isDone(row)).length
  }
}

type Tone = 'blue' | 'green' | 'orange' | 'red' | 'gray'

export type NodeReviewHeadline = {
  badge: { label: string; tone: Tone }
  parts: string[]
}

const OPINION_TONES: Record<ReviewOpinion['result'], Tone> = {
  满足要求: 'green',
  需补正: 'red',
  证据不足: 'orange',
  不适用: 'gray'
}

/** 「2026-10-31 11:31:59」→「10-31」；认不出就原样给，别丢信息。 */
const shortDate = (value: string) => {
  const match = /^\d{4}-(\d{2})-(\d{2})/.exec(value.trim())
  return match ? `${match[1]}-${match[2]}` : value.trim()
}

const SOURCE_SHORT: Record<string, string> = {
  全工程一键分析: '一键分析',
  节点AI复核: '节点复核',
  '节点 AI 复核': '节点复核'
}

export const buildNodeReviewHeadline = (input: {
  ai: {
    runId: string
    activityAt: string
    sourceLabel: string
    running: boolean
    errorMessage: string
  }
  /** 结论卡的计数；AI 没跑完或失败时没有。 */
  counts?: { needAction: number; confirm: number }
  materials: NodeMaterialStats
  latestOpinion?: Pick<ReviewOpinion, 'result' | 'createdAt'>
}): NodeReviewHeadline => {
  const { ai, counts, materials, latestOpinion } = input
  const parts: string[] = []

  if (ai.running) parts.push('AI 正在审查')
  else if (ai.errorMessage) parts.push('AI 审查失败')
  else if (!ai.runId.trim()) parts.push('AI 还没审')
  else {
    const when = shortDate(ai.activityAt)
    const source = SOURCE_SHORT[ai.sourceLabel] || ai.sourceLabel
    const detail = [when, source].filter(Boolean).join(' ')
    parts.push(detail ? `AI 已初审（${detail}）` : 'AI 已初审')
  }
  if (counts?.needAction) parts.push(`${counts.needAction} 条需处理`)
  if (counts?.confirm) parts.push(`${counts.confirm} 条待你确认`)
  if (materials.missing) parts.push(`缺 ${materials.missing} 份必传资料`)
  if (materials.pending) parts.push(`${materials.pending} 份资料待确认`)

  const badge: NodeReviewHeadline['badge'] = latestOpinion
    ? {
        label: `已下结论：${latestOpinion.result}`,
        tone: OPINION_TONES[latestOpinion.result] || 'gray'
      }
    : ai.running
      ? { label: 'AI 审查中', tone: 'blue' }
      : { label: '待你下结论', tone: 'orange' }
  return { badge, parts }
}
