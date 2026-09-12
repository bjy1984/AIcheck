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

export const statusLabelMap: Record<string, string> = {
  ...reviewStatusLabels,
  active: '启用',
  accepted: '已接受',
  approved_for_eval: '已准入评估集',
  blocked_by_gate: '门禁阻断',
  complete: '已完成',
  completed: '已完成',
  degraded: '降级运行',
  draft: '草稿',
  fail: '未通过',
  high: '高',
  incomplete: '不完整',
  labeled: '待二审',
  low: '低',
  low_confidence_field: '字段识别置信度低',
  medium: '中',
  missing: '缺失',
  needs_human_confirmation: '需要人工确认',
  needs_human_review: '需人工复核',
  needs_labeling: '待标注',
  needs_triage: '待归因',
  normal: '正常',
  over_budget: '超预算',
  pass: '通过',
  passed: '通过',
  production: '生产中',
  production_approved: '生产已批准',
  ready: '就绪',
  ready_for_eval: '可入评估',
  request_correction: '建议发起补正',
  reviewed: '已复核',
  running: '运行中',
  stale: '需刷新',
  success: '成功',
  triaged: '已归因',
  unknown: '未知',
  warning: '告警',
  shadow: '影子运行',
  hybrid_rag: '混合检索',
  pageindex: '章节溯源',
  pageindex_tree_search: '章节树检索',
  vector_search: '向量检索',
  review_basis_search: '审查依据检索',
  long_document_cross_section: '长文档跨章节检索'
}

