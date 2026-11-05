import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { handler } from './workflowTestHarness'
import { ownerProgress } from './ownerHome'

const computed = (fn: () => unknown) => ({
  get value() {
    return fn()
  }
})
const props = {
  metrics: [
    { key: 'token', label: 'Token 消耗', value: 987654 },
    { key: 'progress', label: '总体进度', value: '50%' },
    { key: 'latency', label: '推理耗时', value: '80ms' },
    { key: 'report', label: '报告版本', value: 999 },
    { key: 'archive', label: '归档资料', value: 999 }
  ],
  reports: [{ id: 'R1' }],
  archiveItems: [{ id: 'A1' }, { id: 'A2' }]
}
// 建设方首页的进度只认业务进度：接口只给技术指标（Token、耗时）时显示「—」，不编一个进度
assert.deepEqual(ownerProgress(props.metrics), { label: '50%', percent: 50 })
assert.deepEqual(
  ownerProgress([{ key: 'token', label: 'Token 消耗', value: 987654 }]),
  { label: '—', percent: 0 },
  'technical-only payload must not fabricate business progress'
)

const executionSummary = handler(
  '../AIReviewB/ConversationalReviewWorkbenchB.vue',
  'executionSummary',
  {
    computed,
    runLooksStalled: { value: false },
    sending: { value: false },
    reviewStarting: { value: false },
    latestAssistantExecution: {
      value: { mode: 'llm_agent', model: 'PRIVATE_MODEL', toolCallCount: 99 }
    }
  }
)
assert.equal(
  executionSummary.value,
  '本轮回复已完成，请结合原文核验。',
  'a completed reply does not establish that document verification passed'
)

const messageLabel = handler(
  '../AIReviewB/ConversationalReviewWorkbenchB.vue',
  'messageExecutionLabel',
  {}
)
assert.equal(
  messageLabel({
    role: 'assistant',
    execution: {
      mode: 'llm_agent',
      provider: 'PRIVATE_PROVIDER',
      model: 'MODEL_ID',
      toolCallCount: 99,
      usage: { totalTokens: 10000 }
    }
  }),
  '',
  'routine replies must not append provider, model or tool metrics'
)
assert.equal(messageLabel({ role: 'assistant', execution: { mode: 'deterministic_command' } }), '')
assert.match(
  messageLabel({ role: 'assistant', execution: { mode: 'deterministic_fallback' } }),
  /重新提问|人工核验/,
  'removing technical metadata must retain an actionable incomplete-answer warning'
)
assert.equal(messageLabel({ role: 'user', execution: { mode: 'deterministic_fallback' } }), '')

const workbench = readFileSync(new URL('./Workbench.vue', import.meta.url), 'utf8')
const ownerHome = readFileSync(
  new URL('./components/OwnerProjectHome.vue', import.meta.url),
  'utf8'
)
assert.doesNotMatch(ownerHome, /reviewSteps|aiConfidence|Prompt|业务审查链路|强制限制/)
assert.doesNotMatch(ownerHome, /<ElTable/, '建设方首页不用表格：手机上要横滑')
assert.match(ownerHome, /retryReportArchive/)
assert.match(workbench, /<OwnerProjectHome\s+v-if="role === 'owner'"/)
assert.doesNotMatch(
  workbench,
  /<WorkbenchSidePanel|<WorkbenchRightStaticDetails|<RoleContextPanel/,
  'owner must not mount the shared engineering/AI sidebar'
)
assert.match(workbench, /<NodePackagePanel\s+:show-technical-status="false"/)
// 节点资料点进节点才看（抽屉），不在首页把报告挤到下面去
assert.match(workbench, /<ElDrawer\s+v-if="role === 'owner'"\s+v-model="ownerNodeOpen"/)
const conversation = readFileSync(
  new URL('../AIReviewB/ConversationalReviewWorkbenchB.vue', import.meta.url),
  'utf8'
)
assert.doesNotMatch(conversation, /messageTokenUsageLabel|formatReviewTokenUsage/)
assert.match(conversation, /<details v-if="!props.embedded" class="judgment-record">/)
assert.match(conversation, /block.type === 'reasoning' && !props.embedded/)
assert.match(
  conversation,
  /@open-evidence="openEvidence"/,
  'business evidence remains available while runtime details are removed'
)

assert.ok(
  conversation.includes('资料就绪状态和历史审查任务。'),
  'welcome copy uses the business task name'
)

console.log('Role-focused business content and meaningful review feedback passed')
