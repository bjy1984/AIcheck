import type { ProjectAnalysisStatus } from '@/api/aicheck/projectAnalysis'

export type ProjectAnalysisBannerState = {
  tone: 'running' | 'success' | 'failure'
  label: string
  /** 鼠标停上去的说明：失败发生在什么时候、为什么。 */
  title?: string
}

// 失败标签原来只有四个字，没有时间也没有原因：生产里顶栏一直挂着「AI分析失败」，
// 其实是 10 月 23 日的一次旧失败（那时的模型套餐已过期），之后没人再跑过，看起来却像刚坏的。
const failureCodeHints: Record<string, string> = {
  'ACCESSDENIED.UNPURCHASED': '模型服务未开通或套餐已过期'
}

const shortTime = (value?: string | null) => {
  const match = String(value || '').match(/^\d{4}-(\d{2}-\d{2})[ T](\d{2}:\d{2})/)
  return match ? `${match[1]} ${match[2]}` : ''
}

const failureBanner = (status: ProjectAnalysisStatus): ProjectAnalysisBannerState => {
  const when = shortTime(status.finishedAt)
  const code = String(status.errorCode || '').trim()
  const reason = failureCodeHints[code] || String(status.errorMessage || '').trim() || code
  const label = when ? `AI分析失败 · ${when}` : 'AI分析失败'
  if (!when && !reason) return { tone: 'failure', label }
  const detail = reason ? `：${reason}${code && reason !== code ? `（${code}）` : ''}` : ''
  return {
    tone: 'failure',
    label,
    title: `最近一次全工程一键分析${when ? `在 ${when} ` : ''}失败${detail}。点「一键分析」可查看详情或重新发起。`
  }
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
  if (status.phase === 'failed' || status.phase === 'partial_failure') return failureBanner(status)
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
  if (reason === 'NOT_FOUND') {
    return { terminal: true, message: '分析任务不存在或已失效，请重新发起。' }
  }
  /* 网络抖动、单次超时、5xx 都不是运行本身的终态：轮询要继续。
   * 原来任何未知错误都 terminal → 停止轮询，界面停在旧进度、提示「刷新失败」，
   * 而后台运行其实还在跑并最终完成（2026-09-03 实测）。 */
  return { terminal: false, message: '全工程分析状态刷新失败，正在重试…' }
}

/* 分批运行的进度后缀：「（第 2/4 批）」；单批不显示，与分批前文案一致 */
const batchSuffix = (status: ProjectAnalysisStatus) => {
  const total = Number(status.batchCount || 1)
  if (total <= 1) return ''
  return `（第 ${Number(status.currentBatchIndex || 0) + 1}/${total} 批）`
}

/* 排队文案：llm 队列只有一个槽位，前面排着 OCR 抽取/节点复核时要让用户知道在等什么 */
const queuedLabel = (status: ProjectAnalysisStatus) => {
  const ahead = status.queueAhead
  if (typeof ahead !== 'number') return '已进入大模型队列'
  if (ahead <= 0) return '已进入大模型队列，即将开始'
  return `已进入大模型队列，前面还有 ${ahead} 个任务`
}

export const projectAnalysisProgressView = (status: ProjectAnalysisStatus) => {
  const base =
    status.progressMode === 'indeterminate'
      ? { mode: 'indeterminate' as const }
      : {
          mode: 'determinate' as const,
          // 没带 percent 的记录（如 run 列表原始项）：已完成就是 100，不能显示成 0
          percent: status.percent ?? (status.phase === 'waiting_human_review' ? 100 : 0)
        }
  const labels: Record<string, string> = {
    preparing_snapshot: `正在收集节点 ${status.preparedNodeCount}/${status.includedNodeCount}`,
    building_prompt: `正在拼接 OCR ${status.loadedFileCount}/${status.uniqueFileCount} · 预计 ${status.estimatedInputTokens.toLocaleString()} tokens`,
    queued: `${queuedLabel(status)}${batchSuffix(status)}`,
    model_running: `大模型正在进行全工程分析${batchSuffix(status)}`,
    validating_output: `正在校验分析结果 ${status.validatedFindingCount}/${status.totalFindingCount}`,
    persisting_results: `正在回挂节点结果 ${status.persistedNodeCount}/${status.includedNodeCount}`,
    waiting_human_review: '全工程分析完成，等待人工确认',
    partial_failure: '部分节点结果回挂失败',
    failed: `分析失败${status.errorCode ? ` · ${status.errorCode}` : ''}`
  }
  return { ...base, label: labels[status.phase] || status.phase }
}