export const techTermLabels: Record<string, string> = {
  Agent: 'AI 员工',
  Bundle: '能力组合',
  COG: '公开判断摘要',
  Checkpoint: '检查点',
  Draft: '草稿',
  FDE: 'AI 交付工程师',
  Flags: '标记',
  Graph: '编排图',
  Hash: '校验哈希',
  HybridRag: '混合检索',
  Job: '任务编号',
  Key: '键',
  LangGraph: 'Agent 编排图',
  LiteLLM: 'LiteLLM 模型网关',
  LLM: '大模型审查',
  Metadata: '元数据',
  Model: '模型',
  OCR: 'OCR 文字识别',
  'Payload Hash': '载荷校验哈希',
  PageIndex: '章节溯源',
  'Postgres Checkpointer': 'PostgreSQL 检查点',
  Profile: '解析配置',
  Prompt: '提示词',
  RAG: '知识检索',
  ReviewRun: '审查任务',
  'Run ID': '运行编号',
  Schema: '结构约束',
  Temporal: '流程编排',
  Token: 'Token 用量',
  Trace: '溯源记录',
  Workflow: '工作流',
  'Vector ID': '向量编号',
  Vectorization: '资料向量化',
  QualityGate: '质量门禁',
  RetrievalTrace: '检索轨迹',
  all: '全部配置',
  chat_completions: '调用大模型',
  'chat.completions': '调用大模型',
  ActivityCompleted: '活动已完成',
  agentdesign_seal_ocr_subprocess: '印章文字识别子进程',
  archive_agent: '归档完整性检查员',
  bge_large_zh_v1_5: '本地中文向量模型',
  'bge-large-zh-v1.5': '本地中文向量模型',
  bge_m3: '本地多语种向量模型',
  'bge-m3': '本地多语种向量模型',
  bge_reranker_v2_m3: '本地知识重排模型',
  'bge-reranker-v2-m3': '本地知识重排模型',
  cog_reasoning_summary: '公开判断摘要',
  compliance_review_agent: '资料合规复核员',
  construction_record_v1: '施工记录解析配置',
  correction_agent: '补正单起草员',
  deepseek_reasoner: 'DeepSeek 推理模型',
  'deepseek-reasoner': 'DeepSeek 推理模型',
  document_intelligence: '文档智能服务',
  document_intelligence_service: '文档智能服务',
  document_parser_agent: '文档解析员',
  embedding_default: '默认本地向量模型',
  'embedding-default': '默认本地向量模型',
  engineering_document: '通用工程资料',
  engineering_inspection_v1: 'GC类 工业管道',
  engineering_rules: '工程监检规则集',
  'engineering_rules@1.0.0': '工程监检规则集 1.0.0',
  engineering_table_photo: '工程表格照片',
  evidence_validation: '证据校验',
  field_extraction: '字段抽取',
  field_inconsistent: '字段不一致',
  field_missing: '字段缺失',
  cross_document_consistency_warning: '跨资料一致性风险',
  quality_certificate_profile: '质量证明文件解析场景',
  quality_certificate: '质量证明文件',
  ndt_report: 'NDT 检测报告',
  ndt_rt_table_profile: '射线检测表格解析场景',
  FIELD_LOW_CONFIDENCE: '字段识别置信度低',
  get_extracted_fields: '读取抽取字段',
  get_node_requirements: '读取节点资料要求',
  get_document_ocr_result: '读取 OCR 结果',
  get_ocr_result: '读取 OCR 结果',
  get_project_context: '读取项目上下文',
  graph_runner: '编排执行器',
  hybrid_rag: '混合检索',
  intake_agent: '资料收件员',
  inspection_kb: '监检知识库',
  'inspection_kb@1.0.0': '监检知识库 1.0.0',
  knowledge_rule_service: '知识规则服务',
  knowledge_retrieval_agent: '知识依据检索员',
  langgraph_postgres: 'LangGraph + PostgreSQL 检查点',
  load_context: '读取项目上下文',
  load_document_context: '加载资料上下文',
  load_ocr_result: '读取 OCR 结果',
  llm_generate_findings: '大模型生成审查草稿',
  llm_review: '生成审查草稿',
  material_review: '材料资料审查',
  material_review_v1: '材料资料审查流程',
  ndt_rt_report_v1: '射线检测报告解析配置',
  ocr_agent: 'OCR 识别员',
  ocr_result_cache: 'OCR 结果缓存',
  opencv_table_grid_subprocess: '表格网格识别子进程',
  overall: '全部场景',
  paddle_ocr_v6: 'PaddleOCR 文本识别',
  paddleocr_vl_1_6: 'PaddleOCR-VL 复杂文档复核',
  paddlex_seal: 'PaddleX 印章识别',
  'paddlex-seal-model': '印章识别模型',
  pp_structure_v3: 'PP-Structure 表格版面识别',
  pageindex: '章节溯源',
  pageindex_tree_search: '章节树检索',
  langgraph: 'Agent 编排图',
  litellm: 'LiteLLM 模型网关',
  low_confidence_field: '字段识别置信度低',
  LOW_CONFIDENCE: '低置信内容',
  BBOX_SHIFT: '证据框位置偏移',
  TABLE_STRUCTURE_LOW_CONFIDENCE: '表格结构置信度低',
  SEAL_TEXT_LOW_CONFIDENCE: '印章文字置信度低',
  MISSING_FIELD_LABELS: '缺少字段标签',
  MISSING_SEAL_BBOX: '缺少印章证据框',
  MISSING_TABLE_CELL_LABELS: '缺少表格单元格标注',
  piping_characteristic_list_v1: '管道特性表解析配置',
  piping_table_profile: '管道表格解析场景',
  postgres: 'PostgreSQL 持久化',
  quality_certificate_v1: '质量证明文件解析配置',
  quality_gate: '质量门禁',
  qualification_certificate_v1: '资质证书解析配置',
  'postgres-checkpointer': 'PostgreSQL 检查点',
  postgres_checkpointer: 'PostgreSQL 检查点',
  project_control_agent: '项目管控助手',
  pymupdf_text_layer: 'PDF 文本层解析',
  retrieve_knowledge: '检索知识依据',
  report_agent: '报告草稿员',
  review_orchestrator_service: '审查编排服务',
  review_large: '审查大模型',
  'review-large': '审查大模型',
  review_prompt: '审查提示词',
  'review_prompt@2.1.0': '审查提示词 2.1.0',
  review_small: '审查小模型',
  'review-small': '审查小模型',
  risk_review_agent: '风险识别员',
  rule_check_agent: '规则核对员',
  rule_checking: '规则校验中',
  run_rule_checks: '执行规则检查',
  run_rule_engine: '执行规则引擎',
  human_confirmation_required: '需要人工确认',
  seal_consistency_warning: '签章一致性风险',
  sealNameAccuracy: '印章名称准确率',
  seal_recognition: '印章识别',
  seal_text_profile: '印章文字解析配置',
  seal_text_profile_v1: '印章文字解析配置',
  SignalWaiting: '等待人工信号',
  search_knowledge_base: '检索知识库',
  table_structure: '表格结构',
  tableCellAccuracy: '表格单元格准确率',
  validate_output: '校验证据与依据',
  vector: '资料向量化',
  vector_search: '向量检索',
  visual_seal_candidate_subprocess: '印章候选区域检测子进程',
  waiting_human_review: '等待人工复核',
  WorkflowStarted: '工作流已启动'
}

