import type { ReviewFinding } from '@/api/aicheck'
import type { ArchiveItem, Project, ReportVersion } from '@/types/aicheck'

// A populated humanStatus can still explicitly mean “pending”. Terminal finding
// status wins because the accept/reject API does not rewrite humanStatus.
export const findingReviewState = (finding: Pick<ReviewFinding, 'status' | 'humanStatus'>) => {
  if (finding.status === 'accepted') return '已采纳'
  if (finding.status === 'rejected') return '未采纳'
  if (['confirmed', 'completed', 'accepted'].includes(finding.humanStatus || '')) return '已确认'
  if (finding.humanStatus === 'rejected') return '未采纳'
  return '待人工确认'
}

export const pendingFinding = (finding: Pick<ReviewFinding, 'status' | 'humanStatus'>) =>
  findingReviewState(finding) === '待人工确认'

export const latestReportVersion = (reports: ReportVersion[]) =>
  [...reports].sort((a, b) =>
    (b.updatedAt || b.generatedAt).localeCompare(a.updatedAt || a.generatedAt)
  )[0]

export const latestArchiveItem = (archives: ArchiveItem[]) =>
  [...archives].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))[0]

export const ownerActivityItems = (
  project: Project | undefined,
  reports: ReportVersion[],
  archives: ArchiveItem[]
) => {
  const items: Array<{
    timestamp: string
    title: string
    description: string
    type: 'primary' | 'success'
  }> = []
  if (project?.updatedAt)
    items.push({
      timestamp: project.updatedAt,
      title: '项目信息更新',
      description: project.name,
      type: 'primary'
    })
  reports.forEach((report) => {
    const timestamp = report.updatedAt || report.generatedAt
    if (timestamp)
      items.push({
        timestamp,
        title: `报告${report.status}`,
        description: `${report.title} · ${report.versionNo}`,
        type: 'primary'
      })
  })
  archives.forEach((archive) => {
    if (archive.updatedAt)
      items.push({
        timestamp: archive.updatedAt,
        title: '归档资料更新',
        description: archive.name,
        type: 'success'
      })
  })
  return items.sort((a, b) => b.timestamp.localeCompare(a.timestamp)).slice(0, 6)
}
