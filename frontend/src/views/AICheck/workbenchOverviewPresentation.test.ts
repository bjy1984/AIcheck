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
  assert.equal(location.value, '24. 焊工资格证及持证合格项目')
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

const nodePackage = ref({
  projectFiles: [
    { materialCategory: '无损检测资料', materialTypeCode: 'report', status: '待提交' },
    { materialCategory: '无损检测资料', materialTypeCode: 'report', status: '已提交' },
    { materialCategory: '无损检测资料', materialTypeCode: 'film', status: '需补正' },
    { materialCategory: '施工资料', materialTypeCode: 'report', status: '待提交' }
  ]
})
const ndtFeedback = ref([{ status: '待补正' }, { status: '已关闭' }])
const workbenchAuditCards = handler('./Workbench.vue', 'workbenchAuditCards', {
  computed,
  role,
  nodePackage,
  ndtFeedback,
  currentProject: ref({ name: '测试项目' }),
  documentBindingSummary: (file: { status: string }) => file.status
})
const summary = handler('./Workbench.vue', 'ndtSubmissionSummary', {
  computed,
  workbenchAuditCards
})
assert.deepEqual(
  summary.value.map((item: { label: string; value: string | number }) => [item.label, item.value]),
  [
    ['已上传文件', '3 份'],
    ['待提交/补正', 2],
    ['监检反馈', '1 项']
  ],
  'the compact summary retains NDT-only counts and omits duplicate project context'
)
assert.equal(summary.value[0].hint, '2 种资料类型')
assert.equal(summary.value[1].actionKey, 'ndt-pending')
assert.equal(summary.value[1].actionLabel, '查看待处理文件')

nodePackage.value.projectFiles.forEach((file) => (file.status = '已提交'))
ndtFeedback.value[0].status = '已关闭'
assert.equal(summary.value[1].value, 0)
assert.equal(
  summary.value[1].actionKey,
  undefined,
  'no pending action is fabricated for zero files'
)
assert.equal(summary.value[2].value, '0 项')

console.log('Workbench overview location and compact NDT summary regressions passed')