export const ruleCodeLabels: Record<string, string> = {
  EVIDENCE_BBOX_REQUIRED: '证据框必须可定位',
  FIELD_LOW_CONFIDENCE: '字段识别置信度低',
  MISSING_FIELD_LABELS: '缺少字段标签',
  MISSING_SEAL_BBOX: '缺少印章证据框',
  MISSING_TABLE_CELL_LABELS: '缺少表格单元格标注',
  OCR_FIELD_CONF_002: 'OCR 字段置信度过低',
  QC_CERT_FIELD_003: '质量证明文件缺少关键字段',
  SEAL_REQUIRED_001: '资料必须有有效签章',
  SEAL_TEXT_LOW_CONFIDENCE: '印章文字置信度低',
  TABLE_STRUCTURE_LOW_CONFIDENCE: '表格结构置信度低',
  WELDER_CERT_001: '焊工资格证必须上传'
}

/**
 * 证据与结构校验的失败码。这些码会以「待核对」的形式直接出现在结论里，
 * 2026-09-11 生产计数：EVIDENCE_REFS_MISSING 230 次、EVIDENCE_FILE_OUTSIDE_NODE 53 次、
 * EVIDENCE_QUOTE_NOT_VERBATIM 12 次——监检人员看到的就是这一串英文大写。
 * 取值来自 libs/project_analysis/validation.py 与 libs/review_grounding.py。
 */
export const evidenceIssueLabels: Record<string, string> = {
  EVIDENCE_FILE_OUTSIDE_NODE: '引用的文件不属于本节点',
  EVIDENCE_FILE_NOT_IN_CORPUS: '引用的文件不在本次资料范围内',
  EVIDENCE_METADATA_MISSING: '证据缺少页码或位置信息',
  EVIDENCE_QUOTE_NOT_VERBATIM: '引用原文与资料不一致',
  EVIDENCE_REFS_MISSING: '这条结论没有给出证据出处',
  EVIDENCE_REF_INVALID: '证据引用格式不合法',
  EVIDENCE_REF_INVALID_TYPE: '证据引用格式不合法',
  EVIDENCE_REF_LINK_NOT_FOUND: '证据链接已失效',
  EVIDENCE_REF_CROSS_DOCUMENT: '证据跨到了另一份文件',
  EVIDENCE_REF_PAGE_INVALID: '证据页码不合法',
  EVIDENCE_REF_BBOX_INVALID: '证据位置框不合法',
  EVIDENCE_REF_POSITION_INVALID: '证据位置不合法',
  FINDING_TYPE_MISSING: '发现缺少类型',
  FINDING_SEVERITY_INVALID: '发现的严重度取值不合法',
  FINDING_TITLE_MISSING: '发现缺少标题',
  FINDING_DESCRIPTION_MISSING: '发现缺少说明',
  RULE_REF_SOURCE_INVALID: '规则出处不合法',
  RULE_REF_NOT_VERBATIM: '规则原文与标准不一致',
  RULE_REF_INVALID_TYPE: '规则引用格式不合法',
  PURE_LLM_REVIEW_NO_OCR_EVIDENCE: '本次复核没有可引用的 OCR 证据',
  UNSUPPORTED_CLAIM: '结论没有证据支持',
  UNSUPPORTED_LLM_CLAIM: '模型结论没有证据支持',
  INSUFFICIENT_OCR_EVIDENCE: 'OCR 证据不足以支撑自动结论',
  LOW_CONFIDENCE_OCR_EVIDENCE: 'OCR 证据置信度低',
  OCR_GROUNDING_DOCUMENT_VERSION_MISSING: '缺少文件版本，无法定位证据',
  OCR_GROUNDING_TEXT_MISSING: '没有可用的 OCR 文字',
  OCR_GROUNDING_EVIDENCE_LINK_MISSING: '没有按文件划定的证据链接',
  OCR_GROUNDING_LOW_CONFIDENCE: 'OCR 识别置信度低',
  OCR_GROUNDING_POSITION_MISSING: 'OCR 结果缺少位置信息',
  OCR_GROUNDING_TABLE_CONTENT_MISSING: '表格内容未识别出来',
  OCR_GROUNDING_SEAL_TEXT_RISK: '印章文字识别存疑',
  OCR_GROUNDING_QUALITY_FLAGS: 'OCR 质量存在告警'
}

