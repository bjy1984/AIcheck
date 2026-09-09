export type ConditionValue = string | number | boolean
export interface ConditionNode {
  id?: string
  field?: string
  operator?: string
  expected?: ConditionValue | ConditionValue[]
  unit?: string
  all?: ConditionNode[]
  any?: ConditionNode[]
  not?: ConditionNode
}
export interface RuleConditions {
  schemaVersion: 'rule-conditions-v1'
  checks: ConditionNode[]
  applicability?: ConditionNode
}
export const newCondition = (): ConditionNode => ({
  id: `condition-${crypto.randomUUID()}`,
  field: '',
  operator: 'eq',
  expected: ''
})
export const conditionKind = (node: ConditionNode) =>
  node.all ? 'all' : node.any ? 'any' : node.not ? 'not' : 'comparison'
export const changeConditionKind = (node: ConditionNode, kind: string): ConditionNode => {
  if (kind === conditionKind(node)) return node
  if (kind === 'all') return { all: [node] }
  if (kind === 'any') return { any: [node] }
  if (kind === 'not') return { not: node }
  return newCondition()
}
