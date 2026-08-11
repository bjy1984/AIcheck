export type DocumentPipelineState = {
  currentOcrStatus?: string
  sliceStatus?: string
  vectorStatus?: string
  /** 文件本体是否已落盘。未上传成功的资料不能提交。 */
  bodyUploaded?: boolean
}

export type DocumentUploadStatus = '上传中' | '上传成功' | '失败重新上传'

export type DocumentBusinessStatus = DocumentUploadStatus

export const isDocumentUploadSuccessful = (file: DocumentPipelineState): boolean =>
  file.bodyUploaded !== false &&
  ['已识别', '人工修正', '抽取不完整'].includes(String(file.currentOcrStatus || '')) &&
  String(file.sliceStatus || '') === '已切片' &&
  String(file.vectorStatus || '') === '已向量化'

/**
 * 提交方（施工方 / 无损检测机构）看到的处理状态。
 *
 * OCR、切片、向量化是系统内部为了做 AI 复核而走的步骤，提交资料的人既无从理解、
 * 也不需要据此决策——他们只需要知道「传上去了没有、能不能提交」。技术过程的细节
 * 仍保留在原始状态字段中，供监检和 FDE 排查使用。
 */
export const documentBusinessStatus = (file: DocumentPipelineState): DocumentBusinessStatus => {
  if (file.bodyUploaded === false) return '失败重新上传'
  return documentPipelineStatus(file)
}

/** 该资料能否提交：上传成功才可以。 */
export const canSubmitDocument = (file: DocumentPipelineState): boolean =>
  documentBusinessStatus(file) === '上传成功'

export const documentPipelineStatus = (file: DocumentPipelineState): DocumentUploadStatus => {
  const ocrStatus = String(file.currentOcrStatus || '')
  const sliceStatus = String(file.sliceStatus || '')
  const vectorStatus = String(file.vectorStatus || '')
  if (file.bodyUploaded === false) return '失败重新上传'
  if ([ocrStatus, sliceStatus, vectorStatus].some((status) => status.includes('失败'))) {
    return '失败重新上传'
  }
  if (isDocumentUploadSuccessful(file)) return '上传成功'
  return '上传中'
}