/**
 * 确定性工具报的「为什么不是通过」。取值来自 libs/review_orchestrator/deterministic_tools.py
 * 各工具 facts.reason 与 aggregate_tool_results；2026-09-12 七项目扫描按出现次数排。
 * 认不出的码按 `_missing` / `_not_configured` 后缀兜底成中文，再不行原样显示。
 */
export const checkReasonLabels: Record<string, string> = {
  'checkCount=0': '规则跑了，但节点没有可检的资料',
  provider_confidence_unavailable: '抽取引擎没给置信度，需人工核对引文',
  requiredFields_not_configured: '规则未配置必填字段清单',
  sampling_parameters_missing: '缺少抽检比例 / 抽样参数',
  R19_SEMANTIC_JUDGMENT_MISSING: '需要语义判断，确定性工具不判',
  validUntil_and_periodStart_and_periodEnd_missing: '缺少证书有效期与施工起止日期',
  periodStart_and_periodEnd_missing: '项目未填施工起止日期',
  validUntil_missing: '未抽到证书有效期',
  r15_design_items_missing: '未抽到设计文件条目',
  required_signature_roles_missing: '缺少必要签字角色',
  pwht_weld_items_missing: '未抽到热处理焊口记录',
  welder_qualifications_and_welding_work_records_missing: '缺少焊工资格与施焊记录',
  welder_qualifications_missing: '未抽到焊工资格项目',
  welding_work_records_missing: '缺少施焊记录',
  required_document_types_missing: '缺少必需的资料类型',
  condition_missing: '缺少判定条件',
  required_pipeline_grades_missing: '未抽到管道级别（GC1/GC2…）',
  fewer_than_two_comparable_values: '可比的值不足两处',
  no_certificates: '未抽到证书',
  pipe_fit_up_records_missing: '缺少管道组对记录',
  welding_records_missing: '缺少焊接记录',
  repair_occurrence_or_records_missing: '缺少返修发生记录',
  license_list_not_attempted: '公示平台未取到证书清单',
  tsg_z6002_2026_effective_profile_not_verified: 'TSG Z6002-2026 生效口径未核',
  unrecognized_code_shape: '项目代号格式无法识别',
  coverage_code_not_in_profile: '项目代号不在覆盖表里'
}

const REASON_SUFFIX_LABELS: Array<[RegExp, (stem: string) => string]> = [
  [/^(.+)_and_(.+)_missing$/, (stem) => `缺少 ${stem.replace(/_and_/g, '、')}`],
  [/^(.+)_missing$/, (stem) => `缺少 ${stem}`],
  [/^(.+)_not_configured$/, (stem) => `未配置 ${stem}`],
  [/^(.+)_not_verified$/, (stem) => `${stem} 未核验`]
]

export const friendlyCheckReason = (value?: string | null) => {
  const code = String(value || '').trim()
  if (!code) return ''
  if (checkReasonLabels[code]) return checkReasonLabels[code]
  for (const [pattern, render] of REASON_SUFFIX_LABELS) {
    const match = code.match(pattern)
    if (match) return render(friendlyFieldLabel(match[1]) || match[1])
  }
  return code
}

/**
 * 逐条检查码 → 人话。码是工具里 check(code, …) 写死的；带证书编号前缀的
 * （`TS1844171-2028:scope_covers_required`）先剥前缀。
 */
export const checkCodeLabels: Record<string, string> = {
  all_values_equal: '三处单位名一致',
  not_expired_on_reference_date: '证书在参考日未过期',
  scope_covers_required: '许可范围覆盖所需级别',
  valid_from_before_period_start: '生效日早于开工',
  valid_until_after_period_end: '有效期晚于完工',
  report_standard_present: '报告写明执行标准',
  report_result_accepted: '报告结论合格',
  references_exist: '证据引用存在',
  locator_complete: '证据定位完整（页码+位置或引文）',
  confidence: '置信度达标',
  not_conflicted: '证据无冲突'
}

