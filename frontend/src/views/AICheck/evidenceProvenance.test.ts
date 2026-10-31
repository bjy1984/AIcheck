import assert from 'node:assert/strict'

import { evidenceStatusView, isSystemLinked } from './evidenceProvenance'

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
