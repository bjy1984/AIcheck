import assert from 'node:assert/strict'
import type { ReviewDocumentSelection } from '@/api/aicheck/reviewDocuments'
import { objectCandidateLabel, runObjectCandidates, selectionWithObject } from './objectSelection'
import { documentSelectionPayload } from './documentPageSelection'

const candidates = [
  { objectId: 'PL8303-100', objectType: 'pipeline', documentVersionId: 'V', pageNo: 16 },
  { objectId: 'PL8306-100', objectType: 'pipeline', documentVersionId: 'V', pageNo: null }
]
assert.deepEqual(runObjectCandidates({ objectCandidates: candidates }), candidates)
assert.deepEqual(runObjectCandidates(null), [])
assert.equal(objectCandidateLabel(candidates[0]), 'PL8303-100（第 16 页）')
assert.equal(objectCandidateLabel(candidates[1]), 'PL8306-100')

const selection: ReviewDocumentSelection = {
  reviewMode: 'formal',
  versions: [{ documentId: 'D', versionId: 'V', fileName: '交工资料.pdf' }]
}
assert.throws(() => selectionWithObject(null, 'PL8303-100'), /先选择本次审查的文件版本/)
const chosen = selectionWithObject(selection, 'PL8303-100')
assert.deepEqual(chosen.selectedObjectIds, ['PL8303-100'])
assert.deepEqual(documentSelectionPayload(chosen), {
  inputDocumentVersionIds: ['V'],
  selectedObjectIds: ['PL8303-100']
})