export const friendlyCheckCode = (value?: string | null) => {
  const raw = String(value || '').trim()
  if (!raw) return ''
  const [, prefix, code] = raw.match(/^(.*?):([^:]+)$/) || [null, '', raw]
  const scope = code.match(/^scope_covers_(.+)$/)
  const base =
    checkCodeLabels[code] ||
    (scope ? `许可范围覆盖 ${scope[1]}` : '') ||
    code.replace(/^fact_\d+_/, (m) => `事实${m.replace(/\D/g, '')}·`)
  const factMatch = code.match(/^fact_(\d+)_(.+)$/)
  const label = factMatch
    ? `事实 ${factMatch[1]}：${checkCodeLabels[factMatch[2]] || factMatch[2]}`
    : base
  return prefix ? `${prefix}：${label}` : label
}

export const friendlyEvidenceIssue = (value?: string | null) => {
  const code = String(value || '').trim()
  return code ? evidenceIssueLabels[code] || '' : ''
}

/**
 * 模型角色别名。库里存的是路由键（libs/qwen_runtime.MODEL_ROLE_ALIASES），
 * 界面上直接印「review-chat」对监检人员没有意义。认不出的别名原样显示——
 * 那多半是环境里换了模型，原样显示比猜一个中文名诚实。
 */
export const modelAliasLabels: Record<string, string> = {
  'review-chat': '审查模型',
  'project-review-large': '全工程分析模型',
  'default-chat': '通用模型',
  'compare-fast': '快速比对模型',
  'qwen-vision-review': '视觉审查模型',
  'document-classifier': '资料分类模型'
}

export const friendlyModelAlias = (value?: string | null) => {
  const alias = String(value || '').trim()
  return alias ? modelAliasLabels[alias] || alias : ''
}

export const fieldLabelMap: Record<string, string> = {
  agentId: 'AI 员工',
  agentSopCount: 'AI 员工 SOP',
  caseId: '样本编号',
  checkpointer: '检查点',
  collectionStatus: '采集状态',
  currentStep: '当前步骤',
  currentOcrStatus: 'OCR 文字识别',
  eventType: '事件类型',
  findingType: '问题类型',
  graphEngine: '内层编排',
  material_grade: '材料牌号',
  weld_no: '焊口编号',
  report_no: '报告编号',
  certificate_no: '证书编号',
  batch_no: '炉批号',
  manufacturer: '生产厂家',
  project_name: '项目名称',
  detection_date: '检测日期',
  inspection_unit: '检测单位',
  seal_name: '印章名称',
  seal_type: '印章类型',
  valid_until: '有效期',
  conclusion: '结论',
  jobId: '任务编号',
  nodeKey: '节点键',
  parseResultId: '解析结果编号',
  profileId: '解析配置',
  prompt: '提示词',
  promptVersion: '提示词版本',
  retrievalHitCount: '检索命中',
  reviewRunId: '审查任务编号',
  ruleCode: '规则',
  runId: '运行编号',
  taskId: '任务编号',
  tokenCount: 'Token 用量',
  toolName: '工具名称',
  workflowId: '工作流编号'
}

export const friendlyReviewStatus = (status?: string | null) => {
  if (!status) return '未知状态'
  return statusLabelMap[status] || status
}

export const friendlyTechTerm = (value?: string | null) => {
  if (!value) return '未返回'
  return techTermLabels[value] || statusLabelMap[value] || ruleCodeLabels[value] || value
}

export const friendlyRuleCode = (value?: string | null, options: { keepCode?: boolean } = {}) => {
  if (!value) return '未返回'
  const label = ruleCodeLabels[value] || techTermLabels[value] || statusLabelMap[value]
  if (!label) return value
  return options.keepCode === true ? `${label}（${value}）` : label
}

export const friendlyFieldLabel = (value?: string | null) => {
  if (!value) return '字段'
  return fieldLabelMap[value] || techTermLabels[value] || value
}

export const friendlyToken = (value?: string | null, options: { keepCode?: boolean } = {}) => {
  if (!value) return '未返回'
  const label = ruleCodeLabels[value] || techTermLabels[value] || statusLabelMap[value]
  if (!label) return value
  return options.keepCode === true ? `${label}（${value}）` : label
}

