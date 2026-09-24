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
  WELDER_CERT_001: '焊工资格证必须上传',
  // 规则键（rule_versions.ruleKey），会以「规则依据」的形式印在发现卡上
  // （2026-09-13 用户实测：`welder-qualification` 原样露出来）。
  'welder-qualification': '焊工资格（TSG Z6002）',
  'ndt-report': '无损检测记录与报告',
  // 其它业务包（合规审计、设备检验）的规则键
  'control-evidence-consistency': '控制措施与证据一致性',
  'maintenance-completeness': '维护保养记录完整性',
  'policy-completeness': '制度文件完整性',
  'safety-device-evidence': '安全附件证据',
  AI_RUN_REVIEW_CONTEXT: '审查上下文校验',
  PIPE_LIST_FIELD_CONFIDENCE: '管道特性表字段置信度',
  SEAL_REQUIRED_AND_READABLE: '印章须存在且可辨认'
}

/**
 * 69 条监检项规则的键是 `engineering-inspection-rNN`：NN 就是监检项目表的序号，
 * 逐条列 69 行没意义（序号本身就是监检认的东西），按规律翻。
 */
const NODE_RULE_KEY = /^engineering-inspection-r(\d{1,2})$/

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
  // 这条以 r24_ 开头但不是规则前缀，剥前缀会把它拆坏，直接给整条。
  r24_or_r25_linked_result_missing: '缺少节点 24 或 25 的关联结果',
  'checkCount=0': '规则跑了，但节点没有可检的资料',
  // 证照核验失败时报的是「哪条检查没过」（deterministic_tools._CERTIFICATE_FAILURE_REASONS）。
  // 2026-09-13 之前这个工具不报原因，界面上就显示同一项里别的工具报的数据缺口。
  certificate_holder_registry_mismatch: '证件号在平台登记的持证人与资料上的不是同一个',
  certificate_holder_project_mismatch: '持证单位与本工程的责任单位不一致',
  certificate_scope_not_covered: '许可范围不覆盖本工程要求的管道级别',
  certificate_expires_before_period_end: '证书有效期早于施工结束日期',
  certificate_issued_after_period_start: '证书生效日期晚于施工开始日期',
  certificate_expired_on_reference_date: '证书已过期',
  certificate_valid_until_missing: '证书没有有效期至',
  certificate_holder_missing: '证书没有持证主体',
  certificate_scope_missing: '证书没有许可范围',
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

/**
 * 原因码是「词根 + 后缀」拼出来的（`consumable_certificate_or_design_requirement_missing`），
 * 全库 295 个、还会长。逐条列表跟不上，所以按词翻译再按后缀组框：
 * 词典覆盖 190 个业务词，认不出的词**原样保留**——宁可露出英文，也不硬翻出一个错意思。
 */
