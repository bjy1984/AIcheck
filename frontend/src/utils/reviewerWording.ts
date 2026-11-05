/**
 * 施工方、无损检测、建设方看到的字眼不提「AI / 人工智能」（2026-11-04 用户）。
 *
 * 审查过程里机器做的事对外一律说成「审查 / 预审」，要人拍板的一律说成「审核员」。
 * 只改显示：同一份状态、退回原因、消息标题监检和管理员照原样看。
 * 只替换明确的说法，不做「人工 → 审核员」的通配：「人工挂载」是施工方自己挂的资料，
 * 换成「审核员挂载」就错了。
 */
import type { RoleCode } from '@/types/aicheck'

/** 这些角色看原文：监检要知道哪些是 AI 给的、哪些是人定的；管理员、FDE 管着 AI 本身。 */
const SEES_AI_WORDING: ReadonlySet<string> = new Set(['inspection', 'admin', 'fde'])

export const usesPlainWording = (role?: RoleCode | string | null) =>
  !SEES_AI_WORDING.has(String(role || ''))

const HUMAN_ACTIONS = '确认|复核|核验|核对|辨认|判断|审查|审核|结论|判定|复审'

const REPLACEMENTS: Array<[RegExp, string]> = [
  // 人工智能审查 → 审查；其余单独的人工智能 → 审核
  [/人工智能\s*(?=预审|审查|复核|分析|核验|判定|判断|识别|抽取|结论|建议|发现)/g, ''],
  [/人工智能/g, '审核'],
  // 待人工确认 / 需人工复核 / 人工核对 → 审核员…
  [new RegExp(`人工(${HUMAN_ACTIONS})`, 'g'), '审核员$1'],
  // AI 预审中 / AI审查 / AI 复核 → 预审中 / 审查 / 复核
  [/(?<![A-Za-z])AI\s*(?=预审|审查|复核|分析|核验|判定|判断|识别|抽取|结论|建议|发现)/g, ''],
  // 剩下单独的 AI（「AI 已完成」）说成「审核」
  [/(?<![A-Za-z])AI(?![A-Za-z])\s*/g, '审核']
]

export const plainWording = (text: string | null | undefined): string => {
  let value = String(text ?? '')
  for (const [pattern, replacement] of REPLACEMENTS) value = value.replace(pattern, replacement)
  return value
}

/**
 * 产品对外的名字（2026-11-04）：登录页所有角色共用、还认不出是谁，
 * 施工方、无损检测、建设方登录后也用它；监检、管理员、FDE 的浏览器标题照旧用
 * VITE_APP_TITLE（生产是「AIcheck」）。
 */
export const PLAIN_APP_TITLE = '压力管道监检协作系统'

export const appTitleFor = (role: RoleCode | string | null | undefined, envTitle: string) =>
  role && !usesPlainWording(role) ? envTitle : PLAIN_APP_TITLE

/** 按角色决定要不要换说法：组件里统一用这个。 */
export const wordingFor = (role?: RoleCode | string | null) =>
  usesPlainWording(role) ? plainWording : (text: string | null | undefined) => String(text ?? '')