/**
 * 资料类型代号 → 资料名。取值是后端 materialTypeCode / certificateType
 * （welder_certificate、design_license…），界面上直接印代号没人看得懂
 * （2026-09-12 用户实测反馈：证照核验卡头上写着「welder_certificate」）。
 * 原来这张表埋在 Workbench.vue 里只给一处用，现在挪出来共用。
 */
export const materialTypeLabels: Record<string, string> = {
  installation_license: '安装单位许可证',
  ndt_agency_approval: '无损检测机构核准证',
  ndt_personnel_certificate: '无损检测人员资格证',
  valve_construction_record: '阀门施工记录',
  pipe_fit_up_record: '管道组对记录',
  weld_appearance_record: '焊接接头外观检查记录',
  heat_treatment_instrument: '热处理测温仪表记录',
  temperature_point_layout: '测温点布置图',
  hardness_report: '硬度检测报告',
  consumable_receipt: '焊材入库/领用记录',
  consumable_management: '焊材管理记录',
  welding_consumable_certificate: '焊接材料质量证明文件',
  pipeline_summary: '管线汇总表',
  wps: '焊接作业指导书 WPS',
  pqr: '焊接工艺评定报告 PQR',
  generic_review_material: '审查资料',
  design_license: '设计单位许可证',
  construction_license: '施工单位安装许可证',
  manufacturing_license: '制造单位许可证',
  ndt_org_certificate: '无损检测机构核准证',
  ndt_person_certificate: '无损检测人员资格证和执业注册证',
  design_document: '设计文件',
  drawing_review_record: '施工图审查手续',
  calculation_report: '强度计算书或应力分析报告',
  design_change_document: '设计变更和书面批准文件',
  construction_organization_design: '施工组织设计',
  construction_schedule: '施工计划工期文件',
  quality_certificate: '产品质量证明书',
  manufacturing_supervision_certificate: '制造监督检验证书',
  type_test_report: '型式试验证书或型式试验报告',
  factory_inspection_report: '出厂检验报告',
  overseas_material_certificate: '境外制造或境外牌号材料证明文件',
  acceptance_witness_record: '到货验收见证资料',
  material_retest_report: '材料复验报告',
  material_mark_transfer_record: '材料标志移植记录',
  material_substitution_approval: '材料代用批准文件',
  technical_review_approval: '技术评审和批准手续',
  valve_test_report: '阀门施工资料和耐压试验报告',
  welder_certificate: '焊工资格证',
  welder_roster: '焊工名册',
  wps_pqr: '焊接工艺评定报告和焊接作业指导书',
  welding_material_certificate: '焊接材料质量证明文件',
  welding_material_management_record: '焊材验收保管发放回收记录',
  welding_record: '焊接记录和焊缝标识资料',
  weld_repair_record: '焊缝返修记录',
  heat_treatment_procedure: '焊后热处理工艺文件',
  heat_treatment_record: '热处理记录、曲线和硬度检测报告',
  instrument_calibration_certificate: '仪表检定或校准证书',
  ndt_plan: '无损检测方案',
  ndt_procedure: '无损检测工艺文件',
  ndt_report: '无损检测报告',
  radiographic_film: '射线检测底片',
  anticorrosion_insulation_material_certificate: '防腐及保温材料质量证明文件',
  anticorrosion_insulation_record: '防腐补口补伤和保温施工记录',
  cathodic_protection_record: '阴极保护和杂散电流排流装置资料',
  grounding_test_record: '静电接地施工和测试记录',
  installation_record: '管道安装和现场制作记录',
  safety_accessory_record: '安全附件安装、校验或性能测试资料',
  pressure_test_plan: '耐压试验方案',
  pressure_test_report: '耐压试验记录或报告',
  leakage_test_report: '泄漏试验记录或报告',
  purge_cleaning_record: '吹扫清洗方案和记录',
  field_photo: '现场照片、底片或实物核验证据',
  quality_system_document: '质量保证体系文件和实施记录',
  external_query_screenshot: '外部查询截图'
}

export const friendlyMaterialType = (value?: string | null) => {
  const code = String(value || '').trim()
  if (!code) return ''
  return materialTypeLabels[code] || code
}
