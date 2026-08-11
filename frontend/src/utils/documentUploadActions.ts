import type { DocumentUploadStatus } from './documentPipelineStatus'

export const canSubmitDocumentUpload = (
  workflowEligible: boolean,
  uploadStatus: DocumentUploadStatus
): boolean => workflowEligible && uploadStatus === '上传成功'

export const canRetryDocumentUpload = (uploadStatus: DocumentUploadStatus): boolean =>
  uploadStatus === '失败重新上传'

export const canSubmitNdtDocumentUpload = (
  approvalStatus: string,
  uploadStatus: DocumentUploadStatus
): boolean => canSubmitDocumentUpload(['草稿', '需补正'].includes(approvalStatus), uploadStatus)