const REASON_WORDS: Record<string, string> = {
  accuracy: '精度',
  actual: '实际',
  allowed: '允许',
  and: '与',
  approved: '已批准',
  as: '按',
  at: '',
  available: '可用',
  before: '前',
  built: '建',
  calibration: '校准',
  colorant: '着色剂',
  controlled: '受控',
  covers: '覆盖',
  dial: '表盘',
  exception: '例外',
  exemption: '免做',
  foreign: '境外',
  form: '格式',
  from: '起',
  frozen: '已固化',
  gate: '闸阀',
  has: '有',
  hold: '保压',
  identified: '已识别',
  increasing: '递增',
  increment: '增量',
  known: '已知',
  large: '大',
  least: '少',
  limits: '限值',
  matches: '一致',
  method: '方法',
  minimum: '下限',
  minutes: '分钟',
  most: '多',
  new: '新',
  nonconformance: '不符合项',
  not: '非',
  on: '于',
  or: '或',
  org: '单位',
  overseas: '境外',
  percent: '百分比',
  person: '人员',
  range: '范围',
  ratio: '比',
  recorded: '已记录',
  resolved: '已确定',
  role: '角色',
  route: '路径',
  safe: '安全',
  sample: '试样',
  technical: '技术',
  traceable: '可追溯',
  transferred: '已移植',
  unique: '唯一',
  until: '至',
  valid: '有效',
  test: '试验',
  checked: '核对',
  got: '得到',
  non: '非',
  boolean: '布尔',
  over: '超过',
  criteria: '判据',
  disabled: '停用',
  json: 'JSON',
  probe: '探针',
  transaction: '事务',
  hbw: '布氏硬度',
  second: '第二',
  r24: '节点24',
  r25: '节点25',
  mineru: 'MinerU',
  acceptance: '验收',
  activity: '活动',
  agencies: '机构',
  agency: '机构',
  angle: '角度',
  annex: '附录',
  appearance: '外观',
  application: '申请',
  applicability: '适用性',
  applicable: '适用',
  approval: '批准',
  archive: '归档',
  arrival: '到货',
  basis: '依据',
  batch: '批号',
  bevel: '坡口',
  bindings: '绑定',
  body: '正文',
  bonding: '粘接',
  business: '业务',
  calculation: '计算',
  candidates: '候选',
  cards: '卡片',
  case: '案例',
  cases: '案例',
  category: '类别',
  certificate: '证书',
  certificates: '证书',
  change: '变更',
  characteristic: '特性',
  checklist: '检查表',
  chemical: '化学',
  classification: '分类',
  clause: '条款',
  closure: '闭环',
  code: '代号',
  codes: '代号',
  collections: '集合',
  commissions: '委托',
  comparable: '可比',
  comparison: '比对',
  comparisons: '比对',
  complete: '完整',
  completion: '完成',
  component: '元件',
  composite: '复合',
  composition: '成分',
  conclusion: '结论',
  condition: '条件',
  conditional: '条件性',
  confidence: '置信度',
  configured: '配置',
  conflict: '冲突',
  construction: '施工',
  consumable: '焊材',
  content: '内容',
  continuity: '连续性',
  contract: '合同',
  control: '管理',
  conversion: '换算',
  copy: '复印件',
  count: '数量',
  coverage: '覆盖',
  covered: '覆盖',
  covering: '覆盖',
  curve: '曲线',
  cycle: '周期',
  data: '数据',
  date: '日期',
  dates: '日期',
  declared: '声明',
  defect: '缺陷',
  design: '设计',
  diameter: '管径',
  dimensions: '尺寸',
  disposition: '处置',
  document: '文件',
  documents: '文件',
  drawing: '图纸',
  dual: '双重',
  effective: '生效',
  event: '事件',
  events: '事件',
  evidence: '证据',
  expired: '超期',
  fact: '事实',
  facts: '事实',
  factory: '出厂',
  field: '字段',
  fields: '字段',
  film: '底片',
  fit: '组对',
  forced: '强力',
  formal: '正式',
  found: '找到',
  gap: '间隙',
  grade: '级别',
  handler: '经手人',
  handoff: '交接',
  hardness: '硬度',
  hash: '哈希',
  heat: '热',
  holding: '保温',
  human: '人工',
  id: '编号',
  identification: '标识',
  identity: '标识',
  image: '图像',
  impact: '冲击',
  impression: '印模',
  input: '输入',
  inputs: '输入',
  inspection: '检验',
  instrument: '仪表',
  inventory: '清单',
  invalid: '无效',
  issuer: '发证机关',
  item: '项',
  items: '项',
  jacket: '夹套',
  joint: '接头',
  latest: '最近一次',
  layout: '布置',
  license: '许可证',
  licenses: '许可证',
  limit: '限值',
  link: '关联',
  linked: '关联',
  links: '关联',
  location: '部位',
  lot: '批',
  lots: '批',
  management: '管理',
  manifest: '清单',
  manufacturer: '制造单位',
  manufacturing: '制造',
  mapping: '映射',
  mark: '标志',
  markdown: 'Markdown',
  match: '匹配',
  matching: '匹配',
  material: '材料',
  mechanical: '力学',
  members: '成员',
  methods: '方法',
  misalignment: '错边量',
  mtc: '质量证明书',
  name: '名称',
  names: '名称',
  ndt: '无损检测',
  necessary: '必要',
  node: '节点',
  number: '编号',
  numeric: '数值',
  object: '对象',
  occurrence: '发生情况',
  official: '官方',
  organization: '单位',
  origin: '来源',
  original: '原件',
  outside: '之外',
  page: '页',
  parameter: '参数',
  parameters: '参数',
  parent: '父级',
  payload: '载荷',
  period: '期间',
  personnel: '人员',
  photo: '照片',
  physical: '实物',
  pipe: '管子',
  pipeline: '管线',
  plan: '方案',
  planned: '计划',
  point: '测点',
  policy: '策略',
  positive: '肯定',
  pqr: '工艺评定报告',
  presence: '存在',
  present: '存在',
  pressure: '压力',
  previous: '上一个',
  procedure: '工艺',
  product: '产品',
  profile: '档案',
  progressive: '渐进',
  project: '项目',
  properties: '性能',
  provider: '引擎',
  pt: '渗透检测',
  pwht: '焊后热处理',
  qms: '质量管理体系',
  qualification: '评定',
  qualified: '已评定',
  quality: '质量',
  quotation: '引文',
  ranges: '范围',
  readings: '读数',
  record: '记录',
  records: '记录',
  reference: '引用',
  registry: '登记',
  reinforcement: '余高',
  reinspection: '复检',
  repair: '返修',
  repairs: '返修',
  repeat: '重复',
  report: '报告',
  reports: '报告',
  requirement: '要求',
  requirements: '要求',
  required: '必需',
  response: '响应',
  restored: '恢复',
  result: '结果',
  retest: '复验',
  review: '审查',
  roles: '角色',
  root: '根部',
  round: '轮次',
  rule: '规则',
  same: '同一',
  sampling: '抽样',
  scope: '范围',
  seal: '印章',
  seals: '印章',
  selected: '所选',
  sequence: '序号',
  serial: '序列号',
  shape: '格式',
  signature: '签字',
  signatures: '签字',
  size: '数量',
  source: '来源',
  special: '特殊',
  specific: '具体',
  specification: '规格',
  stage: '阶段',
  standard: '标准',
  start: '开始',
  status: '状态',
  steps: '步骤',
  stock: '库存',
  substitution: '代用',
  supervision: '监督检验',
  supplied: '提供',
  supplier: '供货方',
  supporting: '支撑',
  target: '目标',
  task: '任务',
  temperature: '温度',
  tested: '已试验',
  text: '文字',
  thickness: '厚度',
  time: '时间',
  token: '标记',
  trace: '追溯',
  traceability: '可追溯性',
  transfer: '移植',
  treatment: '处理',
  trigger: '触发',
  two: '两',
  type: '型式',
  types: '类型',
  unavailable: '不可用',
  undercut: '咬边',
  uniquely: '唯一',
  unrecognized: '无法识别',
  unsupported: '不支持',
  up: '',
  usage: '使用',
  use: '使用',
  value: '值',
  values: '值',
  valve: '阀门',
  verification: '核验',
  verified: '已核验',
  version: '版本',
  weld: '焊缝',
  welding: '焊接',
  width: '宽度',
  witness: '见证',
  work: '施焊',
  worker: '焊工',
  wps: '焊接工艺规程',
  written: '书面'
}

