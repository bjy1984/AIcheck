import assert from 'node:assert/strict'
import {
  adminOverviewSections,
  missingAdminSections,
  adminCountLabel,
  adminValidationState,
  confidenceValue,
  productionTemplateLocked,
  promptDraftFrom,
  templatePublishMessage,
  loadTemplatePublishCandidates,
  adminRecordScopes,
  adminTargetPage
} from './adminOperationPolicy'

assert.deepEqual(adminOverviewSections('rule'), ['ruleVersions'])
assert.deepEqual(adminOverviewSections('material-review-point'), ['materialReviewPoints'])
for (const tab of ['permission', 'org', 'audit', 'prompt-template', 'fine-config']) {
  assert.deepEqual(adminOverviewSections(tab), ['core'])
}
assert.deepEqual(missingAdminSections('rule', ['ruleVersions', 'materialReviewPoints']), [
  'ruleVersions'
])
assert.deepEqual(missingAdminSections('rule', ['materialReviewPoints']), [])
assert.equal(adminCountLabel(0, false), '未获取')
assert.equal(adminCountLabel(0, true), '0')
assert.equal(adminCountLabel(undefined, true), '未获取')
assert.equal(adminValidationState({ loading: false, ok: null }).type, 'info')
assert.equal(
  adminValidationState({ loading: false, ok: true, error: 'Request failed' }).type,
  'danger'
)
assert.equal(adminValidationState({ loading: true, ok: true }).type, 'info')
assert.equal(adminValidationState({ loading: false, ok: true }).type, 'success')
assert.equal(confidenceValue(0, 0.85), 0)
assert.equal(confidenceValue('0', 0.65), 0)
assert.equal(confidenceValue(undefined, 0.65), 0.65)
assert.equal(confidenceValue(NaN, 0.85), 0.85)

const original = {
  id: 'P1',
  name: 'Evidence review',
  version: 'v1',
  status: 'production',
  etag: 'e1',
  businessPackId: 'pack',
  promptKey: 'review',
  systemPrompt: 'Keep evidence'
}
const draft = promptDraftFrom(original)
assert.equal(draft.id, '')
assert.equal(draft.etag, '')
assert.equal(draft.status, 'draft')
assert.equal(draft.systemPrompt, original.systemPrompt)
assert.equal(original.status, 'production')
assert.ok(productionTemplateLocked('已发布'))
assert.ok(!productionTemplateLocked(draft.status))
const confirmation = templatePublishMessage('Prompt', { ...draft, id: 'P2' }, [
  original,
  { ...original, id: 'other', promptKey: 'other', name: 'Unrelated' }
])
assert.match(confirmation, /Evidence review.*v1-draft.*P2/)
assert.match(confirmation, /将替代：.*Evidence review.*v1.*P1/)
assert.ok(!confirmation.includes('Unrelated'))
assert.deepEqual(adminRecordScopes('prompt-template'), [])
assert.deepEqual(adminRecordScopes('fine-config'), [])
assert.deepEqual(
  adminRecordScopes('permission').map((item) => item.value),
  ['permission', 'node-template']
)
assert.deepEqual(
  adminRecordScopes('rule').map((item) => item.value),
  ['rule', 'workflow']
)
const rows = Array.from({ length: 15 }, (_, index) => ({ id: String(index) }))
assert.equal(adminTargetPage(rows, '12', 10)?.page, 2)
assert.equal(adminTargetPage(rows, '12', 10)?.row, rows[12])
assert.equal(adminTargetPage(rows, 'missing', 10), null)

// More than one page of history must not permanently block publication.
const pagedTemplates = Array.from({ length: 205 }, (_, index) => ({
  ...original,
  id: `history-${index}`,
  status: index === 204 ? 'production' : 'retired'
}))
const pageCalls: number[] = []
const candidates = await loadTemplatePublishCandidates(async (page, pageSize) => {
  pageCalls.push(page)
  return {
    data: {
      items: pagedTemplates.slice((page - 1) * pageSize, page * pageSize),
      total: pagedTemplates.length
    }
  }
})
assert.deepEqual(pageCalls, [1, 2, 3])
assert.equal(candidates.length, 205)
assert.match(
  templatePublishMessage('Prompt', { ...draft, id: 'new-version' }, candidates),
  /history-204/
)
await assert.rejects(
  loadTemplatePublishCandidates(async () => undefined),
  /加载失败/
)
await assert.rejects(
  loadTemplatePublishCandidates(async () => ({ data: { items: [original], total: 2 } })),
  /分页未返回/
)
await assert.rejects(
  loadTemplatePublishCandidates(async (page) => ({
    data: { items: [original], total: page === 1 ? 2 : 3 }
  })),
  /发生变化/
)
