import assert from 'node:assert/strict'
import type { OcrStructuredView } from '@/api/aicheck'
import { documentPageRows } from './documentPagePresentation'
const view: OcrStructuredView = {
  available: true,
  documentVersionId: 'V1',
  layoutBlocks: [],
  tables: [],
  seals: [],
  pageCount: 3,
  truncated: false,
  pageClassifications: [
    { pageNo: 3, status: 'unknown', documentKind: null },
    { pageNo: 1, status: 'identified', documentKind: 'rt_report' },
    { pageNo: 2, status: 'ambiguous', documentKind: null }
  ]
}
assert.deepEqual(
  documentPageRows(view, 'V1').map((row) => [row.pageNo, row.identified]),
  [
    [1, true],
    [2, false],
    [3, false]
  ]
)
assert.equal(documentPageRows(view, 'V1')[0].label, '射线检测报告')
assert.deepEqual(documentPageRows(view, 'V2'), [])
assert.deepEqual(documentPageRows(view, undefined), [])
assert.deepEqual(documentPageRows(undefined, 'V1'), [])
const duplicate = structuredClone(view)
duplicate.pageClassifications!.push({ pageNo: 1, status: 'identified', documentKind: 'pqr' })
assert.equal(documentPageRows(duplicate, 'V1')[0].identified, false)
const unsupported = structuredClone(view)
unsupported.pageClassifications![1].documentKind = 'constructor'
assert.equal(documentPageRows(unsupported, 'V1')[0].identified, false)
assert.equal(documentPageRows(view, 'V1').length, 3)
