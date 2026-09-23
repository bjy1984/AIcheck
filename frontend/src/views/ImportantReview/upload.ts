import { createDocumentUploadSessionApi, completeDocumentUploadSessionApi } from '@/api/aicheck'
import { useUserStore } from '@/store/modules/user'

export async function uploadImportantFiles(projectId: string, files: File[]) {
  const user = useUserStore()
  const response = await createDocumentUploadSessionApi(
    projectId,
    files.map((file) => ({
      fileName: file.name,
      fileSize: file.size,
      fileType: file.name.split('.').pop()?.toLowerCase() || 'pdf'
    })),
    { idempotencyKey: `important-upload-${crypto.randomUUID()}` }
  )
  const session = response.data
  if (session.uploadUrls.length !== files.length) throw new Error('上传会话返回的文件数量不一致。')
  for (const [index, target] of session.uploadUrls.entries()) {
    const url = new URL(target.url, window.location.origin)
    if (!['http:', 'https:'].includes(url.protocol)) throw new Error('上传地址不可用。')
    const ownApi = url.origin === window.location.origin && url.pathname.startsWith('/api/')
    const result = await fetch(url, {
      method: target.method || 'PUT',
      headers: {
        ...target.headers,
        ...(ownApi ? { [user.getTokenKey || 'Authorization']: user.getToken || '' } : {})
      },
      body: files[index]
    })
    if (!result.ok) throw new Error(`${files[index].name} 上传失败（${result.status}）。`)
    if (result.headers.get('content-type')?.includes('application/json')) {
      const payload = await result.json()
      if (Number(payload.code ?? 0) !== 0) throw new Error(payload.message || '上传失败')
    }
  }
  const completed = await completeDocumentUploadSessionApi(
    projectId,
    session.uploadSessionId,
    session.uploadUrls.map((target, index) => ({
      documentVersionId: target.documentVersionId,
      fileSize: files[index].size
    })),
    { idempotencyKey: `important-complete-${session.uploadSessionId}` }
  )
  return completed.data
}
