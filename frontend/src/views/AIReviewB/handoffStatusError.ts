const object = (value: unknown): Record<string, unknown> =>
  value !== null && typeof value === 'object' ? (value as Record<string, unknown>) : {}

export const handoffStatusError = (error: unknown): string => {
  const value = object(error)
  const response = object(value.response)
  const data = object(response.data)
  const httpStatus = Number(response.status)
  const code = httpStatus >= 400 ? httpStatus : Number(data.code || value.code)
  if (code === 401) return '登录已失效，请重新登录后核对交接状态。当前不能确认哪些节点需要重验。'
  if (code === 403) return '当前账号无法读取交接状态，请确认工程权限；不能据此认定没有需重验节点。'
  if (code === 404 || code === 501)
    return '交接状态接口当前不可用，请联系维护人员核对服务版本和工程访问范围。节点暂按交接状态未知处理。'
  return '暂时无法核对交接状态，请重新核对；这不代表没有需重验节点。'
}
