import assert from 'node:assert/strict'
import { approvalLabel, approvalMessage, approvalStatus } from './approvalPresentation'
assert.equal(approvalLabel({ code: 'r11_signature_审核_unresolved' }), '审核签名记录')
assert.equal(approvalLabel({ code: 'constructor' }), '签批核对事项')
assert.match(
  approvalMessage({ code: 'r11_owner_approval_before_use', result: 'failed' }),
  /先采用、后批复/
)
assert.match(approvalMessage({ code: 'r11_signature_审批', result: 'failed' }), /未签名/)
assert.match(approvalMessage({ code: 'r11_owner_reply', result: 'failed' }), /拒绝/)
assert.match(
  approvalMessage({ code: 'r11_signature_审核', result: 'evidence_insufficient' }),
  /不一定是缺文件/
)
assert.match(
  approvalMessage({ code: 'r11_usage_inventory', result: 'evidence_insufficient' }),
  /重复项/
)
assert.equal(approvalStatus('unknown'), '待核对')
