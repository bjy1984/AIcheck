import assert from 'node:assert/strict'
import { evidencePreviewSource } from './evidencePreviewSource'
import type { EvidenceLink } from '@/types/aicheck'
const evidence = {
  id: 'E1',
  projectId: 'P/1',
  documentId: 'D/1',
  documentVersionId: 'OLD/1',
  fileName: '历史文件.pdf',
  previewUrl: '/api/current-new-version',
  objectType: 'documentVersion'
} as EvidenceLink
assert.equal(
  evidencePreviewSource(evidence),
  '/api/projects/P%2F1/documents/D%2F1/original?versionId=OLD%2F1&disposition=inline'
)
assert.equal(
  evidencePreviewSource({ ...evidence, previewUrl: undefined }),
  evidencePreviewSource(evidence)
)
assert.equal(
  evidencePreviewSource({ ...evidence, objectType: 'knowledgeClause' }),
  '/api/current-new-version'
)
assert.equal(
  evidencePreviewSource({ ...evidence, documentVersionId: undefined }),
  '/api/current-new-version'
)
assert.equal(evidencePreviewSource(undefined), '')

assert.equal(
  evidencePreviewSource({ ...evidence, documentId: undefined }),
  '',
  '缺文件身份不能使用当前版本预览网址'
)
