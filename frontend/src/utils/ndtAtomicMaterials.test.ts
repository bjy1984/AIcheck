import assert from 'node:assert/strict'
import type { DocumentAsset, NodeFileBinding } from '@/types/aicheck'
import {
  NDT_ATOMIC_MATERIALS,
  NDT_BUSINESS_RULE_NAMES,
  NDT_NODE_IDS,
  ndtAtomicMaterialByCode,
  ndtBusinessRuleNames,
  ndtFileApprovalStatus
} from './ndtAtomicMaterials'

assert.equal(NDT_ATOMIC_MATERIALS.length, 21)
assert.deepEqual(NDT_NODE_IDS, [35, 36, 37, 38, 39, 40, 41, 42])
assert.deepEqual(ndtAtomicMaterialByCode('ndt_entrustment')?.defaultNodeIds, [37, 42])
assert.equal(ndtAtomicMaterialByCode('missing'), undefined)
assert.deepEqual(NDT_BUSINESS_RULE_NAMES, {
  35: '无损检测机构施工现场质量保证体系的实施',
  36: '无损检测方案',
  37: '检测过程中发现问题的处理',
  38: '无损检测人员资格证、执业注册证及持证合格项目',
  39: '无损检测工艺文件',
  40: '无损检测记录、报告',
  41: '射线检测底片抽查',
  42: '射线检测现场抽查'
})
assert.deepEqual(ndtBusinessRuleNames([37, 42, 37]), [
  '检测过程中发现问题的处理',
  '射线检测现场抽查'
])
assert.ok(ndtBusinessRuleNames(NDT_NODE_IDS).every((name) => !/R\d+/i.test(name)))

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
