import assert from 'node:assert/strict'
import { buildReturnCorrectionPayload, createReturnCorrectionDraft } from './returnCorrection'

const submittedBindings = [
  { id: 'BIND-1', fileName: '许可证.pdf', bindingStatus: '已提交' as const },
  { id: 'BIND-2', fileName: '人员证明.pdf', bindingStatus: '已提交' as const }
]
const missingRequirements = [
  {
    id: 'REQ-1',
    nodeId: 1,
    name: '设计单位许可证',
    requiredType: '必传' as const,
    matchedBindingCount: 0,
    matchedFileNames: [],
    fulfilled: false
  }
]

const returnDraft = createReturnCorrectionDraft(
  submittedBindings,
  missingRequirements,
  '许可证范围不一致'
)
assert.equal(returnDraft.mode, 'return_correction')
assert.deepEqual(returnDraft.selectedBindingIds, ['BIND-1', 'BIND-2'])
assert.equal(returnDraft.reason, '许可证范围不一致')

returnDraft.selectedBindingIds = ['BIND-2']
assert.deepEqual(
  buildReturnCorrectionPayload(returnDraft, submittedBindings, missingRequirements),
  {
    mode: 'return_correction',
    reason: '许可证范围不一致',
    opinion: '许可证范围不一致',
    bindingIds: ['BIND-2'],
    evidenceLinkIds: [],
    supplementRequirements: []
  }
)

const supplementDraft = createReturnCorrectionDraft([], missingRequirements, '')
assert.equal(supplementDraft.mode, 'supplement_request')
assert.deepEqual(supplementDraft.selectedRequirementIds, ['REQ-1'])
supplementDraft.reason = '请补充缺失资料'
supplementDraft.manualRequirementsText = '项目负责人授权书\n  设计说明书  \n'
assert.deepEqual(buildReturnCorrectionPayload(supplementDraft, [], missingRequirements), {
  mode: 'supplement_request',
  reason: '请补充缺失资料',
  opinion: '请补充缺失资料',
  bindingIds: [],
  evidenceLinkIds: [],
  supplementRequirements: [
    { id: 'REQ-1', source: 'system', name: '设计单位许可证' },
    { id: 'MANUAL-1', source: 'manual', name: '项目负责人授权书' },
    { id: 'MANUAL-2', source: 'manual', name: '设计说明书' }
  ]
})

const emptyDraft = createReturnCorrectionDraft([], [], '请补充资料')
assert.throws(
  () => buildReturnCorrectionPayload(emptyDraft, [], []),
  /至少选择或填写一项需要提交的资料/
)

console.log('Review B return correction behavior passed')

// ── 补充资料单：给施工方看的东西，不能是给引擎看的码 ──────────────
//
// 实操所见（2026-08-15，监检点「退回补正」）：
//
//   需要提交的资料： design_license  design_document  design_document
//
// 两个问题：
//   1. 列的是资料类型码。这是规则引擎比对用的，而这张单子是发给施工方的——
//      收到「请补交 design_document」，没人知道该交什么；
//   2. design_document 出现两次，两项同名同码、勾选框也是两个。
//      同一资料类型对应多个审查点是正常的，但「要交什么」只该出现一次。
//
// 后端其实同时发了 materialTypeName / reviewContent，只是没被用上。
import { readFileSync as _readFileSync } from 'node:fs'
import { fileURLToPath as _fileURLToPath } from 'node:url'

const dialog = _readFileSync(
  _fileURLToPath(new URL('./components/ReturnCorrectionDialog.vue', import.meta.url)),
  'utf8'
)

assert.ok(dialog.includes('const requirementLabel'), '缺失资料还在直接显示码')
assert.ok(/materialTypeName/.test(dialog), '没有优先用中文名')
assert.ok(dialog.includes('const visibleRequirements'), '没有按资料类型去重')

// 去重必须贯穿到草稿与提交——只改显示的话，被隐藏那条仍在勾选集合里，
// 生成的单子上照样出现两次，去重就只是障眼法
assert.ok(
  /createReturnCorrectionDraft\(\s*props\.bindings,\s*visibleRequirements\.value/.test(dialog),
  '默认勾选还在用未去重的清单'
)
assert.ok(
  /buildReturnCorrectionPayload\(draft\.value, props\.bindings, visibleRequirements\.value\)/.test(
    dialog
  ),
  '提交时还在用未去重的清单'
)

console.log('Supplement requirement label & dedupe contract passed')