/** 后缀框架：`X_missing` → 缺少 X。 */
const REASON_FRAMES: Array<[string, (stem: string) => string]> = [
  ['_missing', (stem) => `缺少${stem}`],
  ['_not_applicable', (stem) => `${stem}不适用`],
  ['_not_verified', (stem) => `${stem}未核验`],
  ['_not_configured', (stem) => `未配置${stem}`],
  ['_not_found', (stem) => `未找到${stem}`],
  ['_not_met', (stem) => `${stem}不满足`],
  ['_not_indexed', (stem) => `${stem}未建索引`],
  ['_unresolved', (stem) => `${stem}未定`],
  ['_unknown', (stem) => `${stem}情况不明`],
  ['_undecidable', (stem) => `${stem}无法判定`],
  ['_mismatch', (stem) => `${stem}不一致`]
]

/** 词典拼不出正确说法的整段词根，在这里直译。 */
const REASON_STEMS: Record<string, string> = {
  // 检验服务接口（inspection_services）把判定结论本身当 reason 写出。
  evidence_insufficient: '证据不足',
  ocr_holder_unreliable: 'OCR 识别的持证单位名称不可靠',
  unsupported_scope_profile: '当前许可范围判定口径尚未支持',
  original_with_manufacturer_quality_seal: '原件带制造单位质量章',
  copy_with_dealer_and_handler_seals: '复印件带经销商与经手人签章',
  actual_material_usage: '实际材料用量',
  actual_or_qualified_thickness: '实际厚度或已评定厚度',
  boolean_field_got_non_boolean: '布尔字段收到了非布尔值',
  composite_applicability: '复合适用性判断',
  design_and_contract_valve_basis_not_checked: '未核对设计与合同的阀门依据',
  invalid_archive: '归档包无效',
  mineru_markdown: 'MinerU 解析出的 Markdown',
  node_rule_bindings: '节点规则绑定',
  non_hbw_conversion_evidence: '非布氏硬度换算依据',
  not_configured: '未配置',
  over_two_repairs_special_approval: '同一部位返修超两次的专项批准',
  path_not_declared_by_criteria: '该路径未在判定依据里声明',
  policy_disabled_or_trigger_not_configured: '策略已停用或触发条件未配置',
  pressure_test_value: '试验压力值',
  r24_or_r25_linked_result: '节点 24 或 25 的关联结果',
  response_not_json: '模型响应不是合法 JSON',
  second_stage_parent: '第二阶段的父级记录',
  technical_review_approval: '技术评审批准手续',
  technical_review: '技术评审',
  approval: '批准手续',
  transaction_probe_failed: '事务探针失败',
  type_test_conclusion: '型式试验结论',
  type_test_diameter_scope: '型式试验的管径范围',
  type_test_organization: '型式试验机构',
  type_test_pressure_scope: '型式试验的压力范围',
  type_test_report: '型式试验报告',
  type_test_report_number: '型式试验报告编号',
  type_test_scope_fields: '型式试验范围字段',
  type_test_specification_scope: '型式试验的规格范围',
  valve_test_lots: '阀门试验批',
  valve_test_record_facts: '阀门试验记录事实',
  not_applicable: '不适用',
  actual_work: '实际施焊记录',
  consumable_certificate: '焊材质量证明书',
  design_requirement: '设计要求',
  design_items: '设计条目',
  wps_pqr: '焊接工艺规程与评定报告',
  work_items: '施焊记录',
  welder_qualifications: '焊工合格项目',
  welding_work_records: '施焊记录',
  license_scopes: '许可范围',
  required_pipeline_grades: '所需管道级别',
  pipe_fit_up_records: '管道组对记录',
  pwht_weld_items: '需热处理的焊口',
  sampling_parameters: '抽检比例与抽样参数',
  required_fields: '必填字段',
  required_signature_roles: '必需的签字角色',
  required_document_types: '必需的资料类型',
  provider_confidence_unavailable: '抽取引擎没给置信度',
  fewer_than_two_comparable_values: '可比的值不足两处',
  unrecognized_code_shape: '项目代号格式无法识别',
  coverage_code_not_in_profile: '项目代号不在覆盖表里',
  no_supplied_evidence: '没有提供任何证据',
  not_present_in_supplied_evidence: '所给证据里没有这一项',
  quotation_not_found_in_page: '引文在该页找不到',
  value_without_quotation: '给了值却没有引文',
  positive_claim_without_specific_evidence_token: '下了肯定结论却没有具体证据',
  evidence_outside_selected_documents: '证据不在本次所选资料范围内',
  seal_text_not_a_name: '印章文字不像单位名称',
  work_item_coverage_undecidable: '施焊记录覆盖情况无法判定',
  special_joint_qualification_requires_annex_review: '特殊接头评定需按附录人工复核',
  closure_does_not_uniquely_match_latest_round: '闭环记录对不上最近一轮返修',
  repair_basis_or_time_not_aligned_with_defect: '返修依据或时间与缺陷对不上',
  design_contract_valve_standard_conflict: '设计与合同的阀门标准冲突',
  unsupported_valve_test_standard: '不支持的阀门试验标准',
  latest_reinspection_evaluated: '已按最近一次复检判定',
  formal_review_waiting_human_review: '正式审查等待人工结论',
  formal_review_failed_restored_previous_status: '正式审查未通过，已恢复原状态'
}

