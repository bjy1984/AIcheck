import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const workbenchSource = readFileSync(new URL('./Workbench.vue', import.meta.url), 'utf8')
const apiSource = readFileSync(new URL('../../api/aicheck/index.ts', import.meta.url), 'utf8')
const actionBarSource = readFileSync(
  new URL('./components/WorkbenchActionBar.vue', import.meta.url),
  'utf8'
)
const submissionDialogSource = readFileSync(
  new URL('./components/SubmissionBatchDialog.vue', import.meta.url),
  'utf8'
)
const mockSource = readFileSync(
  new URL('../../../mock/aicheck/index.mock.ts', import.meta.url),
  'utf8'
)

assert.match(workbenchSource, /getInspectionSubmittedDocumentsApi/)
assert.match(workbenchSource, /已提交审查资料/)
assert.match(workbenchSource, /label="提交审查时间"/)
assert.match(workbenchSource, /row\.submittedAt/)
assert.match(workbenchSource, /binding\.bindingStatus === '已提交'/)
assert.match(workbenchSource, /bindingIds: submittedBindingIds/)
assert.match(mockSource, /inspection\\\/submitted-documents/)
assert.match(mockSource, /SUBMISSION_WITHDRAW_NOT_ALLOWED/)
assert.doesNotMatch(workbenchSource, /currentVersion\?\.uploadTime \|\| file\.updatedAt/)
assert.doesNotMatch(workbenchSource, /withdrawSubmissionItemsApi/)
assert.doesNotMatch(apiSource, /withdrawSubmissionItemsApi/)
assert.doesNotMatch(actionBarSource, /submission:withdraw/)
assert.doesNotMatch(actionBarSource, /撤回未提交/)
assert.doesNotMatch(submissionDialogSource, /撤回未提交项/)
assert.doesNotMatch(mockSource, /binding\.actions = \['submission:draft', 'submission:submit'/)

console.log('inspection submitted document UI contract passed')
