import type { DocumentUploadStatus } from './documentPipelineStatus'

export const canSubmitDocumentUpload = (
  workflowEligible: boolean,
  uploadStatus: DocumentUploadStatus
): boolean => workflowEligible && uploadStatus === '上传成功'

export const canRetryDocumentUpload = (uploadStatus: DocumentUploadStatus): boolean =>
  uploadStatus === '失败重新上传'
