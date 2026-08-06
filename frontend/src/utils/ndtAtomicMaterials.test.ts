import assert from 'node:assert/strict'
import type { DocumentAsset, NodeFileBinding } from '@/types/aicheck'
import {
  NDT_ATOMIC_MATERIALS,
  NDT_NODE_IDS,
  ndtAtomicMaterialByCode,
  ndtFileApprovalStatus
} from './ndtAtomicMaterials'

assert.equal(NDT_ATOMIC_MATERIALS.length, 21)
assert.deepEqual(NDT_NODE_IDS, [35, 36, 37, 38, 39, 40, 41, 42])
assert.deepEqual(ndtAtomicMaterialByCode('ndt_entrustment')?.defaultNodeIds, [37, 42])
assert.equal(ndtAtomicMaterialByCode('missing'), undefined)

for (const material of NDT_ATOMIC_MATERIALS) {
  assert.ok(material.code)
  assert.ok(material.name)
  assert.ok(material.defaultNodeIds.length > 0)
  assert.ok(material.defaultNodeIds.every((nodeId) => NDT_NODE_IDS.includes(nodeId)))
}

const binding = (bindingStatus: NodeFileBinding['bindingStatus']): NodeFileBinding => ({
  id: `BIND-${bindingStatus}`,
  projectId: 'P-1',
  nodeId: 35,
  documentId: 'DOC-1',
  documentVersionId: 'DV-1',
  fileName: '质量保证手册.pdf',
  versionNo: 'V1',
  usage: '证明材料',
  sourceOrgName: '检测单位',
  bindingStatus,
  boundAt: '2026-08-06T00:00:00Z',
  actions: []
})

const fileWithBindings = (bindings: NodeFileBinding[]) =>
  ({ bindings }) as Pick<DocumentAsset, 'bindings'>

assert.equal(ndtFileApprovalStatus(fileWithBindings([])), '草稿')
assert.equal(ndtFileApprovalStatus(fileWithBindings([binding('草稿挂载')])), '草稿')
assert.equal(ndtFileApprovalStatus(fileWithBindings([binding('已提交')])), '待审查')
assert.equal(
  ndtFileApprovalStatus(fileWithBindings([binding('已提交'), binding('需补正')])),
  '需补正'
)
assert.equal(
  ndtFileApprovalStatus(fileWithBindings([binding('已通过'), binding('已通过')])),
  '已通过'
)
