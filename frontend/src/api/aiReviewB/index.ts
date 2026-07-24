import request from '@/axios'
import { PATH_URL } from '@/axios/service'
import { useUserStoreWithOut } from '@/store/modules/user'
import type {
  ReviewBAuditView,
  ReviewBEvent,
  ReviewBMessage,
  ReviewBSession,
  ReviewBWorkspace
} from '@/types/ai-review-b'

type MutationOptions = {
  etag?: string
  idempotencyKey?: string
}

const createIdempotencyKey = (prefix: string) => {
  const random =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2)}`
  return `${prefix}-${random}`
}

const mutationHeaders = (prefix: string, options?: MutationOptions) => {
  const headers: Record<string, string> = {
    'Idempotency-Key': options?.idempotencyKey || createIdempotencyKey(prefix)
  }
  if (options?.etag) headers['If-Match'] = options.etag
  return headers
}

export const getReviewBWorkspaceApi = (
  projectId: string,
  nodeId: number,
  reviewRunId?: string
): Promise<IResponse<ReviewBWorkspace>> => {
  return request.get({
    url: `/api/projects/${projectId}/inspection/nodes/${nodeId}/review-workspace`,
    params: reviewRunId ? { reviewRunId } : undefined
  })
}

export const createReviewBSessionApi = (
  projectId: string,
  nodeId: number,
  data: { currentTask?: string; reviewRunId?: string },
  options?: MutationOptions
): Promise<IResponse<{ session: ReviewBSession; created: boolean }>> => {
  return request.post({
    url: `/api/projects/${projectId}/inspection/nodes/${nodeId}/review-sessions`,
    data,
    headers: mutationHeaders('review-session', options)
  })
}

export const listReviewBMessagesApi = (
  sessionId: string,
  after = 0
): Promise<IResponse<{ sessionId: string; messages: ReviewBMessage[]; lastSequence: number }>> => {
  return request.get({
    url: `/api/review-sessions/${sessionId}/messages`,
    params: { after }
  })
}

export const sendReviewBMessageApi = (
  sessionId: string,
  content: string,
  options?: MutationOptions
): Promise<
  IResponse<{
    messageId: string
    status: string
    userMessage: ReviewBMessage
    assistantMessage: ReviewBMessage
    session: ReviewBSession
  }>
> => {
  return request.post({
    url: `/api/review-sessions/${sessionId}/messages`,
    data: { content },
    headers: mutationHeaders('review-message', options)
  })
}

export const runReviewBSessionActionApi = (
  sessionId: string,
  actionKey: 'select_evidence' | 'remove_evidence' | 'set_active_review_run' | 'set_current_task',
  data: Record<string, unknown>,
  options?: MutationOptions
): Promise<IResponse<{ session: ReviewBSession }>> => {
  return request.post({
    url: `/api/review-sessions/${sessionId}/actions/${actionKey}`,
    data,
    headers: mutationHeaders('review-action', options)
  })
}

export const listReviewBEventsApi = (
  sessionId: string,
  after = 0
): Promise<
  IResponse<{
    schema: string
    sessionId: string
    events: ReviewBEvent[]
    lastSequence: number
    transport: 'polling' | 'sse'
  }>
> => {
  return request.get({
    url: `/api/review-sessions/${sessionId}/events`,
    params: { after }
  })
}

/**
 * SSE 事件流消费：使用 fetch + ReadableStream（EventSource 无法携带鉴权头）。
 * 每收到一条事件就回调 onEvent；连接结束或异常时正常返回，由调用方决定是否降级为轮询。
 */
export const streamReviewBEventsApi = async (
  sessionId: string,
  after: number,
  onEvent: (event: ReviewBEvent) => void,
  signal: AbortSignal
): Promise<void> => {
  const userStore = useUserStoreWithOut()
  const userInfo = userStore.getUserInfo
  const response = await fetch(
    `${PATH_URL}/api/review-sessions/${sessionId}/events/stream?after=${after}`,
    {
      headers: {
        [userStore.getTokenKey ?? 'Authorization']: userStore.getToken ?? '',
        'X-Role': userInfo?.role ?? '',
        'X-User-Id': userInfo?.id ?? ''
      },
      signal
    }
  )
  if (!response.ok || !response.body) {
    throw new Error(`SSE stream failed: ${response.status}`)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const chunks = buffer.split('\n\n')
    buffer = chunks.pop() ?? ''
    for (const chunk of chunks) {
      for (const line of chunk.split('\n')) {
        if (!line.startsWith('data: ')) continue
        try {
          const parsed = JSON.parse(line.slice(6))
          if (parsed && parsed.eventId) onEvent(parsed as ReviewBEvent)
        } catch {
          // 忽略心跳与非 JSON 数据行。
        }
      }
    }
  }
}

export const getReviewBAuditViewApi = (
  reviewRunId: string
): Promise<IResponse<ReviewBAuditView>> => {
  return request.get({ url: `/api/review-runs/${reviewRunId}/audit-view` })
}

export const submitReviewBHumanDecisionApi = (
  reviewRunId: string,
  data: {
    decision: 'accept' | 'edit' | 'reject'
    comment: string
    correctedOutput?: Array<Record<string, unknown>>
    evidenceLinkIds?: string[]
  },
  options?: MutationOptions
): Promise<IResponse<Record<string, unknown>>> => {
  return request.post({
    url: `/api/review-runs/${reviewRunId}/human-decision`,
    data,
    headers: mutationHeaders('review-decision', options)
  })
}