/**
 * 检查项的期望值/实际值里也会出现 snake_case 枚举
 * （`original_with_manufacturer_quality_seal_or_copy_with_dealer_and_handler_seals`，
 * 2026-09-13 线上巡检在节点 16 抓到）。按词典翻，翻不动就原样。
 */
/**
 * 检查项的期望/实际值里也会出现判定结论本身
 * （`uploaded_drawing_catalog` 的 actual 是一串已上传的资料类型码，
 *  锚定门的 actual 是 `evidence_insufficient`）。
 */
const OUTCOME_VALUE_LABELS: Record<string, string> = {
  evidence_insufficient: '证据不足',
  human_review_required: '需人工判断',
  not_applicable: '不适用',
  passed: '通过'
}

export const friendlyEnumValue = (value?: string | null) => {
  const text = String(value || '').trim()
  if (!text || !/^[a-z][a-z0-9_]{5,}$/.test(text)) return text
  if (OUTCOME_VALUE_LABELS[text]) return OUTCOME_VALUE_LABELS[text]
  if (materialTypeLabels[text]) return materialTypeLabels[text]
  if (REASON_STEMS[text]) return REASON_STEMS[text]
  // 先只按 `_or_` 切，每段先整段查表——否则 `_and_` 会把
  // 「copy_with_dealer_and_handler_seals」这种整词也切开（2026-09-13 实测）。
  const parts = text.split('_or_')
  const translated = parts.map((part) => {
    if (REASON_STEMS[part]) return REASON_STEMS[part]
    const pieces = part.split('_and_')
    const inner = pieces.map((piece) => REASON_STEMS[piece] || translateStem(piece))
    if (inner.some((piece, index) => piece === pieces[index] && !REASON_STEMS[pieces[index]])) {
      return part
    }
    return inner.join('且')
  })
  if (translated.some((part, index) => part === parts[index] && !REASON_STEMS[parts[index]])) {
    return text
  }
  return translated.join('，或')
}

const translateStem = (stem: string): string => {
  if (REASON_STEMS[stem]) return REASON_STEMS[stem]
  const words = stem.split('_').filter(Boolean)
  const parts = words.map((word) => REASON_WORDS[word])
  // 有一个词不认识就整段保留原文：拼一半中文一半英文比原样更难读，也容易读出错意思。
  if (parts.some((part) => part === undefined)) return stem
  return parts.join('')
}

