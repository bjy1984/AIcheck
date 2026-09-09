import type { EvidenceLink } from '@/types/aicheck'

export const evidencePreviewSource = (evidence: EvidenceLink | undefined, projectId?: string) => {
  if (!evidence) return ''
  if (evidence.objectType !== 'knowledgeClause' && evidence.documentVersionId) {
    const scope = projectId || evidence.projectId
    if (!scope || !evidence.documentId) return ''
    return `/api/projects/${encodeURIComponent(scope)}/documents/${encodeURIComponent(evidence.documentId)}/original?versionId=${encodeURIComponent(evidence.documentVersionId)}&disposition=inline`
  }
  return String(evidence.previewUrl || '')
}
