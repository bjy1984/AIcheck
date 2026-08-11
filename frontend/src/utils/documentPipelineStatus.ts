export type DocumentPipelineState = {
  currentOcrStatus?: string
  sliceStatus?: string
  vectorStatus?: string
}

export type DocumentUploadStatus = '上传中' | '上传成功' | '失败重新上传'

export const isDocumentUploadSuccessful = (file: DocumentPipelineState): boolean =>
  ['已识别', '人工修正', '抽取不完整'].includes(String(file.currentOcrStatus || '')) &&
  String(file.sliceStatus || '') === '已切片' &&
  String(file.vectorStatus || '') === '已向量化'

export const documentPipelineStatus = (file: DocumentPipelineState): DocumentUploadStatus => {
  const ocrStatus = String(file.currentOcrStatus || '')
  const sliceStatus = String(file.sliceStatus || '')
  const vectorStatus = String(file.vectorStatus || '')
  if ([ocrStatus, sliceStatus, vectorStatus].some((status) => status.includes('失败'))) {
    return '失败重新上传'
  }
  if (isDocumentUploadSuccessful(file)) return '上传成功'
  return '上传中'
}
