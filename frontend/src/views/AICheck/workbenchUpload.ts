/** 工作台的上传与业务阻断原因整理：不碰组件状态的部分，2026-11-02 从 Workbench.vue 搬来。 */
import type { UploadSessionPayload } from '@/api/aicheck'
import { getAicheckErrorMessage } from '@/utils/aicheckError'
import { ElMessage } from 'element-plus'
import type { Ref } from 'vue'

export type DocumentUploadTarget = UploadSessionPayload['uploadUrls'][number]

export const stringifyBusinessReason = (value: unknown) => {
  if (!value) return ''
  if (typeof value === 'string') return value
  if (typeof value !== 'object') return String(value)
  const record = value as {
    message?: unknown
    code?: unknown
    reportId?: unknown
    requirementName?: unknown
  }
  return [record.reportId, record.requirementName, record.message || record.code]
    .filter(Boolean)
    .join('：')
}

export const extractBusinessBlockerReasons = (data?: Record<string, unknown>) => {
  if (!data) return []
  const containers = [
    data.evidenceReadiness,
    data.evidenceValidation,
    data.ndtReadiness,
    data.dispatch
  ] as Array<Record<string, unknown> | undefined>
  const reasons: string[] = []
  for (const container of containers) {
    if (!container) continue
    const blockingReasons = container.blockingReasons
    if (Array.isArray(blockingReasons)) {
      reasons.push(...blockingReasons.map(stringifyBusinessReason).filter(Boolean))
    }
    const message = stringifyBusinessReason(container.message || container.statusReason)
    if (message) reasons.push(message)
  }
  return Array.from(new Set(reasons))
}

/** 各个弹窗的报错写法都一样：翻成人话、写进本弹窗的错误位、再弹一条提示。 */
export const reportErrorTo = (target: Ref<string>) => (fallback: string, error?: unknown) => {
  const message = getAicheckErrorMessage(error, fallback)
  target.value = message
  ElMessage.error(message)
}

const uploadMimeByExtension: Record<string, string> = {
  pdf: 'application/pdf',
  doc: 'application/msword',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  xls: 'application/vnd.ms-excel',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  png: 'image/png',
  zip: 'application/zip'
}

export const inferUploadFileType = (file: File) => {
  if (file.type) return file.type
  const extension = file.name.split('.').pop()?.toLowerCase() || ''
  return uploadMimeByExtension[extension] || 'application/octet-stream'
}

const assertRealUploadTarget = (target: DocumentUploadTarget, file: File) => {
  const url = String(target?.url || '')
  if (!url) throw new Error(`${file.name} 未返回上传地址`)
  if (url.startsWith('mock://')) {
    throw new Error('真实上传地址不可用：后端返回 mock:// 地址，请配置对象存储后重试。')
  }
}

/** 这个上传地址是不是我们自己的 API。
 *
 * 只有自家 API 才需要 JWT。发往对象存储的预签名 URL 绝不能带 Authorization：
 * S3/MinIO 一看到这个头就改用它来鉴权、不再认预签名参数，而 JWT 不是合法的
 * AWS 签名，直接回 400。
 *
 * 2026-08-15 实测就是这么卡住的：服务器侧用同一个预签名 URL curl（不带该头）
 * 返回 200，浏览器带着头 PUT 返回 400 Bad Request。
 */
export const isOwnApiUploadTarget = (url: string) =>
  url.startsWith('/api/') || url.startsWith(`${window.location.origin}/api/`)

/** apiAuthHeader 只在目标是自家 API 时才带上（见 isOwnApiUploadTarget）。 */
export const uploadFileToSignedUrl = async (
  target: DocumentUploadTarget,
  file: File,
  apiAuthHeader: Record<string, string>
) => {
  assertRealUploadTarget(target, file)
  // 登录态由本地会话补，不再依赖服务端在会话响应里回显 Authorization（M-3）——
  // 把调用方自己的 JWT 写进响应体没有增益，却会随响应进入 devtools、前端日志、
  // 错误上报和网关访问日志。target.headers 仍带本次上传专用的短时凭证。
  const response = await fetch(target.url, {
    method: target.method || 'PUT',
    headers: {
      ...(target.headers || {}),
      ...(isOwnApiUploadTarget(target.url) ? apiAuthHeader : {})
    },
    body: file
  })
  if (!response.ok) {
    throw new Error(
      `${file.name} 上传失败：${response.status} ${response.statusText || '存储服务拒绝写入'}`
    )
  }
  const contentType = String(response.headers.get('content-type') || '').toLowerCase()
  if (contentType.includes('application/json')) {
    const payload = (await response.json()) as { code?: number; message?: string }
    if (Number(payload.code ?? 0) !== 0) {
      throw new Error(payload.message || `${file.name} 上传被业务规则拒绝`)
    }
  }
}