export const friendlyCheckReason = (value?: string | null) => {
  const code = String(value || '').trim()
  if (!code) return ''
  if (checkReasonLabels[code]) return checkReasonLabels[code]
  const withoutRule = code.replace(/^r\d+_/, '')
  if (REASON_STEMS[withoutRule]) return REASON_STEMS[withoutRule]
  for (const [suffix, frame] of REASON_FRAMES) {
    if (!withoutRule.endsWith(suffix)) continue
    const stem = withoutRule.slice(0, -suffix.length)
    // 整段词根优先：`actual_or_qualified_thickness` 拆开翻会变成「实际 或 已评定厚度」。
    if (REASON_STEMS[stem]) return frame(REASON_STEMS[stem])
    const parts = stem.split(/_or_|_and_/)
    const joiners = [...stem.matchAll(/_or_|_and_/g)].map((match) =>
      match[0] === '_or_' ? '或' : '与'
    )
    const translated = parts.map(translateStem)
    if (translated.some((part, index) => part === parts[index] && !REASON_STEMS[parts[index]])) {
      // 有认不出的部分：给出框架但保留原文，别假装翻译完了
      return frame(parts.join(joiners[0] === '或' ? ' 或 ' : ' 与 '))
    }
    return frame(
      translated.reduce((text, part, index) => text + (index ? joiners[index - 1] : '') + part, '')
    )
  }
  return code
}

/**
 * 逐条检查码 → 人话。码是工具里 check(code, …) 写死的；带证书编号前缀的
 * （`TS1844171-2028:scope_covers_required`）先剥前缀。
 */
