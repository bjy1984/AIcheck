import assert from 'node:assert/strict'
import { changeConditionKind, conditionKind, type ConditionNode } from './ruleConditionModel'

const original: ConditionNode = {
  id: 'AC-1',
  field: 'thickness',
  operator: 'gte',
  expected: 10,
  unit: 'mm'
}
const before = JSON.stringify(original)
const all = changeConditionKind(original, 'all')
assert.equal(conditionKind(all), 'all')
assert.deepEqual(all.all, [original])
const any = changeConditionKind(all, 'any')
assert.deepEqual(any.any, [all])
const negated = changeConditionKind(any, 'not')
assert.deepEqual(negated.not, any)
assert.equal(changeConditionKind(negated, 'not'), negated)
assert.equal(JSON.stringify(original), before)
assert.equal(conditionKind(original), 'comparison')
