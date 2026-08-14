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
