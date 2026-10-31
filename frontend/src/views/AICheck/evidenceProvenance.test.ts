import assert from 'node:assert/strict'

import { evidenceStatusView, evidenceTypeText, isSystemLinked } from './evidenceProvenance'

// 系统自动挂的：不能再画成绿色「已确认」
const auto = {
  manualStatus: 'confirmed',
  manualStatusLabel: '已确认',
  source: 'material_targeting',
  confirmedByName: '系统自动打靶'
}
assert.equal(isSystemLinked(auto), true)
assert.deepEqual(
  { label: evidenceStatusView(auto).label, tagType: evidenceStatusView(auto).tagType },
  { label: '系统挂接', tagType: 'info' }
)
assert.ok(evidenceStatusView(auto).hint.includes('还没有人工核对'))
// 只认 confirmedByName 也算（来源字段缺失的旧数据）
assert.equal(isSystemLinked({ manualStatus: 'confirmed', confirmedByName: '系统自动打靶' }), true)

// 人工确认的：写清是谁
assert.deepEqual(
  {
    label: evidenceStatusView({ manualStatus: 'confirmed', confirmedByName: '张工' }).label,
    tagType: evidenceStatusView({ manualStatus: 'confirmed', confirmedByName: '张工' }).tagType
  },
  { label: '已确认 · 张工', tagType: 'success' }
)
// 人工挂载整份资料（manual_binding）也是人做的
assert.equal(
  evidenceStatusView({
    manualStatus: 'confirmed',
    source: 'manual_binding',
    confirmedByName: '李工'
  }).label,
  '已确认 · 李工'
)
assert.equal(isSystemLinked({ manualStatus: 'confirmed', source: 'manual_binding' }), false)
// 没写人名时退回「已确认」
assert.equal(evidenceStatusView({ manualStatus: 'confirmed' }).label, '已确认')

// 没确认的：照旧
assert.deepEqual(
  evidenceStatusView({ manualStatus: 'pending', manualStatusLabel: '待确认' }).label,
  '待确认'
)
assert.equal(evidenceStatusView({}).label, '候选')
assert.equal(evidenceStatusView({ manualStatus: 'pending' }).tagType, 'warning')
// 系统挂的但被人驳回了，不能再叫系统挂接
assert.equal(isSystemLinked({ manualStatus: 'rejected', source: 'material_targeting' }), false)

// 证据类型：不再把内部类型名甩给监检
assert.equal(evidenceTypeText({ id: 'EV-1', objectType: 'nodeEvidenceLink' }), '节点证据')
assert.equal(evidenceTypeText({ id: 'EV-2', objectType: 'documentVersion' }), '资料文件')
assert.equal(evidenceTypeText({ id: 'EV-3', objectType: 'extractedField' }), 'OCR 字段')
assert.equal(evidenceTypeText({ id: 'EV-4', objectType: 'knowledgeClause' }), '标准条款')
assert.equal(evidenceTypeText({ id: 'AIREF-DV-1-1-abc', objectType: 'documentVersion' }), 'AI 引用')
// 没有类型或没见过的类型：退回「节点证据」，不显示原词
assert.equal(evidenceTypeText({ id: 'EV-5' }), '节点证据')
assert.equal(evidenceTypeText({ id: 'EV-6', objectType: 'somethingNew' }), '节点证据')
assert.equal(evidenceTypeText(undefined), '节点证据')
