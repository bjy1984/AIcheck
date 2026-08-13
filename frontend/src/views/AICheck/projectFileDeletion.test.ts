import assert from 'node:assert/strict'

import type { DocumentAsset, NodePackagePayload } from '@/types/aicheck'
import { removeProjectFileLocally, restoreProjectFileLocally } from './projectFileDeletion'

const file = (id: string): DocumentAsset =>
  ({
    id,
    fileName: `${id}.pdf`
  }) as DocumentAsset

const packageWithFiles = (...ids: string[]): NodePackagePayload =>
  ({
    projectFiles: ids.map(file)
  }) as NodePackagePayload

const original = packageWithFiles('DOC-1', 'DOC-2', 'DOC-3')
const removal = removeProjectFileLocally(original, 'DOC-2')

assert.deepEqual(
  removal.packageData?.projectFiles.map((item) => item.id),
  ['DOC-1', 'DOC-3']
)
assert.equal(removal.removedFile?.id, 'DOC-2')
assert.equal(removal.originalIndex, 1)
assert.deepEqual(
  original.projectFiles.map((item) => item.id),
  ['DOC-1', 'DOC-2', 'DOC-3'],
  '乐观移除不能修改原节点包'
)

const restored = restoreProjectFileLocally(removal.packageData, removal)
assert.deepEqual(
  restored?.projectFiles.map((item) => item.id),
  ['DOC-1', 'DOC-2', 'DOC-3']
)

const restoredTwice = restoreProjectFileLocally(restored, removal)
assert.deepEqual(
  restoredTwice?.projectFiles.map((item) => item.id),
  ['DOC-1', 'DOC-2', 'DOC-3'],
  '重复恢复不能插入重复文件'
)

const missing = removeProjectFileLocally(original, 'DOC-NOT-FOUND')
assert.equal(missing.packageData, original)
assert.equal(missing.removedFile, undefined)
assert.equal(missing.originalIndex, -1)

assert.equal(removeProjectFileLocally(undefined, 'DOC-1').packageData, undefined)
assert.equal(restoreProjectFileLocally(undefined, removal), undefined)

console.log('project file optimistic deletion contract passed')
