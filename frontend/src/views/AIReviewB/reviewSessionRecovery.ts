export type ReviewSessionMutationOptions = {
  etag?: string
  idempotencyKey?: string
  silentBusinessError?: boolean
  silentHttpError?: boolean
}

export const reviewSessionMutationHeaders = (
  prefix: string,
  options?: ReviewSessionMutationOptions
) => {
  const headers: Record<string, string> = {
    'Idempotency-Key': options?.idempotencyKey || prefix
  }
  if (options?.etag) headers['If-Match'] = options.etag
  if (options?.silentBusinessError) headers['X-Silent-Business-Error'] = 'true'
  if (options?.silentHttpError) headers['X-Silent-Http-Error'] = 'true'
  return headers
}

export const createSessionWithAuthorizationRecovery = async <T>(
  create: (idempotencyKey: string, silent: boolean) => Promise<T>,
  stableKey: string,
  nonce: () => string
): Promise<T> => {
  try {
    return await create(stableKey, true)
  } catch (error) {
    const candidate = error as {
      response?: { data?: { data?: { reason?: unknown }; reason?: unknown } }
      data?: { reason?: unknown }
      reason?: unknown
    }
    const reason = String(
      candidate.response?.data?.data?.reason ||
        candidate.response?.data?.reason ||
        candidate.data?.reason ||
        candidate.reason ||
        ''
    )
    if (reason !== 'FORBIDDEN') throw error
    return create(`${stableKey}-reauth-${nonce()}`, false)
  }
}
