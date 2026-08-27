import type { ProjectAnalysisStatus } from '@/api/aicheck/projectAnalysis'

export const projectAnalysisRequestFailure = (error: unknown) => {
  const reason = String(
    (error as { response?: { data?: { data?: { reason?: string } } } })?.response?.data?.data
      ?.reason || ''
  )
  return {
    terminal: true,
    message:
      reason === 'NOT_FOUND'
        ? '分析任务不存在或已失效，请重新发起。'
        : '全工程分析状态刷新失败，请稍后重试。'
  }
}

export const projectAnalysisProgressView = (status: ProjectAnalysisStatus) => {
  const base =
    status.progressMode === 'indeterminate'
      ? { mode: 'indeterminate' as const }
      : { mode: 'determinate' as const, percent: status.percent || 0 }
  const labels: Record<string, string> = {
    preparing_snapshot: `正在收集节点 ${status.preparedNodeCount}/${status.includedNodeCount}`,
    building_prompt: `正在拼接 OCR ${status.loadedFileCount}/${status.uniqueFileCount} · 预计 ${status.estimatedInputTokens.toLocaleString()} tokens`,
    queued: '已进入大模型队列',
    model_running: '大模型正在进行全工程分析',
    validating_output: `正在校验分析结果 ${status.validatedFindingCount}/${status.totalFindingCount}`,
    persisting_results: `正在回挂节点结果 ${status.persistedNodeCount}/${status.includedNodeCount}`,
    waiting_human_review: '全工程分析完成，等待人工确认',
    partial_failure: '部分节点结果回挂失败',
    failed: `分析失败${status.errorCode ? ` · ${status.errorCode}` : ''}`
  }
  return { ...base, label: labels[status.phase] || status.phase }
}
