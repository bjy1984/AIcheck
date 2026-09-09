import assert from 'node:assert/strict'
import type { Handoff } from '@/api/aicheck/reviewHandoffs'
import {
  handoffEvidenceLink,
  handoffBelongsTo,
  handoffCanConfirm,
  handoffReviewBlock
} from './handoffPresentation'

const record = {
  projectId: 'P1',
  draft: { schemaVersion: 'review-handoff-draft-v2', kind: 'facts', target: { runId: 'RUN1' } },
  validation: {
    status: 'current_draft',
    inputSourceCheck: { status: 'current' },
    evidenceLocationCheck: { status: 'locations_found' }
  },
  verification: { status: 'unreviewed', authoritative: false }
} as Handoff
assert.equal(handoffBelongsTo(record, 'P1', 'RUN1'), true)
assert.equal(handoffBelongsTo(record, 'P2', 'RUN1'), false)
assert.equal(handoffBelongsTo(record, 'P1', 'RUN2'), false)
assert.equal(handoffCanConfirm(record), true)
for (const change of [
  { ...record, draft: { ...record.draft, schemaVersion: 'review-handoff-draft-v1' } },
  { ...record, validation: { ...record.validation, status: 'stale_or_invalid' } },
  { ...record, validation: { ...record.validation, inputSourceCheck: { status: 'unverified' } } },
  { ...record, verification: { status: 'invalid_history', authoritative: false as const } }
]) {
  assert.ok(handoffReviewBlock(change))
  assert.equal(handoffCanConfirm(change), false)
}
const missingPage = {
  ...record,
  validation: { ...record.validation, evidenceLocationCheck: { status: 'unresolved' } }
}
assert.equal(handoffReviewBlock(missingPage), '')
assert.equal(handoffCanConfirm(missingPage), false)
assert.equal(
  handoffCanConfirm({ ...missingPage, draft: { ...missingPage.draft, kind: 'collaboration' } }),
  true
)

const fixedVersion = {
  ...record,
  evidenceDocuments: [
    { documentVersionId: 'OLD', documentId: 'D1', fileName: 'original.pdf' },
    { documentVersionId: 'NEW', documentId: 'D1', fileName: 'revision.pdf' }
  ]
}
assert.equal(
  handoffEvidenceLink(fixedVersion, 'OLD')?.previewUrl,
  '/api/projects/P1/documents/D1/original?versionId=OLD&disposition=inline'
)
assert.equal(handoffEvidenceLink(fixedVersion, 'MISSING'), null)
assert.equal(
  handoffEvidenceLink(
    {
      ...fixedVersion,
      evidenceDocuments: [...fixedVersion.evidenceDocuments, fixedVersion.evidenceDocuments[0]]
    },
    'OLD'
  ),
  null
)

assert.equal(
  handoffCanConfirm({
    ...record,
    draft: { ...record.draft, schemaVersion: 'review-handoff-draft-v3' }
  }),
  true
)
