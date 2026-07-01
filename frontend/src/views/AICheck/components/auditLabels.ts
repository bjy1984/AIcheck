export const reviewStatusLabels: Record<string, string> = {
  created: '已创建',
  queued: '排队中',
  context_building: '构建上下文',
  ocr_waiting: '等待 OCR',
  rule_checking: '规则校验中',
  knowledge_retrieving: '知识检索中',
  llm_reviewing: 'Agent 审查中',
  evidence_validating: '证据校验中',
  schema_validating: '格式校验中',
  critic_reviewing: '复核校验中',
  quality_checking: '质量门禁中',
  draft_persisted: '草稿已留存',
  waiting_human_review: '等待人工复核',
  accepted_by_human: '人工已采纳',
  edited_by_human: '人工已修正',
  rejected_by_human: '人工已驳回',
  rerun_requested: '已请求重跑',
  failed: '失败',
  cancelled: '已取消',
  superseded: '已被替代'
}

export const techTermLabels: Record<string, string> = {
  LangGraph: 'Agent 编排图',
  PageIndex: '章节溯源',
  Vectorization: '资料向量化',
  RetrievalTrace: '检索轨迹',
  QualityGate: '质量门禁',
  Temporal: '流程编排',
  HybridRag: '混合检索',
  pageindex: '章节溯源',
  pageindex_tree_search: '章节树检索',
  langgraph: 'Agent 编排图',
  vector: '资料向量化'
}

export const friendlyReviewStatus = (status?: string | null) => {
  if (!status) return '未知状态'
  return reviewStatusLabels[status] || status
}

export const friendlyTechTerm = (value?: string | null) => {
  if (!value) return '未返回'
  return techTermLabels[value] || value
}
