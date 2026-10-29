import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { handler } from './workflowTestHarness'

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
const cards = handler('./components/WorkbenchRoleStaticSections.vue', 'ownerMetricCards', {
  computed,
  props,
  reportArchiveUnavailable: { value: false },
  reportArchiveEmptyLabel: { value: '待加载' }
})
assert.deepEqual(
  cards.value.map((card: any) => card.label),
  ['总体进度', '报告版本', '归档资料']
)
assert.deepEqual(
  cards.value.map((card: any) => card.value),
  ['50%', 1, 2]
)
props.metrics = [{ key: 'token', label: 'Token 消耗', value: 987654 }]
assert.deepEqual(
  cards.value.map((card: any) => card.label),
  ['总体进度', '报告版本', '归档资料']
)
assert.equal(
  cards.value[0].value,
  '—',
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
const ownerSections = readFileSync(
  new URL('./components/WorkbenchRoleStaticSections.vue', import.meta.url),
  'utf8'
)
  .split(`<template v-else-if="role === 'owner'">`)[1]
  .split(`<template v-else-if="role === 'inspection'">`)[0]
assert.doesNotMatch(ownerSections, /reviewSteps|aiConfidence|Prompt|业务审查链路|强制限制/)
assert.match(ownerSections, /ownerNodeRows/)
assert.match(ownerSections, /retry-report-archive/)
assert.doesNotMatch(
  workbench,
  /<WorkbenchSidePanel|<WorkbenchRightStaticDetails|<RoleContextPanel/,
  'owner must not mount the shared engineering/AI sidebar'
)
assert.match(workbench, /<NodePackagePanel\s+:show-technical-status="false"/)
assert.match(workbench, /<ReportArchivePanel/)
assert.ok(
  workbench.indexOf('<ReportArchivePanel') < workbench.indexOf('<NodePackagePanel'),
  'owner reports and archives precede detailed node material tables'
)
assert.match(workbench, /<details v-if="role === 'owner'" class="card owner-node-documents">/)
assert.doesNotMatch(
  workbench,
  /<details[^>]*owner-node-documents[^>]*\sopen(?:\s|>)/,
  'node material details should not push owner reports below the fold by default'
)
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
