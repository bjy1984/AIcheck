export type DocumentPipelineState = {
  currentOcrStatus?: string
  sliceStatus?: string
  vectorStatus?: string
  /** 文件本体是否已落盘。未上传成功的资料不能提交。 */
  bodyUploaded?: boolean
}

export type DocumentBusinessStatus = '上传中' | '上传成功' | '上传失败'

/**
 * 提交方（施工方 / 无损检测机构）看到的处理状态。
 *
 * OCR、切片、向量化是系统内部为了做 AI 复核而走的步骤，提交资料的人既无从理解、
 * 也不需要据此决策——他们只需要知道「传上去了没有、能不能提交」。技术过程的细节
 * 仍可用 documentPipelineStatus 取得，供监检和 FDE 排查使用。
 */
export const documentBusinessStatus = (file: DocumentPipelineState): DocumentBusinessStatus => {
  const stages = [file.currentOcrStatus, file.sliceStatus, file.vectorStatus].map((item) =>
    String(item || '')
  )
  if (file.bodyUploaded === false) return '上传失败'
  if (stages.some((status) => status.includes('失败'))) return '上传失败'
  const ocrStatus = stages[0]
  const settled = ['已识别', '人工修正', '抽取不完整'].includes(ocrStatus)
  return settled ? '上传成功' : '上传中'
}

/** 该资料能否提交：上传成功才可以。 */
export const canSubmitDocument = (file: DocumentPipelineState): boolean =>
  documentBusinessStatus(file) === '上传成功'

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
