/**
 * 把节点的七个审计项汇成一句话。
 *
 * 经典视图原先每行平铺七个状态标签，一页 14 行就是 98 个标签、56 个可点元素，
 * 而实测它们绝大多数是同一个值（471/483 个审计项是「未开始」）。监检要在
 * 一屏几乎一样的标签里找出不一样的那几个。
 *
 * 业务前提（2026-08-13 与业务方确认）：**监检最好只需要知道状态，全程不需要
 * 人工干预**。既然如此，列表要回答的就只有一个问题——「这个节点现在要不要我管」。
 * 七项明细移到点开详情后再看。
 *
 * ## 为什么汇总必须带上「卡在哪一步」
 *
 * 只说「需关注」等于把问题原样丢回给人：他还得点进去逐项翻才知道是 OCR 没跑完
 * 还是等他签字。汇总的价值在于替他做完这次翻找，而不是把七个标签换成一个。
 */

/** 审计项的原始状态取值。中英混用是历史遗留，两边都要认。 */
export type AuditItemStatus = string

export type AuditItem = {
  key: string
  label: string
  status: AuditItemStatus
  statusLabel?: string
  metric?: string
  summary?: string
}

export type NodeAggregate = {
  /** 列表用的单一状态 */
  tone: 'attention' | 'running' | 'done' | 'idle'
  /** 状态词，直接显示 */
  label: string
  /** 卡在哪一步。没有阻塞时为空 */
  blockedAt: string
  /** 完成度，例如 2/7 */
  progress: string
}

const ATTENTION_STATUSES = new Set(['需关注', '执行失败', 'failed', 'attention'])
const RUNNING_STATUSES = new Set(['处理中', '推理中', 'running', '执行中'])
const DONE_STATUSES = new Set(['已完成', 'completed', 'done'])

/**
 * 汇总一个节点的七项状态。
 *
 * 优先级是刻意的：**需关注 > 进行中 > 未开始 > 已完成**。
 * 「已完成」排在最后而不是最前——一个节点只要还有一项要人管，它就是要人管的，
 * 哪怕另外六项都完成了。按「完成得最多」排会把真正卡住的节点藏起来。
 */
export const aggregateNodeStatus = (items: AuditItem[] | undefined): NodeAggregate => {
  const list = (items || []).filter((item) => item && typeof item === 'object')
  if (!list.length) {
    return { tone: 'idle', label: '未开始', blockedAt: '', progress: '' }
  }

  const done = list.filter((item) => DONE_STATUSES.has(String(item.status)))
  const progress = `${done.length}/${list.length}`

  const attention = list.find((item) => ATTENTION_STATUSES.has(String(item.status)))
  if (attention) {
    return {
      tone: 'attention',
      label: '需要处理',
      // 指名道姓说是哪一步——只说「需关注」等于让人自己再翻一遍七项
      blockedAt: attention.label,
      progress
    }
  }

  const running = list.find((item) => RUNNING_STATUSES.has(String(item.status)))
  if (running) {
    return { tone: 'running', label: '系统处理中', blockedAt: running.label, progress }
  }

  if (done.length === list.length) {
    return { tone: 'done', label: '已完成', blockedAt: '', progress }
  }

  if (done.length > 0) {
    // 有进展但没有任何一项在跑，也没有卡住——通常是等上游资料
    return { tone: 'idle', label: '等待资料', blockedAt: '', progress }
  }

  return { tone: 'idle', label: '未开始', blockedAt: '', progress }
}

/**
 * 列表默认只看「要我管的」。
 *
 * 69 个节点里绝大多数与今天无关。全列出来，真正需要处理的那几个就淹没在
 * 一屏「未开始」里——这正是原先 471/483 那个数字的问题：它不驱动任何行动。
 */
export const nodeNeedsAttention = (items: AuditItem[] | undefined): boolean =>
  aggregateNodeStatus(items).tone === 'attention'
