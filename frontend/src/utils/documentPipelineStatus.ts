export type DocumentPipelineState = {
  currentOcrStatus?: string
  sliceStatus?: string
  vectorStatus?: string
  /** 文件本体是否已落盘。未上传成功的资料不能提交。 */
  bodyUploaded?: boolean
}

/**
 * `识别失败` 与 `失败重新上传` 必须分开。
 *
 * 2026-08-15 实操：文件上传成功（对象存储里字节可读、哈希已落库、挂载也成功），
 * 只是 OCR 没识别出来，界面却写「失败重新上传」。这句话有两处不对：
 *
 * - 事实不对：上传成功了；
 * - 指路不对：重新上传同一份文件，OCR 照样识别不出来。
 *
 * 用户按提示重传，然后再次看到同样的字——这种提示比不给提示更耗人。
 */
export type DocumentUploadStatus = '上传中' | '上传成功' | '识别失败' | '失败重新上传'

export type DocumentBusinessStatus = DocumentUploadStatus

/**
 * 上传成功 = 本体落盘 + OCR 完成。**不看切片/向量化**。
 *
 * 2026-08-29 架构调整：项目资料是被审查的对象、不是检索语料，后端已不再对它们
 * 做切片和向量化（见 task_dispatcher.project_file_indexing_blocker）。
 * 判据里留着那两条的后果是它们**永远不满足**——所有资料永远显示「上传中」、
 * canSubmitDocument 永远 false，用户传上去了却提交不了。
 *
 * 与后端 submission_pipeline.pipeline_stage_of 同口径：报审只要求 OCR 完成。
 */
export const isDocumentUploadSuccessful = (file: DocumentPipelineState): boolean =>
  file.bodyUploaded !== false &&
  ['已识别', '人工修正', '抽取不完整'].includes(String(file.currentOcrStatus || ''))

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
  // 只有本体没落盘才叫「上传失败」——那种情况重传确实有用。
  if (file.bodyUploaded === false) return '失败重新上传'
  // 本体在、识别链路挂了：重传解决不了，得重新识别或人工修正。
  // 只看 OCR：切片/向量化对项目资料已不再执行，历史遗留的「切片失败」
  // 「向量化失败」不该再让用户看到一个他无法处理、也不影响提交的错误。
  if (ocrStatus.includes('失败')) {
    return '识别失败'
  }
  if (isDocumentUploadSuccessful(file)) return '上传成功'
  return '上传中'
}
