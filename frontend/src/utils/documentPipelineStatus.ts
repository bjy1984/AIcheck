export type DocumentPipelineState = {
  currentOcrStatus?: string
  sliceStatus?: string
  vectorStatus?: string
}

export const documentPipelineStatus = (file: DocumentPipelineState): string => {
  const ocrStatus = String(file.currentOcrStatus || '')
  const sliceStatus = String(file.sliceStatus || '')
  const vectorStatus = String(file.vectorStatus || '')
  if ([ocrStatus, sliceStatus, vectorStatus].some((status) => status.includes('失败'))) {
    return '失败可重试'
  }
  if (
    ocrStatus === '排队中' ||
    ocrStatus === '等待OCR' ||
    ocrStatus === '待OCR' ||
    ocrStatus === '待识别' ||
    ocrStatus === '未识别'
  ) {
    return '排队中'
  }
  if (ocrStatus === '识别中') return 'OCR 中'
  const ocrComplete = ['已识别', '人工修正', '抽取不完整'].includes(ocrStatus)
  if (ocrStatus && !ocrComplete) return ocrStatus
  if (sliceStatus === '未切片' || sliceStatus === '待切片') return '待切片'
  if (sliceStatus === '切片中') return '切片中'
  if (sliceStatus && sliceStatus !== '已切片') return sliceStatus
  if (!sliceStatus && ocrComplete) return '待切片'
  if (vectorStatus === '未向量化' || vectorStatus === '待向量化' || !vectorStatus) {
    return '待向量化'
  }
  if (vectorStatus === '向量化中') return '向量化中'
  if (vectorStatus === '已向量化') return '已完成'
  return vectorStatus || ocrStatus || '排队中'
}
