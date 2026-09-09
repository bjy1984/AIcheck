import request from '@/axios'

export type PipelineConflictReport = {
  reviewRunId: string
  projectId: string
  inputHash?: string
  createdAt: string
  conflicts: Array<{
    pipelineId: string
    field: string
    sources: Array<{
      value: unknown
      source: {
        documentVersionId: string
        fileName?: string
        pageNo?: number
        tableId?: string
        rowIndex?: number
      }
    }>
  }>
}
export const getPipelineConflicts = (projectId: string, runId: string) =>
  request.get<{ report: PipelineConflictReport }>({
    url: `/api/projects/${encodeURIComponent(projectId)}/review-runs/${encodeURIComponent(runId)}/pipeline-conflicts`
  })
