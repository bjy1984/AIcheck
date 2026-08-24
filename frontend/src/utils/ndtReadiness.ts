import type { DocumentAsset, NdtFilm, NdtReport, NdtSubmissionReadiness } from '@/types/aicheck'

const pendingStatuses = new Set(['草稿', '待提交', '需补正'])

export const pendingNdtReports = (reports: NdtReport[]) =>
  reports.filter((report) => pendingStatuses.has(report.status))

export const pendingNdtFilms = (films: NdtFilm[]) =>
  films.filter((film) => pendingStatuses.has(film.status))

export const buildNdtSubmitBlockers = (input: {
  reports: NdtReport[]
  films: NdtFilm[]
  projectFiles: DocumentAsset[]
  readiness?: NdtSubmissionReadiness
}) => {
  const reports = pendingNdtReports(input.reports)
  const blockers: string[] = []
  if (!reports.length) blockers.push('请先上传或选择至少一份待提交检测报告。')
  return Array.from(new Set(blockers))
}
