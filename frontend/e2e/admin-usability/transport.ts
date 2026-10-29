// Test-only transport: browser tests intercept every /api request; no backend is used.
type Config = {
  url: string
  data?: unknown
  headers?: Record<string, string>
  params?: Record<string, unknown>
}
const send = async (method: string, config: Config) => {
  const query = new URLSearchParams(
    Object.entries(config.params || {})
      .filter(([, value]) => value != null)
      .map(([key, value]) => [key, String(value)])
  )
  const response = await fetch(config.url + (query.size ? `?${query}` : ''), {
    method,
    headers: { 'Content-Type': 'application/json', ...config.headers },
    body: config.data ? JSON.stringify(config.data) : undefined
  })
  const payload = await response.json()
  if (!response.ok || payload.code !== 0)
    throw Object.assign(new Error(payload.message || '请求失败'), {
      response: { status: response.status, data: payload }
    })
  return payload
}
export default {
  get: (c: Config) => send('GET', c),
  post: (c: Config) => send('POST', c),
  put: (c: Config) => send('PUT', c),
  patch: (c: Config) => send('PATCH', c),
  delete: (c: Config) => send('DELETE', c)
}
