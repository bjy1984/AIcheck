import request from '@/axios'

export type BlindReviewMaterial = {
  documentId: string
  documentVersionId: string
  fileName: string
  fileType?: string
  originalUrl: string
  downloadUrl: string
}
export type BlindReviewMaterials = {
  taskId: string
  scopeSource: 'run_snapshot' | 'unavailable'
  materials: BlindReviewMaterial[]
  unavailableCount: number
  unavailableReason: string
}
export const getBlindReviewMaterialsApi = (
  taskId: string
): Promise<IResponse<BlindReviewMaterials>> =>
  request.get({ url: `/api/fde/blind-review/tasks/${encodeURIComponent(taskId)}/materials` })
