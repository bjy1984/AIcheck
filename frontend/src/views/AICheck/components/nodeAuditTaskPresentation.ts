/**
 * 节点审计任务队列的展示口径（2026-11-05 用户：要能看到节点审计进度，点了能跳到节点继续）。
 *
 * 分三段：进行中（审查中、排队中）→ 要你处理（等你补充、失败、出了结果还没确认）→
 * 已处理（已确认、缺项预审、已取消）。每行一句话说清楚走到哪、下一步做什么。
 */
import type { InspectionNodeConclusionGroup } from '@/types/aicheck'
import type { NodeAuditTask, NodeAuditTasksPayload } from '@/api/aicheck/nodeAuditTasks'
import { STATION_GROUP_LABELS } from './stationOverview'

export type TaskTone = 'primary' | 'info' | 'warning' | 'danger' | 'success'
export type TaskSectionKey = 'active' | 'attention' | 'settled'

/** 秒数写成「38 秒」「6 分钟」「1 小时 12 分」。 */
export const formatDuration = (seconds?: number | null): string => {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return ''
  if (seconds < 60) return `${Math.floor(seconds)} 秒`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} 分钟`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest ? `${hours} 小时 ${rest} 分` : `${hours} 小时`
}

const needsConfirmation = (task: NodeAuditTask) =>
  task.state === 'done' && !task.confirmed && !task.advisoryOnly

export const taskSection = (task: NodeAuditTask): TaskSectionKey => {
  if (task.state === 'running' || task.state === 'queued') return 'active'
  if (task.state === 'needs_input' || task.state === 'failed' || needsConfirmation(task))
    return 'attention'
  return 'settled'
}

export const TASK_SECTION_TITLES: Record<TaskSectionKey, string> = {
  active: '进行中',
  attention: '要你处理',
  settled: '已处理'
}

const resultLabel = (group?: InspectionNodeConclusionGroup, notApplicable?: boolean) => {
  if (!group) return '已出结果'
  if (notApplicable) return '不适用'
  return STATION_GROUP_LABELS[group]
}

const RESULT_TONE: Record<InspectionNodeConclusionGroup, TaskTone> = {
  failed: 'danger',
  needs_materials: 'warning',
  needs_human: 'warning',
  passed: 'success',
  not_started: 'info'
}

export type TaskView = {
  /** 右侧状态标签 */
  badge: string
  tone: TaskTone
  /** 节点名下面那一行：走到哪、等了多久、为什么失败 */
  line: string
  /** 点这一行做什么（按钮文字），以及落到节点页的哪一栏 */
  action: string
  auditItem: 'ai_review' | 'human_review'
}

export const describeTask = (task: NodeAuditTask): TaskView => {
  const mode = task.advisoryOnly ? '缺项预审' : 'AI 复核'
  switch (task.state) {
    case 'running': {
      const elapsed = formatDuration(task.elapsedSeconds)
      return {
        badge: '审查中',
        tone: 'primary',
        line: `${mode}进行中${elapsed ? `，已 ${elapsed}` : ''}`,
        action: '查看节点',
        auditItem: 'ai_review'
      }
    }
    case 'queued': {
      const waited = formatDuration(task.waitSeconds)
      const ahead =
        task.queueAhead == null
          ? '等待执行'
          : task.queueAhead === 0
            ? '下一个就轮到'
            : `前面还有 ${task.queueAhead} 个`
      return {
        badge: '排队中',
        tone: 'info',
        line: `${ahead}${waited ? `，已等 ${waited}` : ''}`,
        action: '查看节点',
        auditItem: 'ai_review'
      }
    }
    case 'needs_input':
      return {
        badge: '等你补充',
        tone: 'warning',
        line: '审查停下来了，需要你补充核验信息后才能继续',
        action: '去补充',
        auditItem: 'ai_review'
      }
    case 'failed':
      return {
        badge: '失败',
        tone: 'danger',
        line: task.errorMessage || `${mode}没有完成`,
        action: '去重新发起',
        auditItem: 'ai_review'
      }
    case 'cancelled':
      return {
        badge: '已取消',
        tone: 'info',
        line: `${mode}已取消`,
        action: '查看节点',
        auditItem: 'ai_review'
      }
    default: {
      const label = resultLabel(task.result?.group, task.result?.notApplicable)
      if (task.advisoryOnly) {
        return {
          badge: '预审完成',
          tone: 'info',
          line: '缺项预审只提示缺什么，不出结论；要出结论请发起正式复核',
          action: '查看节点',
          auditItem: 'ai_review'
        }
      }
      if (task.confirmed) {
        return {
          badge: '已确认',
          tone: 'success',
          line: `AI 判定：${label}；监检结论：${task.humanResult || '已填写'}`,
          action: '查看节点',
          auditItem: 'human_review'
        }
      }
      return {
        badge: label,
        tone: task.result ? RESULT_TONE[task.result.group] : 'info',
        line: `AI 判定：${label}，等你确认并写监检结论`,
        action: '去确认',
        auditItem: 'human_review'
      }
    }
  }
}

export const groupTasks = (payload?: NodeAuditTasksPayload | null) => {
  const sections: Record<TaskSectionKey, NodeAuditTask[]> = {
    active: [],
    attention: [],
    settled: []
  }
  for (const task of payload?.items || []) sections[taskSection(task)].push(task)
  return (Object.keys(sections) as TaskSectionKey[])
    .map((key) => ({ key, title: TASK_SECTION_TITLES[key], tasks: sections[key] }))
    .filter((section) => section.tasks.length)
}

/** 顶栏按钮上的数字：有在跑的显示在跑的个数（蓝），否则显示要你处理的个数（橙）。 */
export const queueBadge = (
  payload?: NodeAuditTasksPayload | null
): { count: number; tone: 'active' | 'attention' } | null => {
  if (!payload) return null
  if (payload.active) return { count: payload.active, tone: 'active' }
  const attention = payload.items.filter((task) => taskSection(task) === 'attention').length
  return attention ? { count: attention, tone: 'attention' } : null
}

/**
 * 两次轮询之间刚结束的节点：上次在进行中、这次不在了。
 * 用来提示「审完了」并让总览刷新——不用等用户自己去点。
 */
export const settledSince = (
  previous: NodeAuditTasksPayload | null | undefined,
  next: NodeAuditTasksPayload
): NodeAuditTask[] => {
  if (!previous) return []
  const wasActive = new Set(
    previous.items.filter((task) => taskSection(task) === 'active').map((task) => task.nodeId)
  )
  return next.items.filter((task) => wasActive.has(task.nodeId) && taskSection(task) !== 'active')
}
