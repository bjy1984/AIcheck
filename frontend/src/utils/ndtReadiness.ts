import type { DocumentAsset, NdtFilm, NdtReport, NdtSubmissionReadiness } from '@/types/aicheck'

const pendingStatuses = new Set(['草稿', '待提交', '需补正'])

export const pendingNdtReports = (reports: NdtReport[]) =>
  reports.filter((report) => pendingStatuses.has(report.status))

export const pendingNdtFilms = (films: NdtFilm[]) =>
  films.filter((film) => pendingStatuses.has(film.status))

const blockerText = (item: { code?: string; message?: string; reportId?: string }) =>
  [item.reportId, item.message || item.code].filter(Boolean).join('：')

export const buildNdtSubmitBlockers = (input: {
  reports: NdtReport[]
  films: NdtFilm[]
  projectFiles: DocumentAsset[]
  readiness?: NdtSubmissionReadiness
}) => {
  const readinessBlockers = (input.readiness?.blockingReasons || [])
    .map(blockerText)
    .filter(Boolean)
  if (readinessBlockers.length) return Array.from(new Set(readinessBlockers))

  const reports = pendingNdtReports(input.reports)
  const films = pendingNdtFilms(input.films)
  const blockers: string[] = []
  if (!reports.length) blockers.push('请先上传或选择至少一份待提交检测报告。')
  const reportFileIds = new Set(reports.map((report) => report.fileId))
  for (const file of input.projectFiles.filter((item) => reportFileIds.has(item.id))) {
    if (!['已识别', '人工修正'].includes(String(file.currentOcrStatus))) {
      blockers.push(`${file.fileName} OCR 未完成，当前状态：${file.currentOcrStatus || '未知'}`)
    }
  }
  for (const report of reports) {
    if (report.method === 'RT' && !report.detectionRatio) {
      blockers.push(`${report.reportNo} 缺少 RT 检测比例。`)
    }
    if (report.method === 'RT' && !report.relatedFilmIds.length && !films.length) {
      blockers.push(`${report.reportNo} 缺少底片/影像关联。`)
    }
  }
  return Array.from(new Set(blockers))
}
