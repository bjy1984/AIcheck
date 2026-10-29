/** Shared by the admin screen and its behavioral regression tests. */
export const adminOverviewSections = (tab: string): string[] => {
  if (tab === 'rule') return ['ruleVersions']
  if (tab === 'material-review-point') return ['materialReviewPoints']
  return ['core']
}

export const missingAdminSections = (tab: string, omitted: string[] = []) =>
  adminOverviewSections(tab).filter((section) => section !== 'core' && omitted.includes(section))

export const adminCountLabel = (value: number | undefined | null, available: boolean) =>
  available && value != null && Number.isFinite(value) ? String(value) : '未获取'

export const adminValidationState = (options: {
  loading: boolean
  error?: string
  ok: boolean | null
  successLabel?: string
  failureLabel?: string
}) => {
  if (options.loading) return { type: 'info' as const, label: '检查中' }
  if (options.error) return { type: 'danger' as const, label: '检查失败' }
  if (options.ok === null) return { type: 'info' as const, label: '未检查' }
  return options.ok
    ? { type: 'success' as const, label: options.successLabel || '检查通过' }
    : { type: 'danger' as const, label: options.failureLabel || '存在错误' }
}

export const confidenceValue = (value: unknown, fallback: number) => {
  if (value == null || value === '') return fallback
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

export const productionTemplateLocked = (status?: string) =>
  ['production', '已发布'].includes(status || '')

/** Confirm against the complete history, including production records on later pages. */
export const loadTemplatePublishCandidates = async <T extends { id: string }>(
  loadPage: (
    page: number,
    pageSize: number
  ) => Promise<
    | {
        data: { items: T[]; total: number }
      }
    | undefined
  >
): Promise<T[]> => {
  const records = new Map<string, T>()
  let expectedTotal: number | undefined
  for (let page = 1; ; page += 1) {
    const response = await loadPage(page, 100)
    if (!response) throw new Error('生产版本清单加载失败，请重试。')
    const { items, total } = response.data
    if (expectedTotal !== undefined && total !== expectedTotal) {
      throw new Error('模板清单在读取期间发生变化，请重新发起发布确认。')
    }
    expectedTotal = total
    const before = records.size
    for (const item of items) records.set(item.id, item)
    if (records.size >= total) return [...records.values()]
    if (records.size === before) {
      throw new Error('模板清单分页未返回后续记录，请重试。')
    }
  }
}

export const promptDraftFrom = <
  T extends { id: string; version: string; status: string; etag?: string }
>(
  template: T
): T => ({ ...template, id: '', etag: '', version: `${template.version}-draft`, status: 'draft' })

type PublishTemplate = {
  id: string
  name: string
  version: string
  businessPackId: string
  promptKey?: string
  status?: string
}
export const templatePublishMessage = (
  kind: 'Prompt' | '报告',
  template: PublishTemplate,
  productionTemplates: PublishTemplate[]
) => {
  const replaced = productionTemplates.filter(
    (item) =>
      item.id !== template.id &&
      productionTemplateLocked(item.status) &&
      item.businessPackId === template.businessPackId &&
      (kind === '报告' || item.promptKey === template.promptKey)
  )
  const current = replaced.length
    ? replaced.map((item) => `「${item.name}」${item.version}（${item.id}）`).join('、')
    : '无现有生产版本'
  const effect =
    kind === 'Prompt'
      ? '后续按此业务包和 Prompt Key 选择生产模板的审查会使用新版本；已保存的审查快照不改写。'
      : '后续按此业务包生成报告会使用新版本；已生成的报告不改写。'
  return `发布「${template.name}」${template.version}（${template.id}）？\n业务包：${template.businessPackId}${template.promptKey ? `；Prompt Key：${template.promptKey}` : ''}\n将替代：${current}。\n${effect}`
}

export const adminRecordScopes = (tab: string) =>
  tab === 'permission'
    ? [
        { value: 'permission' as const, label: '权限矩阵' },
        { value: 'node-template' as const, label: '节点模板' }
      ]
    : tab === 'rule'
      ? [
          { value: 'rule' as const, label: '业务规则' },
          { value: 'workflow' as const, label: '流程状态机' }
        ]
      : []

export const adminTargetPage = <T extends { id: string }>(
  rows: T[],
  id: string,
  pageSize: number
) => {
  const index = rows.findIndex((row) => row.id === id)
  return index < 0 ? null : { row: rows[index], page: Math.floor(index / pageSize) + 1 }
}
