/** 节点审计任务队列（2026-11-05）。后端见 backend/apps/api/node_audit_task_routes.py。 */

import type { InspectionNodeConclusionGroup } from '@/types/aicheck'

export type NodeAuditTaskState =
  | 'running'
  | 'queued'
  | 'needs_input'
  | 'failed'
  | 'done'
  | 'cancelled'

/** 每个节点一行：它最近一次 AI 复核。 */
export type NodeAuditTask = {
  nodeId: number
  nodeName: string
  groupName?: string | null
  aiRunId?: string | null
  reviewRunId?: string | null
  state: NodeAuditTaskState
  rawStatus?: string | null
  /** 排队太久、执行进程已不在而判失败的 */
  stale: boolean
  reviewMode: 'formal' | 'gap_precheck' | string
  /** 缺项预审：只提示缺什么，不出结论 */
  advisoryOnly: boolean
  /** 排队中：前面还有几个（问不到队列时为空） */
  queueAhead?: number | null
  currentStep?: string | null
  createdAt?: string | null
  startedAt?: string | null
  finishedAt?: string | null
  waitSeconds?: number | null
  elapsedSeconds?: number | null
  errorMessage?: string | null
  result?: { group: InspectionNodeConclusionGroup; notApplicable: boolean } | null
  /** 这次复核之后监检已经给了人工结论 */
  confirmed: boolean
  humanResult?: string | null
}

export type NodeAuditTasksPayload = {
  projectId: string
  items: NodeAuditTask[]
  counts: Record<NodeAuditTaskState, number> & { awaitingConfirmation: number }
  /** 排队中＋审查中 */
  active: number
  settledTotal: number
  settledShown: number
  dataAsOf: string
}

type RequestAdapter = {
  get: (config: { url: string; headers?: Record<string, string> }) => Promise<any>
}

// 这个接口是轮询的：出错不弹全局提示（否则每 15 秒弹一次），由抽屉里自己显示
const SILENT = { 'X-Silent-Business-Error': 'true', 'X-Silent-Http-Error': 'true' }

export const createNodeAuditTaskApi = (adapter: RequestAdapter) => ({
  getNodeAuditTasksApi: (projectId: string): Promise<IResponse<NodeAuditTasksPayload>> =>
    adapter.get({
      url: `/api/projects/${encodeURIComponent(projectId)}/inspection/node-audit-tasks`,
      headers: SILENT
    })
})
