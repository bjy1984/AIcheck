/**
 * 「AI审查」对话记忆的界面口径（后端规则见 backend/apps/api/review_session_memory.py）。
 *
 * 文章〈The components of agent memory〉没讲、但平台必须做到的一条：用户能看见 AI 被告知了什么，
 * 也能拿掉它。所以上一段对话的要点、AI 参考多少天的对话、个人偏好，都要摆在面板上，
 * 而不是只藏在发给模型的上下文里。
 */
import type { ReviewBCarryOver, ReviewBSession } from '@/types/ai-review-b'

/** 「2026-11-02 14:03:11」→「11-02 14:03」；对不上格式就原样返回。 */
export const shortStamp = (value?: string | null) => {
  const match = /^\d{4}-(\d{2}-\d{2}) (\d{2}:\d{2})/.exec(String(value || ''))
  return match ? `${match[1]} ${match[2]}` : String(value || '')
}

export type CarryOverLine = {
  key: string
  kind: 'answered' | 'unanswered'
  verdict: string
  tone: 'danger' | 'warning' | 'success' | 'info'
  question: string
  /** 多项时的结论计数，例如「5 项：证据不足 3、符合 2」 */
  summary: string
  answer: string
  askedAt: string
}

const verdictTone = (verdict?: string | null): CarryOverLine['tone'] => {
  if (verdict === '不符合') return 'danger'
  if (verdict === '证据不足' || verdict === '需人工确认') return 'warning'
  if (verdict === '符合') return 'success'
  return 'info'
}

export const carryOverLines = (carry?: ReviewBCarryOver | null): CarryOverLine[] => {
  if (!carry) return []
  return [
    ...(carry.items || []).map((item, index) => ({
      key: `answered-${index}`,
      kind: 'answered' as const,
      verdict: item.verdict || '未下结论',
      tone: verdictTone(item.verdict),
      question: item.question,
      summary: item.verdictSummary || '',
      answer: item.answer || '',
      askedAt: shortStamp(item.askedAt)
    })),
    ...(carry.unanswered || []).map((item, index) => ({
      key: `unanswered-${index}`,
      kind: 'unanswered' as const,
      verdict: '没答完',
      tone: 'info' as const,
      question: item.question,
      summary: '',
      answer: '',
      askedAt: shortStamp(item.askedAt)
    }))
  ]
}

export const hasCarryOver = (session?: ReviewBSession | null) =>
  carryOverLines(session?.carryOver).length > 0

/** 会话闲置超过 AI 参考的天数时给一句提示；没超过就不说话。 */
export const historyHint = (session?: ReviewBSession | null) => {
  const memory = session?.memory
  if (!memory?.historyExpired) return ''
  const last = shortStamp(memory.lastMessageAt)
  return `上次发言在 ${last}，已超过 ${memory.historyDays} 天，AI 不再参考这段对话。要接着做，建议开始新对话。`
}

/** 按字符数（不是 UTF-16 码元）算，和后端 len() 对齐。 */
export const preferenceLength = (text: string) => [...text.trim()].length
