/**
 * 动作权限码的中文名。
 *
 * 角色权限矩阵原来直接把 `project:view`、`fde:vector-quality:apply` 这类码
 * 摊在表格里。这些码是给中间件比对用的，不是给人读的——管理员配一个角色
 * 要先在心里翻译一遍，还容易把 `ai:adopt` 和 `ai:recheck` 看混。
 *
 * 认不出的码**原样显示**，不猜、也不隐藏：新增了动作却忘了加中文，
 * 界面上看得见那个码，比显示一个编出来的名字安全得多。
 */
const ACTION_LABELS: Record<string, string> = {
  // 项目与文件
  'project:view': '查看项目',
  'project:authorize-member': '授权项目成员',
  'file:view': '查看文件',
  'file:upload': '上传文件',
  'file:bind': '挂接资料',
  'file:preview': '预览文件',
  'file:download': '下载文件',
  'file:withdraw': '撤回文件',

  // 提交与整改
  'submission:draft': '暂存提交单',
  'submission:submit': '提交资料',
  'rectification:submit': '提交整改',
  'review:save': '保存复核结论',
  'review:return-correction': '退回补正',

  // AI 与模型
  'ai:recheck': '发起 AI 复核',
  'ai:adopt': '采纳 AI 建议',
  'ai:reject': '驳回 AI 建议',
  'llm:compare': '模型对比',

  // 无损检测
  'ndt:film-create': '创建底片记录',
  'ndt:record-import': '导入检测记录',
  'ndt:report-upload': '上传检测报告',
  'ndt:submit': '提交无损检测',

  // 报告与归档
  'report:generate': '生成报告',
  'report:review': '审核报告',
  'report:export': '导出报告',
  'report:archive': '归档报告',
  'report:view': '查看报告',
  'archive:view': '查看档案',
  'archive:download': '下载档案',

  // 协作
  'todo:update': '处理待办',
  'message:update': '处理消息',

  // 知识库与审计
  'knowledge:view': '查看知识库',
  'knowledge:manage': '管理知识库',
  'audit:view': '查看审计日志',
  'admin:config': '后台配置',
  'admin:export': '导出配置',

  // FDE 治理
  'fde:dashboard:view': 'FDE 看板',
  'fde:ai-run:view-masked': '查看脱敏运行记录',
  'fde:ai-run:replay': '重放运行记录',
  'fde:business-pack:view': '查看业务包',
  'fde:business-pack:validate': '校验业务包',
  'fde:business-pack:install': '安装业务包',
  'fde:capability-bundle:manage': '管理能力包',
  'fde:config:draft': '起草配置',
  'fde:cost:manage': '成本管理',
  'fde:evaluation:view': '查看评测',
  'fde:evaluation:run': '运行评测',
  'fde:evaluation:manage': '管理评测',
  'fde:feedback:view': '查看反馈',
  'fde:feedback:triage': '分流反馈',
  'fde:incident:manage': '事件管理',
  'fde:ocr-annotation:manage': '管理 OCR 标注',
  'fde:ocr-quality:view': '查看 OCR 质量',
  'fde:release:view': '查看发布',
  'fde:release:submit': '提交发布',
  'fde:release:shadow': '影子发布',
  'fde:release:canary': '灰度发布',
  'fde:release:rollback': '回滚发布',
  'fde:security:manage': '安全管理',
  'fde:vector-quality:view': '查看向量质量',
  'fde:vector-quality:review': '复核向量质量',
  'fde:vector-quality:apply': '应用向量修正'
}

/** 动作码的中文名；认不出就原样返回那个码。 */
export const actionLabel = (action: string): string => ACTION_LABELS[action] || action

/** 中文名 + 原始码，用于悬浮说明——配权限的人有时确实需要看到码本身。 */
export const actionLabelWithCode = (action: string): string => {
  const label = ACTION_LABELS[action]
  return label ? `${label}（${action}）` : action
}

export const knownActionCodes = (): string[] => Object.keys(ACTION_LABELS)
