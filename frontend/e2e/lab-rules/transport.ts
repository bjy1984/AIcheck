// Only authentication transport is substituted. Requests reach real API routes.
type Config = { url: string; data?: unknown; headers?: Record<string, string> }
const send = async (method: string, config: Config) => {
  const response = await fetch(config.url, { method, headers: { 'Content-Type': 'application/json', ...config.headers }, body: config.data ? JSON.stringify(config.data) : undefined })
  const payload = await response.json()
  if (!response.ok || payload.code !== 0) throw new Error(payload.message || '请求失败')
  return payload
}
export default { get: (c: Config) => send('GET', c), post: (c: Config) => send('POST', c), patch: (c: Config) => send('PATCH', c) }
