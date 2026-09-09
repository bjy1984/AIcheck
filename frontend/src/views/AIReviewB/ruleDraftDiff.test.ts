import assert from 'node:assert/strict'
import { describeCondition, ruleDraftDiff } from './ruleDraftDiff'
import type { RuleDraftInput } from '@/api/aicheck/projectRules'
const before: RuleDraftInput = {
  inspectionItem: '厚度',
  standardText: '依据',
  witnessText: '',
  executionConditions: {
    schemaVersion: 'rule-conditions-v1',
    checks: [
      {
        id: 'C1',
        field: 'thickness',
        operator: 'gte',
        expected: 3,
        unit: 'mm',
        atomicCheckId: 'A1'
      }
    ]
  }
}
assert.deepEqual(ruleDraftDiff(before, structuredClone(before)), [])
const after = structuredClone(before)
after.executionConditions!.checks[0].expected = '3'
assert.equal(ruleDraftDiff(before, after).length, 1)
assert.notEqual(ruleDraftDiff(before, after)[0].before, ruleDraftDiff(before, after)[0].after)
after.executionConditions!.checks[0].atomicCheckId = 'A2'
assert.match(ruleDraftDiff(before, after)[0].after, /A2/)
after.executionConditions!.applicability = {
  not: { any: [{ field: 'grade', operator: 'in', expected: ['A', 'B'] }] }
}
assert.match(ruleDraftDiff(before, after)[0].after, /不满足：\(任一成立/)
assert.match(
  describeCondition({ field: 'accepted', operator: 'eq', expected: false }),
  /否（布尔值）/
)
assert.match(
  ruleDraftDiff(before, { ...before, executionConditions: undefined })[0].after,
  /未设置可执行条件/
)
assert.equal(before.executionConditions!.checks[0].expected, 3)
