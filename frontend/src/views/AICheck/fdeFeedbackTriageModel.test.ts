import assert from 'node:assert/strict'

import type { FdeFeedback } from '@/api/aicheck'

import {
  ROOT_CAUSE_OPTIONS,
  countBy,
  feedbackTypeLabel,
  filterRows,
  formatRatio,
  historicalRootCauses,
  rootCauseOptionsFor,
  stateTagType,
  triagePayload,
  withinWindow
} from './fdeFeedbackTriageModel'

// P12 F2：triage 页的筛选、计数、归档体都在这个模块里，页面只做渲染
const NOW = Date.parse('2026-09-07T12:00:00Z')
const row = (over: Partial<FdeFeedback>): FdeFeedback => ({
  id: 'AIFB-1',
  aiRunId: 'RUN-1',
  projectId: 'P1',
  nodeId: 24,
  feedbackType: 'rejected',
  accepted: false,
  createdAt: '2026-09-06T00:00:00Z',
  ...over
})

// 七类根因与后端 feedback_capture.AI_FEEDBACK_ROOT_CAUSES 一致
assert.deepEqual(
  ROOT_CAUSE_OPTIONS.map((option) => option.value),
  [
    'data_table',
    'rule_logic',
    'guard_downgrade',
    'evidence_extraction',
    'prompt',
    'policy',
    'external_source',
    'other'
  ]
)

// 时间窗：近 7 天、近 30 天、全部；无时间戳的行不丢
const old = row({ createdAt: '2026-07-01T00:00:00Z' })
assert.equal(withinWindow(old, 'week', NOW), false)
assert.equal(withinWindow(old, 'month', NOW), false)
assert.equal(withinWindow(old, 'all', NOW), true)
assert.equal(withinWindow(row({ createdAt: '' }), 'week', NOW), true)

// 筛选叠加根因、治理状态与时间窗；未归档视为待归因
const rows = [
  row({ id: 'a', rootCause: 'data_table' }),
  row({ id: 'b', rootCause: 'prompt', governanceState: 'triaged' }),
  row({ id: 'c', createdAt: '2026-07-01T00:00:00Z' })
]
assert.deepEqual(
  filterRows(rows, { rootCause: '', state: 'needs_triage', window: 'week' }, NOW).map(
    (item) => item.id
  ),
  ['a']
)
assert.deepEqual(
  filterRows(rows, { rootCause: 'prompt', state: '', window: 'all' }, NOW).map((item) => item.id),
  ['b']
)
assert.equal(filterRows(rows, { rootCause: '', state: '', window: 'all' }, NOW).length, 3)

// 计数与格式化
assert.deepEqual(
  countBy(
    [row({ rootCause: 'prompt' }), row({ rootCause: 'prompt' }), row({})],
    (item) => item.rootCause || 'untriaged'
  ),
  { prompt: 2, untriaged: 1 }
)
assert.equal(formatRatio({ value: 0.4567 }), '45.7%')
assert.equal(formatRatio({ value: null }), '—')
assert.equal(formatRatio(undefined), '—')
assert.equal(stateTagType('promoted_to_eval'), 'success')
assert.equal(stateTagType(undefined), 'info')
assert.equal(stateTagType('needs_adjudication'), 'warning')
assert.equal(stateTagType('needs_triage'), 'warning')
assert.equal(stateTagType('unknown_state'), 'info')

// 归档体：入评测集才是 approved_for_eval
const base = {
  rootCause: 'data_table',
  canUseForEval: false,
  canUseForTraining: false,
  adjudicationRequired: false
}
assert.equal(triagePayload(base).status, 'triaged')
assert.equal(triagePayload({ ...base, canUseForEval: true }).status, 'approved_for_eval')

// Existing records must remain selectable and submitted with their original
// classification, rather than silently converting history to the new taxonomy.
const legacy = row({ feedbackType: 'edited', rootCause: 'prompt_error' })
assert.equal(feedbackTypeLabel(legacy.feedbackType), '人工编辑')
assert.equal(feedbackTypeLabel('future_type'), '其他类型（future_type）')
assert.deepEqual(historicalRootCauses([legacy, legacy, row({ rootCause: 'prompt' })]), [
  { value: 'prompt_error', label: '提示词问题（历史分类）' }
])
const legacyOption = rootCauseOptionsFor(legacy.rootCause).find(
  (option) => option.value === 'prompt_error'
)
assert.ok(legacyOption)
assert.equal(triagePayload({ ...base, rootCause: legacyOption.value }).rootCause, 'prompt_error')
assert.equal(
  filterRows([legacy], { rootCause: 'prompt_error', state: '', window: 'all' }).length,
  1,
  'the displayed historical classification remains filterable without rewriting records'
)
assert.equal(
  rootCauseOptionsFor('future_cause').find((option) => option.value === 'future_cause')?.label,
  '其他分类（future_cause）',
  'an unknown classification remains visible and traceable'
)
assert.equal(rootCauseOptionsFor('prompt').filter((option) => option.value === 'prompt').length, 1)
