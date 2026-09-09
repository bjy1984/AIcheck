// Only authentication transport is substituted. Requests reach real API routes.
type Config = { responseType?: string; url: string; data?: unknown; headers?: Record<string, string>; params?: Record<string, string | number> }
const send = async (method: string, config: Config) => {
  const query = new URLSearchParams(Object.entries(config.params || {}).map(([key, value]) => [key, String(value)]))
  const response = await fetch(config.url + (query.size ? `?${query}` : ''), { method, headers: { 'Content-Type': 'application/json', ...config.headers }, body: config.data ? JSON.stringify(config.data) : undefined })
  if (config.responseType === 'blob') {
    if (!response.ok) throw new Error('请求失败')
    return { data: await response.blob() }
  }
  const payload = await response.json()
  if (!response.ok || payload.code !== 0) throw new Error(payload.message || '请求失败')
  return payload
}
export default { get: (c: Config) => send('GET', c), post: (c: Config) => send('POST', c), patch: (c: Config) => send('PATCH', c) }
