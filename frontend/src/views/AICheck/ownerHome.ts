/**
 * 建设方首页要回答的四件事：进度到哪了、哪里卡住了、有什么新消息、报告在哪下（2026-11-04）。
 *
 * 原来的页面是三张都写着「当前授权可见范围」的指标卡、一张四列节点表、一条时间线、
 * 报告表和归档表，再加上选中节点的资料要求表、已挂载资料表、项目资料池表——手机上
 * 每张表都要横滑。这里只算数，界面在 components/OwnerProjectHome.vue。
 */
import type { ArchiveItem, MessageItem, ProjectTreeNode, ReportVersion } from '@/types/aicheck'

export type OwnerBucket = 'passed' | 'reviewing' | 'correction' | 'pending'

const BUCKET_BY_STATUS: Record<string, OwnerBucket> = {
  已通过: 'passed',
  已归档: 'passed',
  不适用: 'passed',
  需补正: 'correction',
  补正中: 'correction',
  已提交: 'reviewing',
  'AI 预审中': 'reviewing',
  待审查: 'reviewing',
  待人工确认: 'reviewing',
  复审中: 'reviewing',
  业务核验中: 'reviewing',
  '报告生成/复核中': 'reviewing'
}

/** 待提交、部分提交和认不出的状态都算「待提交」：还没到监检手上。 */
export const ownerBucket = (status: string): OwnerBucket => BUCKET_BY_STATUS[status] || 'pending'

export const OWNER_BUCKET_LABELS: Record<OwnerBucket, string> = {
  passed: '已通过',
  reviewing: '审查中',
  correction: '需补正',
  pending: '待提交'
}

export const ownerStatusCounts = (nodes: Pick<ProjectTreeNode, 'status'>[]) => {
  const counts: Record<OwnerBucket, number> = { passed: 0, reviewing: 0, correction: 0, pending: 0 }
  nodes.forEach((node) => {
    counts[ownerBucket(String(node.status || ''))] += 1
  })
  return { ...counts, total: nodes.length }
}

/** 进度只认后端算的 progress；接口只给了技术指标时显示「—」，不凭空编一个进度。 */
export const ownerProgress = (
  metrics: Array<{ key: string; value: string | number; label?: string }>
) => {
  const metric = metrics.find((item) => item.key === 'progress')
  if (!metric) return { label: '—', percent: 0 }
  const label = String(metric.value)
  const percent = Number.parseFloat(label)
  return {
    label: label.includes('%') || Number.isNaN(percent) ? label : `${label}%`,
    percent: Number.isFinite(percent) ? Math.min(100, Math.max(0, percent)) : 0
  }
}

/** 报告与归档没加载成功时不能显示成 0：0 份和「不知道几份」对建设方是两回事。 */
export const ownerReportsState = (input: {
  loading: boolean
  loaded: boolean
  issue?: string
}): 'loading' | 'failed' | 'idle' | 'ready' =>
  input.loading ? 'loading' : input.issue ? 'failed' : !input.loaded ? 'idle' : 'ready'

const shortDate = (value?: string) => {
  const match = /^\d{4}-(\d{2})-(\d{2})/.exec(String(value || '').trim())
  return match ? `${match[1]}-${match[2]}` : String(value || '')
}

/** 被退回的节点排最前；退回原因取监检退回时写的那句（来自「退回补正」消息）。 */
export const ownerAttentionNodes = (nodes: ProjectTreeNode[], messages: MessageItem[]) =>
  nodes
    .filter((node) => ownerBucket(String(node.status || '')) === 'correction')
    .map((node) => {
      const note = messages.find(
        (message) => message.kind === 'node_correction' && Number(message.nodeId) === node.nodeId
      )
      return {
        node,
        reason: note?.content ? `监检退回：${note.content}` : '监检已退回，等施工方补正',
        at: shortDate(note?.createdAt)
      }
    })

export type OwnerFeedItem = { title: string; at: string; tone: 'green' | 'blue' | 'red' | 'gray' }

const MESSAGE_TONES: Record<string, OwnerFeedItem['tone']> = {
  node_conclusion: 'green',
  report_archived: 'blue',
  node_correction: 'red'
}

/** 最新动态：优先用发给建设方的消息（结论、退回、归档），没有消息时退回到报告与归档的更新记录。 */
export const ownerFeed = (
  messages: MessageItem[],
  reports: ReportVersion[],
  archives: ArchiveItem[],
  limit = 3
): OwnerFeedItem[] => {
  const fromMessages = messages.map((message) => ({
    title: message.title,
    at: shortDate(message.createdAt),
    sortKey: String(message.createdAt || ''),
    tone: (message.title.includes('需补正') ? 'red' : MESSAGE_TONES[String(message.kind)]) || 'gray'
  }))
  const fromRecords = [
    ...reports.map((report) => ({
      title: `报告${report.status}：${report.title}`,
      at: shortDate(report.updatedAt || report.generatedAt),
      sortKey: String(report.updatedAt || report.generatedAt || ''),
      tone: 'blue' as const
    })),
    ...archives.map((archive) => ({
      title: `归档资料更新：${archive.name}`,
      at: shortDate(archive.updatedAt),
      sortKey: String(archive.updatedAt || ''),
      tone: 'gray' as const
    }))
  ]
  const items = fromMessages.length ? fromMessages : fromRecords
  return [...items]
    .sort((left, right) => right.sortKey.localeCompare(left.sortKey))
    .slice(0, limit)
    .map(({ title, at, tone }) => ({ title, at, tone }))
}
