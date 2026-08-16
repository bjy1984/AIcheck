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

/** 为什么这个「提交审批」点不了。返回空串表示可以点。
 *
 * 线上实测（2026-08-16，NDT 工作台）：三行文件状态各不相同——
 * 「上传中·草稿」「识别失败·草稿」「上传成功·待审查」——
 * 按钮却一律灰着，**一个字的理由都没有**。
 *
 * 三种情况该做的事完全不同：等一等 / 重新上传 / 已经提交过了。
 * 而用户看到的是同一个灰按钮，只能挨个猜，或者以为系统坏了。
 * **禁用一个按钮而不说原因，等于让用户和界面互相沉默。**
 */
export const ndtSubmitBlockedReason = (
  approvalStatus: string,
  uploadStatus: DocumentUploadStatus
): string => {
  if (canSubmitNdtDocumentUpload(approvalStatus, uploadStatus)) return ''
  if (uploadStatus === '上传中') return '文件还在上传，完成后即可提交。'
  if (uploadStatus === '识别失败') return 'OCR 识别失败，请重新上传该文件后再提交。'
  if (uploadStatus === '失败重新上传') return '上传失败，请点「重新上传」后再提交。'
  if (uploadStatus !== '上传成功') return `当前上传状态为「${uploadStatus}」，暂不能提交。`
  if (approvalStatus === '待审查') return '这份文件已提交审批，正在等待监检处理。'
  if (approvalStatus === '已通过') return '这份文件已通过审查，无需再次提交。'
  return `当前审批状态为「${approvalStatus}」，只有草稿或需补正的文件可以提交。`
}

/** 为什么「调整业务规则」点不了。空串表示可以点。 */
export const ndtEditBlockedReason = (approvalStatus: string): string => {
  if (['草稿', '需补正'].includes(approvalStatus)) return ''
  if (approvalStatus === '待审查') return '已提交审批的文件不能再改绑定，需先撤回或等监检退回。'
  if (approvalStatus === '已通过') return '已通过审查的文件不能再改绑定。'
  return `当前审批状态为「${approvalStatus}」，只有草稿或需补正的文件可以调整。`
}
