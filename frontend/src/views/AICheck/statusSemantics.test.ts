import assert from 'node:assert/strict'
import { computed, ref } from 'vue'
import { getStatusTagType, getStatusTone, getStatusIcon } from './components/status'
import { handler } from './workflowTestHarness'
import type { ProjectStatus, NodeStatus } from '@/types/aicheck'

// A pending release is not a successful release; negative labels must not
// inherit the positive word that happens to be contained in their text.
assert.equal(getStatusTagType('待发布'), 'warning')
assert.equal(getStatusTagType('已发布'), 'success')
assert.equal(getStatusTagType('未发布'), 'info')
assert.equal(getStatusTagType('未通过'), 'danger')
assert.equal(getStatusTagType('未完成'), 'info')
assert.equal(getStatusTagType('已完成'), 'success')
assert.equal(getStatusTagType('未启用'), 'info')
assert.equal(getStatusTagType('已停用'), 'info')
assert.equal(getStatusTagType('上传成功'), 'success')
assert.equal(getStatusTagType('上传未成功'), 'info')
assert.equal(getStatusTagType('识别失败'), 'danger')
assert.equal(getStatusTagType('失败重新上传'), 'danger')

// The same state drives text labels, charts and status icons across workspaces.
assert.equal(getStatusTone('待人工确认'), 'orange')
assert.equal(getStatusTone('needs_adjudication'), 'orange')
assert.equal(getStatusTone('需补正'), 'red')
assert.equal(getStatusTone('运行中'), 'blue')
assert.equal(getStatusTone('排队中'), 'blue')
assert.equal(getStatusTagType('ready_for_eval'), 'primary')
assert.equal(getStatusTagType('promoted_to_eval'), 'success')
assert.equal(getStatusTagType('blocked_by_gate'), 'danger')
assert.equal(getStatusTagType('failed_to_start'), 'danger')
assert.equal(getStatusTagType('needs_human_review'), 'warning')
assert.equal(getStatusTagType('approved_for_eval'), 'primary')
assert.equal(getStatusTagType('production_approved'), 'success')
assert.notEqual(getStatusIcon('待发布'), getStatusIcon('已发布'))
assert.notEqual(getStatusIcon('未获取'), getStatusIcon('失败'))

// Only known API values get semantic colour. New values and descriptive prose
// cannot accidentally become a success or a failure through substring matching.
assert.equal(getStatusTagType(' PENDING-PUBLISH '), 'warning')
assert.equal(getStatusTagType('IN PROGRESS'), 'primary')
assert.equal(getStatusTagType('not_completed'), 'info')
assert.equal(getStatusTagType('unhealthy'), 'danger')
assert.equal(getStatusTagType('新规则尚未发布成功'), 'info')
assert.equal(getStatusTagType('future_status'), 'info')
assert.equal(getStatusTagType('未获取'), 'info')
assert.equal(getStatusTagType(), 'info')

// Cover the actual project/node contract, including the API's spaced AI label.
const projectTones: Record<ProjectStatus, string> = {
  '草稿/立项中': 'gray',
  资料提交中: 'blue',
  'AI 预审中': 'blue',
  监检审查中: 'blue',
  退回补正中: 'red',
  '报告生成/复核中': 'blue',
  已归档: 'green'
}
const nodeTones: Record<NodeStatus, string> = {
  待提交: 'orange',
  部分提交: 'orange',
  已提交: 'orange',
  'AI 预审中': 'blue',
  待审查: 'orange',
  待人工确认: 'orange',
  需补正: 'red',
  补正中: 'red',
  复审中: 'blue',
  已通过: 'green',
  '报告生成/复核中': 'blue',
  已归档: 'green'
}
for (const [status, expected] of Object.entries({ ...projectTones, ...nodeTones })) {
  assert.equal(getStatusTone(status), expected, status)
}
assert.equal(getStatusTagType('AI   预审中'), 'primary')
assert.equal(getStatusTagType('AI 未完成'), 'info')

const overviewError = ref('')
const loading = ref(false)
const ruleDataAvailable = ref(false)
const pendingRuleCount = ref<number | null>(null)
const runtimeTone = handler('./AdminOverview.vue', 'adminRuntimeStatusTone', {
  computed,
  overviewError,
  loading,
  ruleDataAvailable,
  pendingRuleCount
})
assert.equal(runtimeTone.value, 'gray')
loading.value = true
assert.equal(runtimeTone.value, 'blue')
loading.value = false
ruleDataAvailable.value = true
pendingRuleCount.value = 1
assert.equal(runtimeTone.value, 'orange')
pendingRuleCount.value = 0
assert.equal(runtimeTone.value, 'green')
overviewError.value = '加载失败'
assert.equal(runtimeTone.value, 'red')

const auditIntegrity = ref<any>({
  status: 'verified',
  failures: [],
  chainedEventCount: 1,
  legacyUnverifiedEventCount: 1,
  coverageStatus: 'legacy_unverified'
})
const integrityAlert = handler('./AdminOverview.vue', 'auditIntegrityAlert', {
  computed,
  auditIntegrity
})
assert.equal(integrityAlert.value.type, 'warning')
assert.match(integrityAlert.value.title, /尚未封存/)
auditIntegrity.value = { ...auditIntegrity.value, status: 'tampered', failures: ['broken hash'] }
assert.equal(integrityAlert.value.type, 'error')
assert.match(integrityAlert.value.description, /停止签发和归档/)
console.log('status semantics regressions passed')
