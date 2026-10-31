import assert from 'node:assert/strict'

import { evidenceGapNotice, evidenceGapOf, evidenceGapSummary } from './findingEvidence'

// 有引用就没有缺口
assert.equal(evidenceGapOf({ evidenceRefs: [{ fileId: 'F1' }], title: '缺少设计特性表' }), '')

// 缺项类：缺的东西没有原文可引（生产节点 12 的两条）
assert.equal(
  evidenceGapOf({
    evidenceRefs: [],
    title: '已提供阀门制造许可证，但缺少设计特性表和材料表用于覆盖性比对',
    unsupportedClaims: ['EVIDENCE_REFS_MISSING']
  }),
  'absence'
)
assert.equal(
  evidenceGapOf({ evidenceRefs: [], title: '未提供设计资料', description: '' }),
  'absence'
)
assert.equal(
  evidenceGapOf({ evidenceRefs: [], title: '核查事项', description: '无法核实许可范围能否覆盖' }),
  'absence'
)

// 给了引用但核对不过：要明说别照它采信，即使标题里也带「缺少」
assert.equal(
  evidenceGapOf({
    evidenceRefs: [],
    title: '缺少签章',
    unsupportedClaims: ['EVIDENCE_QUOTE_NOT_VERBATIM', 'EVIDENCE_REFS_MISSING']
  }),
  'citation_failed'
)
assert.equal(
  evidenceGapOf({
    evidenceRefs: [],
    title: '钢管规格与许可范围需人工复核',
    validationFailures: [{ code: 'EVIDENCE_FILE_OUTSIDE_NODE' }, { code: 'EVIDENCE_REFS_MISSING' }]
  }),
  'citation_failed'
)

// 既不是缺项、也没有引用：普通的「没附原文」
assert.equal(
  evidenceGapOf({
    evidenceRefs: [],
    title: '钢管质量证明书显示规格108×8.0，与许可证A级参数需人工复核',
    unsupportedClaims: ['EVIDENCE_REFS_MISSING']
  }),
  'no_citation'
)

// 脏数据不能崩
assert.equal(evidenceGapOf({}), 'no_citation')
assert.equal(
  evidenceGapOf({ unsupportedClaims: [3, null], validationFailures: [null, 1] }),
  'no_citation'
)

// 三种情况的措辞互不相同，缺项那条要指到「本节点所需资料」和规则依据
assert.equal(new Set(Object.values(evidenceGapSummary)).size, 3)
assert.equal(new Set(Object.values(evidenceGapNotice)).size, 3)
assert.ok(evidenceGapNotice.absence.includes('本节点所需资料'))
assert.ok(evidenceGapNotice.citation_failed.includes('不要照它的引用采信'))