export const checkCodeLabels: Record<string, string> = {
  r14_applicability_known: 'R14 适用性已判明',
  hold_at_least_3_minutes: '保压不少于 3 分钟',
  increment_at_most_10_percent: '每级增量不超过 10%',
  holder_matches_project: '持证单位与项目单位一致',
  holder_ocr_reliable: 'OCR 识别的持证单位名称可信',
  holder_matches_registry: '持证人与平台登记一致',
  holder_present: '识别到持证主体',
  valid_until_present: '识别到有效期',
  scope_present: '识别到许可范围',
  all_approval_codes_decoded: '全部审批代号可解析',
  all_codes_decoded: '全部项目代号可解析',
  all_special_material_types_sampled: '特殊材料全部抽检到',
  ambient_temperature_minimum: '环境温度不低于下限',
  ambient_temperature_present: '记录了环境温度',
  applicable_standard_supported: '执行标准在支持范围内',
  at_least_one_gauge_at_highest_point: '最高点至少一块压力表',
  body_uploaded: '正文已上传',
  design_and_contract_basis_consistent: '设计与合同依据一致',
  design_reply_present: '有设计回复',
  drawing_version_consistent: '图纸版本一致',
  factory_records_traceable: '出厂记录可追溯',
  factory_test_each_valve: '阀门逐台出厂试验',
  gas_first_step_50_percent: '气压试验首级为 50%',
  gas_first_step_hold_at_least_3_minutes: '气压首级保压不少于 3 分钟',
  gas_last_step_reaches_test_pressure: '气压末级达到试验压力',
  gas_maximum_test_pressure: '气压试验压力不超上限',
  gas_minimum_test_pressure: '气压试验压力不低于下限',
  gas_pressure_steps_complete: '气压升压级次完整',
  gauge_count_at_least_two: '压力表不少于两块',
  implemented_substitution_record_present: '有代用实施记录',
  liquid_minimum_test_pressure: '液压试验压力不低于下限',
  medium_temperature_minimum: '试验介质温度不低于下限',
  medium_temperature_present: '记录了介质温度',
  organization_name_matches: '单位名称一致',
  owner_approved_exemption: '建设单位批准的免做',
  pressure_hold_at_least_10_minutes: '保压不少于 10 分钟',
  project_name_matches: '项目名称一致',
  review_before_construction: '施工前完成审查',
  sample_count_satisfies_requirement: '抽样数量满足要求',
  sample_not_larger_than_population: '抽样数不超过总体',
  seal_or_signature_present: '有签章或签字',
  selected_ids_match_sample_count: '所选编号数与抽样数一致',
  temperature_point_layout_present: '有测温点布置',
  test_medium_allowed: '试验介质允许',
  test_medium_present: '记录了试验介质',
  test_pressure_within_component_limit: '试验压力不超元件承压',
  test_result_accepted: '试验结论合格',
  transfer_record_present: '有标志移植记录',
  valid_from_covers_period_start: '生效日期早于开工',
  valid_until_covers_later_construction_end: '有效期覆盖延后的完工日期',
  valid_until_covers_period_end: '有效期覆盖完工日期',
  valve_test_result_accepted: '阀门试验结论合格',
  witness_type_accepted: '见证方式符合要求',
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

/** 带序号的检查码主体：`component_3_batch_traceable` 里的 component。 */
const CHECK_SUBJECTS: Record<string, string> = {
  acceptance: '验收',
  agency: '机构',
  appearance: '外观',
  certificate: '证书',
  comparison: '比对',
  component: '元件',
  consumable: '焊材',
  document: '文件',
  fact: '事实',
  film: '底片',
  fit_up: '组对',
  gas_step: '气压级',
  gauge: '压力表',
  grade: '级别',
  instrument: '仪表',
  item: '项',
  lot: '批',
  method: '方法',
  nonconformance: '不符合项',
  parseable: '可解析项',
  plan: '方案',
  registry: '登记',
  repair: '返修',
  report: '报告',
  required: '必需项',
  scope: '范围',
  scope_covers: '范围覆盖',
  signature: '签字',
  substitution: '代用',
  transfer: '移植',
  uploaded: '已上传项',
  valve: '阀门',
  weld: '焊缝',
  welding_record: '焊接记录',
  work: '施焊',
  work_item: '施焊项'
}

/** `component_3_batch_traceable` → 「元件 3：批号可追溯」。认不出的部分原样保留。 */
const indexedCheckLabel = (code: string): string => {
  const match = code.match(/^([a-z][a-z0-9_]*?)_(\d+)(?:_([a-z0-9_]+))?$/)
  if (!match) return ''
  const [, subject, index, rest] = match
  const subjectLabel = CHECK_SUBJECTS[subject] || REASON_WORDS[subject]
  if (!subjectLabel) return ''
  if (!rest) return `${subjectLabel} ${index}`
  const restLabel = checkCodeLabels[rest] || translateStem(rest)
  return `${subjectLabel} ${index}：${restLabel === rest ? rest : restLabel}`
}

/**
 * 后端有五族检查码是拼出来的，不是字面量，逐条写词典追不上
 * （business_tools.py：`uploaded_{文档类型}`、`required_{事实路径}`、`grade_{级别}`、
 * `{设计域}_{事实路径}`、`{设计域}_standard_ref_{序号}`）。
 * 2026-09-13 线上审计：207 个生产节点包里这五族占了未翻译检查码的 59 种中的 55 种。
 * 下面按族给规则，拼不出来的仍旧原样显示——半中半英比原文更难读。
 */

/** `uploaded_pipeline_data_sheet`：后缀是资料类型码，用资料词典给正式名称，比逐词拼准。 */
const DOCUMENT_CHECK_FRAMES: Array<[RegExp, (name: string) => string]> = [
  [/^uploaded_(.+)$/, (name) => `已上传${name}`],
  [/^parseable_(.+)$/, (name) => `${name}可解析`]
]

/** 设计专项要求的四个域（evaluate_design_special_requirements）。 */
const DESIGN_DOMAIN_LABELS: Record<string, string> = {
  corrosion: '防腐蚀',
  leaktest: '泄漏性试验',
  ndt: '无损检测',
  pressuretest: '压力试验'
}

/**
 * 域后面那一截：可能是事实路径（`requirements.method` 压平成 `requirements_method`），
 * 也可能是业务包里的规则码（`acceptance_level_specified`）。
 */
const DESIGN_DOMAIN_SUFFIXES: Record<string, string> = {
  acceptance_level_specified: '已明确合格级别',
  coverage_specified: '已明确检测比例',
  method_specified: '已明确检测方法',
  protection_method_specified: '已明确防护方法',
  requirements_acceptancecriteria: '要求·合格标准',
  requirements_coverage: '要求·检测比例',
  requirements_method: '要求·方法',
  requirements_protectionmethod: '要求·防护方法',
  requirements_testpressure: '要求·试验压力',
  specified: '设计是否提出要求',
  test_pressure_specified: '已明确试验压力'
}

/**
 * 冻结域工具（frozen_domain_checks.py）的三种「没收到入参」检查码，
 * 形如 `r46_cathodic_scope_missing`。注意 scope 指的是**审查对象范围**（projectId 等），
 * 不是「阴极保护的范围」——按字面逐词翻会翻反意思。
 */
const FROZEN_DOMAIN_GAPS: Record<string, string> = {
  domains_missing: '缺少要核的专业域',
  scope_missing: '缺少审查对象范围信息',
  standard_rules_missing: '缺少固化的标准规则',
  applicability_missing: '缺少适用性判断依据'
}

/** `r46_cathodic_scope_missing` 里的 `cathodic`：这条检查属于哪个专业。 */
const FROZEN_DOMAIN_NAMES: Record<string, string> = {
  blowing: '吹扫',
  cathodic: '阴极保护',
  certificate: '合格证',
  compensator: '补偿器',
  documents: '竣工资料',
  grounding: '静电接地',
  installation: '安装',
  sleeve: '套管',
  stress: '应力',
  support: '支吊架'
}

/** `required_ndtpersonnel_roster`：路径被压成全小写无分隔，只能按整段查表。 */
const FACT_PATH_LABELS: Record<string, string> = {
  actualndt_workitems: '实际无损检测·检测项目',
  certificatefacts_certificates: '证书事实·证书清单',
  design_requiresinsulatedsupport: '设计文件·是否要求绝缘支架',
  insulatedsupport_inspectionrecords: '绝缘支架·检查记录',
  insulatedsupport_results: '绝缘支架·检查结果',
  ndtpersonnel_qualificationcodes: '无损检测人员·资格代号',
  ndtpersonnel_registration: '无损检测人员·注册信息',
  ndtpersonnel_roster: '无损检测人员·名单'
}

/** 拼出来的那五族。认得出返回中文，认不出返回空串交给下一档兜底。 */
const generatedCheckLabel = (code: string): string => {
  for (const [pattern, frame] of DOCUMENT_CHECK_FRAMES) {
    const slug = code.match(pattern)?.[1]
    if (slug && materialTypeLabels[slug]) return frame(materialTypeLabels[slug])
  }
  const required = code.match(/^required_(.+)$/)?.[1]
  if (required && FACT_PATH_LABELS[required]) return `必需项：${FACT_PATH_LABELS[required]}`
  const frozen = code.match(
    /^r\d+_(?:([a-z]+)_)?((?:scope|standard_rules|domains|applicability)_missing)$/
  )
  if (frozen) {
    const gap = FROZEN_DOMAIN_GAPS[frozen[2]]
    const domainName = frozen[1] ? FROZEN_DOMAIN_NAMES[frozen[1]] : ''
    if (gap && (!frozen[1] || domainName)) return domainName ? `${domainName}：${gap}` : gap
  }
  const grade = code.match(/^grade_(gc[0-9a-z]+)$/)?.[1]
  if (grade) return `管道级别 ${grade.toUpperCase()}`
  const domain = code.match(/^([a-z]+)_(.+)$/)
  if (domain && DESIGN_DOMAIN_LABELS[domain[1]]) {
    const subject = DESIGN_DOMAIN_LABELS[domain[1]]
    const standardRef = domain[2].match(/^standard_ref_(\d+)$/)?.[1]
    if (standardRef) return `${subject}：引用标准 ${standardRef}`
    const suffix = DESIGN_DOMAIN_SUFFIXES[domain[2]]
    if (suffix) return `${subject}：${suffix}`
  }
  return ''
}

export const friendlyCheckCode = (value?: string | null) => {
  const raw = String(value || '').trim()
  if (!raw) return ''
  const [, prefix, code] = raw.match(/^(.*?):([^:]+)$/) || [null, '', raw]
  const withPrefix = (label: string) => (prefix ? `${prefix}：${label}` : label)
  if (checkCodeLabels[code]) return withPrefix(checkCodeLabels[code])
  const generated = generatedCheckLabel(code)
  if (generated) return withPrefix(generated)
  const indexed = indexedCheckLabel(code)
  if (indexed) return withPrefix(indexed)
  const scope = code.match(/^scope_covers_(.+)$/)
  const base =
    (scope ? `许可范围覆盖 ${scope[1]}` : '') ||
    code.replace(/^fact_\d+_/, (m) => `事实${m.replace(/\D/g, '')}·`)
  const factMatch = code.match(/^fact_(\d+)_(.+)$/)
  if (factMatch)
    return withPrefix(`事实 ${factMatch[1]}：${checkCodeLabels[factMatch[2]] || factMatch[2]}`)
  if (base !== code) return withPrefix(base)
  // 最后一档：借原因码那套后缀框架（`r43_certificate_scope_missing` → 「缺少证书范围」）。
  const asReason = friendlyCheckReason(code)
  return withPrefix(asReason && asReason !== code ? asReason : base)
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
  const node = String(value).match(NODE_RULE_KEY)
  const label = node
    ? `监检第 ${Number(node[1])} 项`
    : ruleCodeLabels[value] || techTermLabels[value] || statusLabelMap[value]
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
  acceptance_witness_record: '到货验收见证资料',
  anticorrosion_insulation_material_certificate: '防腐及保温材料质量证明文件',
  anticorrosion_insulation_record: '防腐补口补伤和保温施工记录',
  approval_record: '批准记录',
  audit_report: '审核报告',
  calculation_report: '强度计算书或应力分析报告',
  calibration_certificate: '校准证书',
  cathodic_protection_record: '阴极保护和杂散电流排流装置资料',
  construction_license: '施工单位安装许可证',
  construction_organization_design: '施工组织设计',
  construction_schedule: '施工计划工期文件',
  consumable_management: '焊材管理记录',
  consumable_receipt: '焊材入库/领用记录',
  control_matrix: '控制矩阵',
  data_access_log: '数据访问日志',
  defect_rectification: '缺陷整改记录',
  design_change_document: '设计变更和书面批准文件',
  design_document: '设计文件',
  design_license: '设计单位许可证',
  design_specification: '设计说明书',
  device_inspection_report: '设备检验报告',
  device_register: '设备台账',
  drawing_catalog: '图纸目录',
  drawing_material_list: '图纸材料表',
  drawing_review_record: '施工图审查手续',
  enterprise_material_standard: '企业材料标准',
  external_query_screenshot: '外部查询截图',
  factory_inspection_report: '出厂检验报告',
  field_photo: '现场照片、底片或实物核验证据',
  foreign_component_inspection_record: '境外元件检验记录',
  foreign_manufactured_component_list: '境外制造元件清单',
  generic_review_material: '审查资料',
  grounding_test_record: '静电接地施工和测试记录',
  hardness_report: '硬度检测报告',
  heat_treatment_instrument: '热处理测温仪表记录',
  heat_treatment_procedure: '焊后热处理工艺文件',
  heat_treatment_record: '热处理记录、曲线和硬度检测报告',
  incident_log: '事件记录',
  installation_license: '安装单位许可证',
  installation_record: '管道安装和现场制作记录',
  instrument_calibration_certificate: '仪表检定或校准证书',
  last_inspection_report: '上次检验报告',
  leakage_test_report: '泄漏试验记录或报告',
  maintenance_record: '维护保养记录',
  manufacturing_license: '制造单位许可证',
  manufacturing_supervision_certificate: '制造监督检验证书',
  material_mark_transfer_record: '材料标志移植记录',
  material_ndt_report: '材料无损检测报告',
  material_retest_report: '材料复验报告',
  material_substitution_approval: '材料代用批准文件',
  ndt_agency_approval: '无损检测机构核准证',
  ndt_org_certificate: '无损检测机构核准证',
  ndt_person_certificate: '无损检测人员资格证和执业注册证',
  ndt_personnel_certificate: '无损检测人员资格证',
  ndt_plan: '无损检测方案',
  ndt_procedure: '无损检测工艺文件',
  ndt_report: '无损检测报告',
  new_material_data: '新材料数据',
  org_chart: '组织机构图',
  overseas_material_certificate: '境外制造或境外牌号材料证明文件',
  pipe_fit_up_record: '管道组对记录',
  pipeline_data_sheet: '管道数据表',
  pipeline_layout_drawing: '管道布置图',
  pipeline_material_list: '管道材料表',
  pipeline_summary: '管线汇总表',
  platform_verification: '平台核验记录',
  pmi_report: '光谱分析（PMI）报告',
  policy_document: '制度文件',
  pqr: '焊接工艺评定报告 PQR',
  pressure_test_plan: '耐压试验方案',
  pressure_test_report: '耐压试验记录或报告',
  process_record: '过程记录',
  purge_cleaning_record: '吹扫清洗方案和记录',
  quality_certificate: '产品质量证明书',
  quality_system_document: '质量保证体系文件和实施记录',
  radiographic_film: '射线检测底片',
  remediation_plan: '整改方案',
  risk_register: '风险台账',
  safety_accessory_record: '安全附件安装、校验或性能测试资料',
  safety_device_record: '安全附件记录',
  sampling_witness_record: '抽样见证记录',
  standard_reference: '标准规范正文',
  straight_pipe_strength_calculation: '直管段强度计算书',
  technical_review_approval: '技术评审和批准手续',
  temperature_point_layout: '测温点布置图',
  third_party_contract: '第三方合同',
  training_record: '培训记录',
  type_test_report: '型式试验证书或型式试验报告',
  unclassified_material: '未分类资料',
  valve_construction_record: '阀门施工记录',
  valve_test_report: '阀门施工资料和耐压试验报告',
  weld_appearance_record: '焊接接头外观检查记录',
  weld_repair_record: '焊缝返修记录',
  welder_certificate: '焊工资格证',
  welder_roster: '焊工名册',
  welding_consumable_certificate: '焊接材料质量证明文件',
  welding_material_certificate: '焊接材料质量证明文件',
  welding_material_management_record: '焊材验收保管发放回收记录',
  welding_process_card: '焊接工艺卡',
  welding_record: '焊接记录和焊缝标识资料',
  wps: '焊接作业指导书 WPS',
  wps_pqr: '焊接工艺评定报告和焊接作业指导书'
}

export const friendlyMaterialType = (value?: string | null) => {
  const code = String(value || '').trim()
  if (!code) return ''
  return materialTypeLabels[code] || code
}
