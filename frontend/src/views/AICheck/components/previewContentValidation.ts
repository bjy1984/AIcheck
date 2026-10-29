/** A successful HTTP response can still contain an API error or an HTML sign-in page. */
export async function previewContentError(
  value: unknown,
  expectedType: 'pdf' | 'image'
): Promise<string> {
  if (!(value instanceof Blob)) return '原文服务没有返回可识别的文件内容，请重新加载详情。'
  if (!value.size) return '原文服务返回了空文件，无法预览。请联系管理员检查原文或重新上传。'
  const prefix = (await value.slice(0, 2048).text()).trimStart()
  if (value.type.includes('json') || /^(?:\{|\[)/.test(prefix)) {
    try {
      const error = JSON.parse(await value.text()) as {
        code?: string | number
        message?: string
        msg?: string
        error?: { code?: string; message?: string }
      }
      const code = error.error?.code ?? error.code
      if (String(code) === '401' || code === 'UNAUTHORIZED')
        return '原文预览未通过登录校验，请重新登录后再试。'
      const message = error.error?.message || error.message || error.msg
      return `原文服务返回了错误${code ? `（${code}）` : ''}，未提供文件内容。${typeof message === 'string' ? message.slice(0, 240) : '请重新加载详情后重试。'}`
    } catch {
      return '原文服务返回了无法识别的错误内容，请重新加载详情后重试。'
    }
  }
  if (value.type.includes('html') || /^<(?:!doctype\s+html|html|head|body)\b/i.test(prefix))
    return '原文服务返回了网页，未提供文件。请检查登录状态，或联系管理员检查原文地址。'
  if (expectedType === 'pdf' && !prefix.slice(0, 1024).includes('%PDF-'))
    return '原文服务返回的内容不是可识别的 PDF 文件。请下载核对，或联系管理员检查原文。'
  return ''
}
