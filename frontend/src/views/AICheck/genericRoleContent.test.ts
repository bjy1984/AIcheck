import assert from 'node:assert/strict'
import { computed, reactive } from 'vue'
import type { RoleCode } from '@/types/aicheck'
import { genericRoleContent } from './genericRoleContent'
import { getRoleDefaultPath } from '@/utils/roleAccess'
import { handler, ref } from './workflowTestHarness'

const userStore = reactive({ getUserInfo: { role: 'owner' as RoleCode } })
const content = handler('./GenericReviewWorkbench.vue', 'roleContent', {
  computed,
  userStore,
  genericRoleContent
})
const menu = handler('./GenericReviewWorkbench.vue', 'genericShellMenuSections', {
  computed,
  roleContent: content,
  selectedProject: ref({ name: '实际项目' }),
  workbench: ref({ project: { status: '待审查' } }),
  selectedGenericView: ref('overview')
})

for (const role of ['owner', 'contractor'] as RoleCode[]) {
  userStore.getUserInfo.role = role
  assert.equal(content.value.reviewDetails, false)
  assert.deepEqual(
    menu.value[0].items.map((item: { subpage: string }) => item.subpage),
    ['overview', 'requirements', 'findings'],
    `${role} needs project, materials and findings rather than review diagnostics`
  )
  assert.equal(menu.value[0].title, '实际项目')
}
for (const role of ['inspection', 'admin'] as RoleCode[]) {
  userStore.getUserInfo.role = role
  assert.equal(content.value.reviewDetails, true)
  assert.ok(menu.value[0].items.some((item: { subpage: string }) => item.subpage === 'evidence'))
  assert.ok(menu.value[0].items.some((item: { subpage: string }) => item.subpage === 'human'))
}
assert.equal(genericRoleContent(undefined).reviewDetails, false)

const selectedView = ref('overview')
const filterState = ref('all')
const showFindings = handler('./GenericReviewWorkbench.vue', 'showFindings', {
  findingFilter: filterState,
  selectedGenericView: selectedView,
  roleContent: content,
  nextTick: async () => {},
  document: { getElementById: () => ({ scrollIntoView: () => {} }) }
})
userStore.getUserInfo.role = 'owner'
await showFindings('pending')
assert.equal(filterState.value, 'pending')
assert.equal(
  selectedView.value,
  'findings',
  'business filters retain their visible navigation item'
)
userStore.getUserInfo.role = 'inspection'
await showFindings('pending')
assert.equal(
  selectedView.value,
  'human',
  'reviewers retain their dedicated pending-review navigation'
)

const panelProps = reactive({ rightCards: [] as { title: string }[] })
const hasPanel = handler('./components/StaticPageShell.vue', 'hasRightPanel', {
  computed,
  props: panelProps
})
assert.equal(hasPanel.value, false, 'removing irrelevant content also removes its empty drawer')
panelProps.rightCards = [{ title: '当前任务的诊断' }]
assert.equal(hasPanel.value, true, 'a relevant diagnostic panel remains available')

const showDiagnostics = handler('./components/OperationTaskDrawer.vue', 'showTaskDiagnostics', {
  computed,
  userStore
})
const taskRoute = handler('./components/OperationTaskDrawer.vue', 'taskRoute', {
  userStore,
  getRoleDefaultPath
})
const taskLabels = handler('./components/OperationTaskDrawer.vue', 'taskTypeLabels', {})
const taskLabel = handler('./components/OperationTaskDrawer.vue', 'taskTypeLabel', {
  showTaskDiagnostics: showDiagnostics,
  taskTypeLabels: taskLabels
})
const elapsed = handler('./components/OperationTaskDrawer.vue', 'formatElapsed', {})
assert.equal(elapsed(undefined), '--')
assert.equal(elapsed(-1), '--')
assert.equal(elapsed(65), '1 分 5 秒')
assert.equal(elapsed(3665), '1 小时 1 分')
assert.equal(elapsed(90000), '1 天 1 小时')
for (const role of ['inspection', 'owner', 'contractor', 'ndt'] as RoleCode[]) {
  userStore.getUserInfo.role = role
  assert.equal(showDiagnostics.value, false)
  assert.equal(taskLabel('ocr_or_index'), '资料处理')
  assert.equal(taskLabel('new_worker_task'), '处理任务')
  assert.equal(
    taskRoute({ area: 'workbench', projectId: 'P 1' }),
    `/workbench/${role}?projectId=P%201`,
    'task details return to the signed-in role, including from the generic workbench'
  )
}
for (const role of ['admin', 'fde'] as RoleCode[]) {
  userStore.getUserInfo.role = role
  assert.equal(showDiagnostics.value, true)
  assert.equal(taskLabel('ocr_or_index'), 'OCR / 索引')
}
assert.equal(taskRoute({ route: '/fde/ai-runs?runId=R' }), '/fde/ai-runs?runId=R')

const structuredReview = handler('./components/FileDetailDialog.vue', 'showStructuredReview', {
  computed,
  userStore
})
const fileTab = handler('./components/FileDetailDialog.vue', 'defaultSideTab', {
  computed,
  showStructuredReview: structuredReview
})
for (const role of ['owner', 'contractor', 'ndt'] as RoleCode[]) {
  userStore.getUserInfo.role = role
  assert.equal(structuredReview.value, false)
  assert.equal(
    fileTab.value,
    'meta',
    'business users start with file status and version information'
  )
}
for (const role of ['inspection', 'admin', 'fde'] as RoleCode[]) {
  userStore.getUserInfo.role = role
  assert.equal(structuredReview.value, true)
  assert.equal(fileTab.value, 'fields', 'reviewers retain field, table and seal verification')
}
