import type { RuleDraftInput } from '@/api/aicheck/projectRules'
import type { ConditionNode, RuleConditions } from './ruleConditionModel'

const operators: Record<string, string> = {
  eq: '等于',
  ne: '不等于',
  gt: '大于',
  gte: '大于或等于',
  lt: '小于',
  lte: '小于或等于',
  in: '属于以下任一值',
  exists: '有值'
}
export const describeCondition = (node: ConditionNode): string => {
  if (node.all) return `全部成立：(${node.all.map(describeCondition).join('；')})`
  if (node.any) return `任一成立：(${node.any.map(describeCondition).join('；')})`
  if (node.not) return `不满足：(${describeCondition(node.not)})`
  const value = (item: unknown) =>
    typeof item === 'string'
      ? `“${item}”`
      : typeof item === 'boolean'
        ? item
          ? '是（布尔值）'
          : '否（布尔值）'
        : String(item ?? '未填写')
  const expected = Array.isArray(node.expected)
    ? node.expected.map(value).join('、')
    : value(node.expected)
  return `${node.field || '未选字段'} ${operators[node.operator || ''] || node.operator || '未选比较方式'} ${expected}${node.unit ? ` ${node.unit}` : ''}`
}
const describeConditions = (conditions?: RuleConditions) => {
  if (!conditions) return '未设置可执行条件'
  return [
    `适用范围：${conditions.applicability ? describeCondition(conditions.applicability) : '未设置额外限制'}`,
    ...conditions.checks.map(
      (check, index) =>
        `检查 ${index + 1}（${check.id || '未编号'}）：${describeCondition(check)}\n取代审查项：${check.atomicCheckId || '未绑定'}`
    )
  ].join('\n\n')
}
export const ruleDraftDiff = (before: RuleDraftInput, after: RuleDraftInput) =>
  [
    {
      key: 'inspectionItem',
      label: '审查项目',
      before: before.inspectionItem,
      after: after.inspectionItem
    },
    {
      key: 'standardText',
      label: '判断依据与要求',
      before: before.standardText,
      after: after.standardText
    },
    {
      key: 'witnessText',
      label: '核对方法与工作见证',
      before: before.witnessText,
      after: after.witnessText
    },
    {
      key: 'executionConditions',
      label: '可执行条件与适用范围',
      before: describeConditions(before.executionConditions),
      after: describeConditions(after.executionConditions)
    }
  ].filter((row) => row.before !== row.after)
