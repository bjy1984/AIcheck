type AicheckBusinessErrorPayload = {
  code?: number | string
  message?: string
  data?: {
    reason?: string
    [key: string]: unknown
  }
  operationId?: string
  serverTime?: string
}

type AicheckBusinessErrorRecord = AicheckBusinessErrorPayload & {
  method?: string
  url?: string
  recordedAt: number
}

let latestBusinessError: AicheckBusinessErrorRecord | undefined

const reasonHints: Record<string, string> = {
  FORBIDDEN: '请确认当前角色、项目、节点和动作授权，必要时联系管理员补充权限。',
  ARCHIVED_READONLY: '当前对象已归档或处于只读状态，只能查看、预览或下载。',
  TASK_RUNNING: '已有任务正在运行，请稍后查看任务进度，避免重复触发。',
  IDEMPOTENCY_KEY_CONFLICT: '检测到重复请求或幂等键冲突，请刷新状态后再重试。',
  ETAG_CONFLICT: '数据版本已变化，请先刷新最新数据，再重新提交。',
  FILE_TOO_LARGE: '请压缩文件、拆分文件或改用符合限制的资料重新上传。',
  NDT_FILE_TOO_LARGE: '请压缩检测资料、拆分文件或改用符合限制的资料重新上传。',
  UNSUPPORTED_FILE_TYPE: '请改用系统支持的文件类型后重新上传。',
  UNSUPPORTED_NDT_FILE_TYPE: '请改用系统支持的检测资料类型后重新上传。',
  NDT_FILM_REQUIRED: '请填写底片编号、焊口编号和检测方法后再新增底片。',
  NDT_RECORD_REQUIRED: '请填写检测记录编号、焊口编号和检测方法后再导入记录。',
  NDT_REPORT_REQUIRED: '请先上传或选择至少一份待提交检测报告后再提交。',
  NDT_RECTIFICATION_REQUIRED: '请选择监检反馈事项并填写补正反馈说明后再提交。',
  EMPTY_BINDINGS: '请先选择至少一份项目资料，再执行挂载。',
  EMPTY_NODE_PACKAGE: '当前节点没有可提交资料，请补充资料或检查挂载状态。',
  WITHDRAW_LOCKED: '已通过或锁定资料不能撤回，请刷新节点状态后确认可操作项。',
  TASK_NOT_RETRYABLE: '当前任务状态不允许重试，请刷新任务列表确认最新状态。',
  TASK_NOT_CANCELABLE: '当前任务状态不允许取消，请刷新任务列表确认最新状态。',
  MODEL_COUNT_REQUIRED: '请至少选择两个模型后再运行对比。',
  QUESTION_REQUIRED: '请填写问题内容后再运行。',
  USER_REQUIRED: '请选择授权用户后再保存。',
  NODE_SCOPE_REQUIRED: '请填写有效节点范围后再保存。',
  CONFIG_REASON_REQUIRED: '请填写配置变更原因后再提交。',
  PUBLISH_REASON_REQUIRED: '请填写发布原因后再提交。',
  ROLLBACK_REASON_REQUIRED: '请填写回滚原因后再提交。',
  PROJECT_CODE_DUPLICATED: '请更换项目编号或刷新项目清单后重试。',
  PROJECT_NAME_REQUIRED: '请填写项目名称后再提交。'
}

const suffixHints: Array<[RegExp, string]> = [
  [/NOT_FOUND$/, '目标数据不存在、已被移除或当前账号无权访问，请刷新列表后重试。'],
  [/REQUIRED$/, '请补充必填信息后重试。'],
  [/READONLY$/, '当前对象为只读状态，不能继续写入。'],
  [/CONFLICT$/, '当前数据状态已变化，请刷新后重试。'],
  [/UNSUPPORTED$/, '当前操作或配置暂不支持，请调整后重试。']
]

const getReason = (payload?: AicheckBusinessErrorPayload) => {
  const reason = payload?.data?.reason
  return typeof reason === 'string' && reason.trim() ? reason.trim() : ''
}

const getCode = (payload?: AicheckBusinessErrorPayload) => {
  const code = payload?.code
  if (typeof code === 'number') return String(code)
  return typeof code === 'string' && code.trim() ? code.trim() : ''
}

const getHint = (reason: string) => {
  if (!reason) return ''
  if (reasonHints[reason]) return reasonHints[reason]
  return suffixHints.find(([pattern]) => pattern.test(reason))?.[1] || ''
}

const formatBusinessError = (payload: AicheckBusinessErrorPayload, fallback: string) => {
  const message =
    typeof payload.message === 'string' && payload.message.trim() ? payload.message : fallback
  const reason = getReason(payload)
  const hint = getHint(reason)
  const code = getCode(payload)
  const meta = reason || code ? `（错误码：${reason || code}）` : ''
  const recovery = hint && !message.includes(hint) ? ` ${hint}` : ''
  return `${message}${recovery}${meta}`
}

export const recordAicheckBusinessError = (
  payload: AicheckBusinessErrorPayload,
  context?: { method?: string; url?: string }
) => {
  latestBusinessError = {
    ...payload,
    method: context?.method,
    url: context?.url,
    recordedAt: Date.now()
  }
}

export const clearAicheckBusinessError = () => {
  latestBusinessError = undefined
}

export const getAicheckErrorMessage = (error: unknown, fallback: string) => {
  const candidate = error as {
    message?: unknown
    response?: { data?: AicheckBusinessErrorPayload }
  }
  const responseData = candidate?.response?.data
  if (responseData?.message || responseData?.code || responseData?.data?.reason) {
    return formatBusinessError(responseData, fallback)
  }

  if (latestBusinessError && Date.now() - latestBusinessError.recordedAt < 5000) {
    const message = error instanceof Error ? error.message : typeof error === 'string' ? error : ''
    if (!message || /未返回有效数据|接口返回异常|返回失败/.test(message)) {
      return formatBusinessError(latestBusinessError, fallback)
    }
  }

  if (error instanceof Error && error.message.trim()) return error.message
  if (typeof error === 'string' && error.trim()) return error

  if (latestBusinessError && Date.now() - latestBusinessError.recordedAt < 5000) {
    return formatBusinessError(latestBusinessError, fallback)
  }

  return fallback
}
