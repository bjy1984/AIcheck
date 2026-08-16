/**
 * 把模型输出的 findings JSON 变成人能读的结论。
 *
 * 线上实测（2026-08-16，监检工作台节点 24）：「AI 建议（待人工确认）」下面
 * 直接打出原始 JSON——
 *
 *     { "findings": [ { "findingType": "insufficient_evidence",
 *       "severity": "medium", "title": "焊工资格证及持证合格项目证据不足…",
 *       "evidenceRefs": [ { "evidenceLinkId": "R24EV-65B8B5FF8238", … } ] } ] }
 *
 * 监检要在花括号和转义引号里找结论。**这不是「不好看」，是让人读不到判定**——
 * 而读不到判定的界面，等于没给判定。
 *
 * 解析不出来就原样返回文本：模型偶尔会回纯文字，那时候把原文给人看是对的，
 * 硬套结构只会把内容吃掉。
 */

export interface AiFinding {
  /** 结论类型（已翻译） */
  typeLabel: string
  /** 严重度（已翻译），空串表示模型没给 */
  severityLabel: string
  severity: 'high' | 'medium' | 'low' | ''
  title: string
  description: string
  evidenceCount: number
  ruleCount: number
}

const FINDING_TYPE_LABELS: Record<string, string> = {
  insufficient_evidence: '证据不足',
  evidence_insufficient: '证据不足',
  missing_material: '资料缺失',
  missing_field: '字段缺失',
  field_mismatch: '字段不一致',
  expired: '已过期',
  scope_not_covered: '范围未覆盖',
  name_mismatch: '名称不一致',
  seal_missing: '缺少印章',
  compliant: '符合要求',
  not_applicable: '不适用'
}

const SEVERITY_LABELS: Record<string, string> = {
  high: '高',
  medium: '中',
  low: '低',
  critical: '严重',
  info: '提示'
}

/** 去掉 ```json 围栏——模型常这么包一层。 */
const stripFence = (raw: string): string => {
  let text = String(raw || '').trim()
  if (!text.startsWith('```')) return text
  text = text.slice(text.indexOf('\n') + 1)
  if (text.endsWith('```')) text = text.slice(0, -3)
  return text.trim()
}

const asList = (parsed: unknown): unknown[] => {
  if (Array.isArray(parsed)) return parsed
  if (parsed && typeof parsed === 'object') {
    const holder = parsed as Record<string, unknown>
    for (const key of ['findings', 'items', 'results']) {
      if (Array.isArray(holder[key])) return holder[key] as unknown[]
    }
  }
  return []
}

const countOf = (value: unknown): number => (Array.isArray(value) ? value.length : 0)

/**
 * 解析模型输出。
 *
 * @returns findings 为空数组时表示「这不是 findings JSON」，调用方应原样显示文本。
 */
export const parseAiFindings = (raw: string): AiFinding[] => {
  const text = stripFence(raw)
  if (!text.startsWith('{') && !text.startsWith('[')) return []
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    return []
  }
  return asList(parsed)
    .filter((item): item is Record<string, unknown> => !!item && typeof item === 'object')
    .map((item) => {
      const rawType = String(item.findingType || item.type || '').trim()
      const rawSeverity = String(item.severity || '')
        .trim()
        .toLowerCase()
      return {
        typeLabel: FINDING_TYPE_LABELS[rawType] || rawType || '未分类',
        severity: (['high', 'medium', 'low'].includes(rawSeverity)
          ? rawSeverity
          : '') as AiFinding['severity'],
        severityLabel: SEVERITY_LABELS[rawSeverity] || '',
        title: String(item.title || '').trim(),
        description: String(item.description || item.detail || '').trim(),
        evidenceCount: countOf(item.evidenceRefs || item.evidence),
        ruleCount: countOf(item.ruleRefs || item.rules)
      }
    })
    .filter((item) => item.title || item.description)
}
