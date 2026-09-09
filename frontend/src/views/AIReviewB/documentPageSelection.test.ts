import assert from 'node:assert/strict'
import {
  cloneDocumentSelectionVersions,
  documentPageLabel,
  documentSelectionPayload,
  validDocumentPageRange
} from './documentPageSelection'

const versions = [
  { documentId: 'D', versionId: 'V', fileName: 'fixed.pdf', pageRange: { start: 2, end: 5 } }
]
const cloned = cloneDocumentSelectionVersions(versions)
const payload = documentSelectionPayload({ versions: cloned, reviewMode: 'gap_precheck' })
versions[0].pageRange.end = 10
assert.equal(cloned[0].pageRange?.end, 5)
cloned[0].pageRange!.end = 9
assert.deepEqual(payload.inputDocumentPageRanges, { V: { start: 2, end: 5 } })
assert.equal(documentPageLabel(versions[0]), '第 2–10 页')
assert.deepEqual(
  documentSelectionPayload({
    versions: [{ documentId: 'D', versionId: 'V', fileName: 'fixed.pdf' }],
    reviewMode: 'formal'
  }),
  { inputDocumentVersionIds: ['V'] }
)
for (const range of [
  { start: 0, end: 1 },
  { start: 3, end: 2 },
  { start: 1.5, end: 3 },
  { start: 1, end: NaN },
  { start: 1, end: Infinity }
]) {
  assert.equal(validDocumentPageRange(range), false)
  assert.throws(() =>
    documentSelectionPayload({
      versions: [{ ...versions[0], pageRange: range }],
      reviewMode: 'formal'
    })
  )
}
assert.equal(validDocumentPageRange(undefined), true)
