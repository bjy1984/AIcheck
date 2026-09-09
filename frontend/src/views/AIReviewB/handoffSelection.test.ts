import assert from 'node:assert/strict'
import type { Handoff } from '@/api/aicheck/reviewHandoffs'
import { selectionWithHandoff } from './handoffSelection'
import { documentSelectionPayload } from './documentPageSelection'

const record: Handoff = {
  id: 'H1',
  projectId: 'P',
  draft: {
    schemaVersion: 'review-handoff-draft-v3',
    snapshotHash: 'HASH',
    kind: 'facts',
    subject: { objectType: 'weld', objectId: 'W1', eventId: 'EV1', repairRound: 1 },
    source: { runId: 'SOURCE', stationId: 'A', nodeId: 24 },
    target: { runId: 'TARGET', stationId: 'E', nodeId: 35 },
    payload: { observation: '原文核对' },
    evidenceRefs: [{ id: 'REF', documentVersionId: 'V', pageNo: 2 }]
  },
  evidenceDocuments: [{ documentVersionId: 'V', documentId: 'DOC', fileName: 'fixed.pdf' }],
  validation: {
    status: 'current_draft',
    inputSourceCheck: { status: 'current' },
    evidenceLocationCheck: { status: 'locations_found' }
  },
  verification: { status: 'verified', authoritative: false, latestVerificationId: 'HV1' },
  verifications: [
    {
      id: 'HV1',
      outcome: 'verified',
      reviewedByUserId: 'USER',
      createdAt: '2026-09-09',
      note: '已核对'
    }
  ]
}
const selected = selectionWithHandoff(record, 'P', 'TARGET', null)
assert.equal(selected.versions[0].versionId, 'V')
assert.equal(selected.versions[0].pageRange, undefined)
assert.equal(selected.reviewMode, 'gap_precheck')
assert.deepEqual(selected.handoffSelection?.items, [{ handoffId: 'H1', verificationId: 'HV1' }])
assert.equal(
  selectionWithHandoff(record, 'P', 'TARGET', selected).handoffSelection?.items.length,
  1
)
const payload = documentSelectionPayload(selected)
selected.handoffSelection!.subject.objectId = 'CHANGED'
assert.equal(payload.handoffSelection.subject.objectId, 'W1')
assert.equal(record.draft.subject.objectId, 'W1')
assert.throws(() => selectionWithHandoff(record, 'P', 'OTHER', null))
assert.throws(() => selectionWithHandoff(record, 'OTHER', 'TARGET', null))
assert.throws(() =>
  selectionWithHandoff(
    { ...record, verification: { status: 'stale', authoritative: false } },
    'P',
    'TARGET',
    null
  )
)
assert.throws(() => selectionWithHandoff(record, 'P', 'TARGET', selected), /另一个对象/)
const scoped = selectionWithHandoff(record, 'P', 'TARGET', {
  reviewMode: 'formal',
  versions: [
    { documentId: 'DOC', versionId: 'V', fileName: 'fixed.pdf', pageRange: { start: 2, end: 3 } }
  ]
})
assert.equal(scoped.reviewMode, 'formal')
assert.deepEqual(scoped.versions[0].pageRange, { start: 2, end: 3 })
scoped.versions[0].pageRange!.start = 3
assert.throws(() => selectionWithHandoff(record, 'P', 'TARGET', scoped), /页码范围/)
const unknown = { ...record, evidenceDocuments: [] }
assert.throws(() => selectionWithHandoff(unknown, 'P', 'TARGET', null), /不完整/)
const mapping = {
  selection: {
    subject: { objectType: 'weld', objectId: 'W2' },
    fields: {},
    confirmedSameObject: true
  },
  ruleVersionId: 'R',
  ruleRevision: 1,
  sourceSnapshotHash: 'S'
}
assert.throws(
  () =>
    selectionWithHandoff(record, 'P', 'TARGET', {
      versions: [],
      reviewMode: 'formal',
      conditionObjectMapping: mapping
    }),
  /对象不同/
)
mapping.selection.subject.objectId = 'W1'
assert.throws(
  () =>
    selectionWithHandoff(record, 'P', 'TARGET', {
      versions: [],
      reviewMode: 'formal',
      conditionObjectMapping: mapping
    }),
  /改变试跑资料/
)
