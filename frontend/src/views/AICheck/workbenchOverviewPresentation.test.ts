import assert from 'node:assert/strict'
import { computed, ref } from 'vue'
import { handler } from './workflowTestHarness'

const role = ref('owner')
const activeWorkbenchSection = ref('overview')
const selectedNode = ref<{ nodeId: number; name: string; inspectionType: string } | null>({
  nodeId: 24,
  name: '焊工资格证及持证合格项目',
  inspectionType: 'B'
})
const currentNodeLabel = handler('./Workbench.vue', 'currentNodeLabel', { computed, selectedNode })
const context = { computed, role, activeWorkbenchSection, selectedNode, currentNodeLabel }
const location = handler('./Workbench.vue', 'workbenchLocationLabel', context)
const showNodeType = handler('./Workbench.vue', 'showBreadcrumbNodeType', context)

// A retained selection must not make an overview claim that the user is inside a node.
for (const overviewRole of ['owner', 'inspection']) {
  role.value = overviewRole
  activeWorkbenchSection.value = 'overview'
  assert.equal(location.value, '项目总览')
  assert.equal(showNodeType.value, false)

  activeWorkbenchSection.value = 'node'
  // 节点名字已经是页面标题，面包屑只写位置，不重复一遍
  assert.equal(location.value, '节点审查')
  assert.equal(showNodeType.value, true)

  activeWorkbenchSection.value = 'overview'
  assert.equal(location.value, '项目总览', 'returning to overview clears node location semantics')
  assert.equal(showNodeType.value, false)
}

activeWorkbenchSection.value = 'node'
selectedNode.value = null
assert.equal(location.value, '未选择节点')
assert.equal(
  showNodeType.value,
  false,
  'an empty selection must not display a fabricated node type'
)

for (const [libraryRole, label] of [
  ['contractor', '项目文件库'],
  ['ndt', '无损检测资料库']
]) {
  role.value = libraryRole
  assert.equal(location.value, label)
  assert.equal(showNodeType.value, false)
}

// 2026-11-04 起无损检测的「待提交/补正」摘要条并入 NdtWorkflowPanel 的登记数一行（手机简化稿），
// 工作台不再另算一份，见 ndtUploadedVisibility.test.ts。

console.log('Workbench overview location regressions passed')
