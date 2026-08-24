/**
 * AI 复核对话框的推荐问题。
 *
 * ## 为什么是规则拼装而不是让 LLM 生成
 *
 * 系统已经知道这个节点此刻卡在哪：audit-workspace 返回的 items 里带着
 * `needs_attention` 的具体 issue（OCR_INCOMPLETE、MISSING_REQUIRED_EVIDENCE…），
 * businessBasis 里带着该规则的 criteria 与 checkMethod（完整中文审查要点）。
 *
 * 让 LLM 生成推荐，得先把这些事实喂给它——而喂进去的那一刻，答案已经在手上了。
 * 另外三点实际代价：
 *
 *   延迟   推荐要在对话框渲染时就在。等两秒模型返回，人已经自己打字了。
 *   成本   69 个节点 × 每天多次进出，每次进节点烧一轮 token。
 *   稳定   同一个节点两次进来推荐不同问题，监检会开始怀疑系统。
 *
 * 真正值得接 LLM 的是**下一步**：监检点了推荐问题之后，回答它需要检索证据、
 * 读 OCR 产物、对照条款——那才是模型该干的活。
 *
 * ## 排序原则
 *
 * 当前卡点排在最前。监检打开这个节点，十有八九是为了处理那件事；
 * 把「了解规则」类的问题排前面，等于让他先读一遍他已经知道的东西。
 */

export type AuditIssue = {
  code?: string
  message?: string
}

export type AuditItemLike = {
  key?: string
  label?: string
  status?: string
  metric?: string
  summary?: string
  issues?: AuditIssue[]
}

export type BusinessBasisLike = {
  inspectionItem?: unknown
  ruleName?: unknown
  criteria?: unknown
  checkMethod?: unknown
}

export type SuggestedQuestion = {
  /** 点击后填进输入框的问题原文 */
  text: string
  /** 来源：当前卡点 / 规则依据 / 通用。仅用于排序与埋点，不显示 */
  origin: 'blocker' | 'rule' | 'general'
}

const ATTENTION_STATUSES = new Set([
  'needs_attention',
  'failed',
  'execution_failed',
  '需关注',
  '执行失败'
])

/** 按 issue code 定制的问法。认不出的 code 退回用 item 自己的 summary。 */
const QUESTION_BY_ISSUE_CODE: Record<string, string> = {
  OCR_INCOMPLETE: '这个节点的 OCR 抽取不完整，是哪份资料、缺了什么？',
  MISSING_REQUIRED_EVIDENCE: '还缺哪些资料或证据？分别对应哪个审查点和什么风险？',
  MATERIALS_MISSING: '当前还缺哪些资料？分别影响什么审查判断？',
  RECTIFICATION_OPEN: '未关闭的补正事项是什么？对方回复了吗？',
  REPORT_EVIDENCE_INVALID: '报告的证据校验为什么没通过？',
  ARCHIVE_EXPORT_FAILED: '归档导出失败的原因是什么？',
  SEAL_REQUIRED_AND_READABLE: '必须盖章的资料都盖了吗？印章能认出来吗？'
}

const truncate = (value: string, limit: number) =>
  value.length > limit ? `${value.slice(0, limit)}…` : value

/**
 * 从当前卡点生成问题。
 *
 * 只取 needs_attention 的项——正在跑的和已完成的不需要问。
 */
const blockerQuestions = (items: AuditItemLike[]): SuggestedQuestion[] => {
  const questions: SuggestedQuestion[] = []
  for (const item of items) {
    if (!item || !ATTENTION_STATUSES.has(String(item.status))) continue
    const code = String((item.issues || [])[0]?.code || '')
    const mapped = QUESTION_BY_ISSUE_CODE[code]
    if (mapped) {
      questions.push({ text: mapped, origin: 'blocker' })
      continue
    }
    // 认不出的 code 用 item 的 summary 兜底，而不是跳过：
    // 跳过会让「这个节点明明卡住了却没有相关推荐」，看上去像推荐坏了。
    const summary = String(item.summary || '').trim()
    if (summary) {
      questions.push({ text: `${summary}具体是什么情况？`, origin: 'blocker' })
    }
  }
  return questions
}

/**
 * 从规则依据生成问题。
 *
 * criteria 是完整的中文审查要点（动辄几百字），不能整段塞进按钮——
 * 截断到一句话，让人看得出问的是什么，具体内容由模型去读。
 */
const ruleQuestions = (basis: BusinessBasisLike): SuggestedQuestion[] => {
  const questions: SuggestedQuestion[] = []
  const item = String(basis.inspectionItem || basis.ruleName || '').trim()
  if (item) {
    questions.push({ text: `${item}的判定依据是什么？`, origin: 'rule' })
  }
  const checkMethod = String(basis.checkMethod || '').trim()
  if (checkMethod) {
    questions.push({
      text: `按「${truncate(checkMethod.replace(/^工作见证：\s*/, ''), 24)}」核对，现有资料够吗？`,
      origin: 'rule'
    })
  }
  return questions
}

const GENERAL_QUESTIONS: SuggestedQuestion[] = [
  { text: '这个节点现在可以出结论了吗？还差什么？', origin: 'general' }
]

/**
 * 把 evidenceReadiness.blockingReasons 转成与审计项同构的形状。
 *
 * 两个来源给的是同一件事的两种记法：审计项总览走 items[].issues[].code，
 * 而 AI 复核工作台手上只有 blockingReasons[].code。推荐问题不该关心数据从哪来，
 * 所以在这里归一，而不是在调用处写两套分支。
 */
export const blockingReasonsAsItems = (reasons: AuditIssue[] | undefined): AuditItemLike[] =>
  (reasons || [])
    .filter((reason) => reason && typeof reason === 'object')
    .map((reason) => ({
      key: String(reason.code || ''),
      status: 'needs_attention',
      summary: String(reason.message || ''),
      issues: [reason]
    }))

/**
 * 生成推荐问题。当前卡点在前，规则依据其次，通用兜底。
 *
 * @param limit 最多几条。默认 4——再多就成了一堵墙，人反而不会读。
 */
export const buildSuggestedQuestions = (
  items: AuditItemLike[] | undefined,
  basis: BusinessBasisLike | undefined,
  limit = 4
): SuggestedQuestion[] => {
  const list = (items || []).filter((item) => item && typeof item === 'object')
  const merged = [...blockerQuestions(list), ...ruleQuestions(basis || {}), ...GENERAL_QUESTIONS]
  // 同一个问题可能从卡点和规则两条路各出一次，去重时保留先出现的（卡点优先）
  const seen = new Set<string>()
  const unique: SuggestedQuestion[] = []
  for (const question of merged) {
    const text = question.text.trim()
    if (!text || seen.has(text)) continue
    seen.add(text)
    unique.push({ ...question, text })
  }
  return unique.slice(0, Math.max(1, limit))
}
