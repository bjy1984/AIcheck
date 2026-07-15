export type FdeNavigationTone = 'blue' | 'green' | 'orange' | 'red'

export type FdeRouteCatalogItem = {
  key: string
  label: string
  shortLabel: string
  group: 'overview' | 'production' | 'improvement' | 'delivery' | 'operations'
  route: string
  permission: string
  tone: FdeNavigationTone
  index: string
}

export const fdeNavigationGroups = [
  { key: 'overview', label: '总览', hint: '全局真值与阻断' },
  { key: 'production', label: '生产链路', hint: '项目、OCR 与 AI 运行' },
  { key: 'improvement', label: '改进验证', hint: '反馈闭环与评估门禁' },
  { key: 'delivery', label: '能力发布', hint: '业务包、组合与灰度发布' },
  { key: 'operations', label: '运营交付', hint: '安全、事故、成本与验收' }
] as const

export const fdeRouteCatalog: FdeRouteCatalogItem[] = [
  {
    key: 'dashboard',
    label: '治理总览',
    shortLabel: '总览',
    group: 'overview',
    route: '/fde/dashboard',
    permission: 'fde:dashboard:view',
    tone: 'blue',
    index: '01'
  },
  {
    key: 'projects',
    label: '项目审计',
    shortLabel: '项目',
    group: 'production',
    route: '/fde/projects',
    permission: 'fde:dashboard:view',
    tone: 'blue',
    index: '02'
  },
  {
    key: 'ocr-quality',
    label: 'OCR 质量',
    shortLabel: 'OCR',
    group: 'production',
    route: '/fde/ocr-quality',
    permission: 'fde:ocr-quality:view',
    tone: 'green',
    index: '03'
  },
  {
    key: 'ai-runs',
    label: 'AI Run',
    shortLabel: 'AI Run',
    group: 'production',
    route: '/fde/ai-runs',
    permission: 'fde:ai-run:view-masked',
    tone: 'green',
    index: '04'
  },
  {
    key: 'review-runs',
    label: '审查编排',
    shortLabel: '编排',
    group: 'production',
    route: '/fde/review-runs',
    permission: 'fde:ai-run:view-masked',
    tone: 'green',
    index: '05'
  },
  {
    key: 'feedback',
    label: '反馈样本',
    shortLabel: '反馈',
    group: 'improvement',
    route: '/fde/feedback',
    permission: 'fde:feedback:view',
    tone: 'orange',
    index: '06'
  },
  {
    key: 'evaluation',
    label: '评估验证',
    shortLabel: '评估',
    group: 'improvement',
    route: '/fde/evaluation',
    permission: 'fde:evaluation:view',
    tone: 'green',
    index: '07'
  },
  {
    key: 'business-packs',
    label: '业务包',
    shortLabel: '业务包',
    group: 'delivery',
    route: '/fde/business-packs',
    permission: 'fde:business-pack:view',
    tone: 'blue',
    index: '08'
  },
  {
    key: 'capability-bundles',
    label: '能力组合',
    shortLabel: '组合',
    group: 'delivery',
    route: '/fde/capability-bundles',
    permission: 'fde:business-pack:view',
    tone: 'blue',
    index: '09'
  },
  {
    key: 'releases',
    label: '发布治理',
    shortLabel: '发布',
    group: 'delivery',
    route: '/fde/releases',
    permission: 'fde:release:view',
    tone: 'orange',
    index: '10'
  },
  {
    key: 'security',
    label: '数据安全',
    shortLabel: '安全',
    group: 'operations',
    route: '/fde/security',
    permission: 'fde:security:manage',
    tone: 'red',
    index: '11'
  },
  {
    key: 'incidents',
    label: '事故复盘',
    shortLabel: '事故',
    group: 'operations',
    route: '/fde/incidents',
    permission: 'fde:incident:manage',
    tone: 'orange',
    index: '12'
  },
  {
    key: 'costs',
    label: '成本预算',
    shortLabel: '成本',
    group: 'operations',
    route: '/fde/costs',
    permission: 'fde:dashboard:view',
    tone: 'blue',
    index: '13'
  },
  {
    key: 'acceptance',
    label: '客户验收',
    shortLabel: '验收',
    group: 'operations',
    route: '/fde/acceptance',
    permission: 'fde:business-pack:view',
    tone: 'green',
    index: '14'
  }
]

export const fdeRouteCatalogByKey = Object.fromEntries(
  fdeRouteCatalog.map((item) => [item.key, item])
) as Record<string, FdeRouteCatalogItem>
