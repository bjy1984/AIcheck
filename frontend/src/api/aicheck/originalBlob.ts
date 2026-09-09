import { getAicheckErrorMessage, recordAicheckBusinessError } from '@/utils/aicheckError'

/** Original-file routes can return the normal business error envelope with HTTP 200. */
export async function validateOriginalBlob<T extends { data: Blob }>(
  response: T,
  url: string
): Promise<T> {
  const blob = response.data
  if (!/(?:application\/json|\+json)(?:;|$)/i.test(blob.type) || blob.size > 1024 * 1024)
    return response
  let payload: unknown
  try {
    payload = JSON.parse(await blob.text())
  } catch {
    return response
  }
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return response
  const envelope = payload as Record<string, unknown>
  if (
    !(typeof envelope.code === 'number' || typeof envelope.code === 'string') ||
    !String(envelope.code).trim() ||
    Number(envelope.code) === 0 ||
    typeof envelope.message !== 'string' ||
    typeof envelope.operationId !== 'string' ||
    typeof envelope.serverTime !== 'string'
  )
    return response
  const errorResponse = { ...response, data: envelope }
  recordAicheckBusinessError(envelope, { method: 'GET', url })
  throw Object.assign(
    new Error(getAicheckErrorMessage({ response: errorResponse }, '所选原文暂时无法读取。')),
    {
      name: 'AicheckBusinessError',
      response: errorResponse
    }
  )
}
