import type { Handoff } from '@/api/aicheck/reviewHandoffs'

export function handoffBelongsTo(record: Handoff, projectId: string, runId: string): boolean {
  return record.projectId === projectId && record.draft.target.runId === runId
}
export function handoffReviewBlock(record: Handoff): string {
  if (!['review-handoff-draft-v2', 'review-handoff-draft-v3'].includes(record.draft.schemaVersion))
    return '历史交接未指定事件，请重新建立交接。'
  if (record.validation.status !== 'current_draft')
    return '交接内容或来源已变更，请重新建立交接后核验。'
  if (record.validation.inputSourceCheck?.status !== 'current')
    return '无法验证双方的固定来源，暂不能核验。'
  if (record.verification?.status === 'invalid_history')
    return '核验历史校验失败，请联系管理员检查。'
  return ''
}
export function handoffCanConfirm(record: Handoff): boolean {
  return (
    !handoffReviewBlock(record) &&
    (record.draft.kind === 'collaboration' ||
      record.validation.evidenceLocationCheck?.status === 'locations_found')
  )
}
export const handoffStatusText = (status?: string) =>
  ({
    unreviewed: '待核验',
    verified: '已人工确认',
    rejected: '已退回',
    stale: '来源变更，待重新核验',
    invalid_history: '核验记录异常'
  })[status || 'unreviewed'] || '状态待核对'

export function handoffEvidenceLink(record: Handoff, versionId: string) {
  const matches = (record.evidenceDocuments || []).filter(
    (row) => row.documentVersionId === versionId
  )
  if (matches.length !== 1) return null
  const document = matches[0]
  const project = encodeURIComponent(record.projectId)
  return {
    documentId: document.documentId,
    documentVersionId: versionId,
    fileName: document.fileName,
    previewUrl: `/api/projects/${project}/documents/${encodeURIComponent(document.documentId)}/original?versionId=${encodeURIComponent(versionId)}&disposition=inline`
  }
}
