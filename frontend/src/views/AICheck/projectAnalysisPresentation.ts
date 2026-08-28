import type { ProjectAnalysisStatus } from '@/api/aicheck/projectAnalysis'

export type ProjectAnalysisBannerState = {
  tone: 'running' | 'success' | 'failure'
  label: string
}

export const projectAnalysisBannerState = (
  status?: ProjectAnalysisStatus,
  starting = false
): ProjectAnalysisBannerState | undefined => {
  if (starting) return { tone: 'running', label: 'AI一键分析正在运行' }
  if (!status) return undefined
  if (status.phase === 'waiting_human_review') {
    return { tone: 'success', label: 'AI分析完成' }
  }
  if (status.phase === 'failed' || status.phase === 'partial_failure') {
    return { tone: 'failure', label: 'AI分析失败' }
  }
  return { tone: 'running', label: 'AI一键分析正在运行' }
}

export const projectAnalysisRequestFailure = (error: unknown) => {
  const payload = (
    error as {
      response?: {
        data?: { message?: string; data?: { reason?: string; currentSnapshotHash?: string } }
      }
    }
  )?.response?.data
  const reason = String(payload?.data?.reason || '')
  const serverMessage = String(payload?.message || '')
  /* 后端把机器可读错误码放在 message 字段里（PROJECT_ANALYSIS_*）。
   * 不映射的话用户会看到裸错误码，或更糟——被兜底文案骗去「稍后重试」，
   * 而空范围这种错误重试一万次也不会变。 */
  const codeMessages: Record<string, string> = {
    PROJECT_ANALYSIS_EMPTY_SCOPE:
      '当前项目还没有可分析的节点资料：请先在节点上挂接有效资料（且未被驳回），再发起一键分析。',
    PROJECT_ANALYSIS_CONTEXT_LIMIT_EXCEEDED:
      '项目资料总量超出模型可处理上限，请减少纳入分析的资料后重试。'
  }
  if (codeMessages[serverMessage]) {
    let message = codeMessages[serverMessage]
    /* 超限时后端附 topCorpusFiles（前三大文件及估算 token）：
     * 「减少资料」不可执行，「拆掉这份 4 万 token 的报告」才可执行。 */
    const topFiles = (
      payload?.data as { topCorpusFiles?: { fileName?: string; estimatedTokens?: number }[] }
    )?.topCorpusFiles
    if (serverMessage === 'PROJECT_ANALYSIS_CONTEXT_LIMIT_EXCEEDED' && topFiles?.length) {
      const detail = topFiles
        .map(
          (f) =>
            `${f.fileName || '未知文件'}（约 ${((f.estimatedTokens || 0) / 1000).toFixed(1)}k tokens）`
        )
        .join('、')
      message += `占用最大的资料：${detail}。`
    }
    return { terminal: true, message }
  }
  if (payload?.data?.currentSnapshotHash) {
    return {
      terminal: true,
      message: '项目资料在预览后发生了变化，请刷新预览确认范围后重新发起。'
    }
  }
  return {
    terminal: true,
    message:
      reason === 'NOT_FOUND'
        ? '分析任务不存在或已失效，请重新发起。'
        : '全工程分析状态刷新失败，请稍后重试。'
  }
}

/* 分批运行的进度后缀：「（第 2/4 批）」；单批不显示，与分批前文案一致 */
const batchSuffix = (status: ProjectAnalysisStatus) => {
  const total = Number(status.batchCount || 1)
  if (total <= 1) return ''
  return `（第 ${Number(status.currentBatchIndex || 0) + 1}/${total} 批）`
}

export const projectAnalysisProgressView = (status: ProjectAnalysisStatus) => {
  const base =
    status.progressMode === 'indeterminate'
      ? { mode: 'indeterminate' as const }
      : { mode: 'determinate' as const, percent: status.percent || 0 }
  const labels: Record<string, string> = {
    preparing_snapshot: `正在收集节点 ${status.preparedNodeCount}/${status.includedNodeCount}`,
    building_prompt: `正在拼接 OCR ${status.loadedFileCount}/${status.uniqueFileCount} · 预计 ${status.estimatedInputTokens.toLocaleString()} tokens`,
    queued: `已进入大模型队列${batchSuffix(status)}`,
    model_running: `大模型正在进行全工程分析${batchSuffix(status)}`,
    validating_output: `正在校验分析结果 ${status.validatedFindingCount}/${status.totalFindingCount}`,
    persisting_results: `正在回挂节点结果 ${status.persistedNodeCount}/${status.includedNodeCount}`,
    waiting_human_review: '全工程分析完成，等待人工确认',
    partial_failure: '部分节点结果回挂失败',
    failed: `分析失败${status.errorCode ? ` · ${status.errorCode}` : ''}`
  }
  return { ...base, label: labels[status.phase] || status.phase }
}
