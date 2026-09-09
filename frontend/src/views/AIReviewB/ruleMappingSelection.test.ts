import assert from 'node:assert/strict'
import { mappingSelectionFromTrial } from './ruleMappingSelection'
import { documentSelectionPayload } from './documentPageSelection'
import type { ProjectRule, RuleTrialResult } from '@/api/aicheck/projectRules'
const rule: ProjectRule = {
  id: 'R',
  projectId: 'P',
  nodeIds: [24],
  status: '已发布',
  version: '1',
  etag: 'rev2',
  inspectionItem: 'thickness',
  standardText: 'test',
  witnessText: ''
}
const result: RuleTrialResult = {
  result: 'pass',
  ruleRevision: 2,
  sourceSnapshotHash: 'SOURCE',
  checks: [],
  bindingPlan: { replacements: [{ atomicCheckId: 'A' }], retainedAtomicCheckIds: [] },
  sourceDocuments: [
    { documentId: 'DOC', versionId: 'V', fileName: 'fixed.pdf', pageRange: { start: 2, end: 4 } }
  ],
  objectMappingSnapshot: {
    snapshotHash: 'M',
    selection: {
      subject: { objectType: 'weld', objectId: 'W1' },
      confirmedSameObject: true,
      fields: { thickness: 'FIELD' }
    }
  }
}
const selection = mappingSelectionFromTrial(rule, result, 'formal')
assert.equal(selection.reviewMode, 'formal')
const payload = documentSelectionPayload(selection)
result.objectMappingSnapshot!.selection.subject.objectId = 'W2'
result.sourceDocuments![0].pageRange!.end = 8
assert.equal(selection.conditionObjectMapping!.selection.subject.objectId, 'W1')
assert.deepEqual(payload.inputDocumentPageRanges, { V: { start: 2, end: 4 } })
selection.conditionObjectMapping!.selection.fields.thickness = 'NEW'
assert.equal(payload.conditionObjectMapping.selection.fields.thickness, 'FIELD')
assert.throws(() => mappingSelectionFromTrial({ ...rule, status: '草稿' }, result))
assert.throws(() => mappingSelectionFromTrial(rule, { ...result, sourceDocuments: [] }))
assert.throws(() => mappingSelectionFromTrial(rule, { ...result, bindingPlan: undefined }))
const explicitEmpty = mappingSelectionFromTrial(rule, {
  ...result,
  sourcePageRanges: {},
  sourceDocuments: [{ documentId: 'D', versionId: 'V', fileName: 'all.pdf' }]
})
assert.deepEqual(documentSelectionPayload(explicitEmpty).inputDocumentPageRanges, {})
