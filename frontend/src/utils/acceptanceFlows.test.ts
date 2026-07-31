import assert from 'node:assert/strict'

import type { DocumentAsset, NodeFileBinding } from '@/types/aicheck'
import {
  buildDocumentSubmissionPayload,
  documentBindingSummary,
  resolveNdtMaterialAction,
  submittableDocumentBindings
} from './acceptanceFlows'

const binding = (
  id: string,
  nodeId: number,
  bindingStatus: NodeFileBinding['bindingStatus']
): NodeFileBinding => ({
  id,
  projectId: 'QX201903S-13-Y',
  nodeId,
  requirementId: `REQ-${nodeId}-01`,
  requirementName: `R${nodeId} 测试资料`,
  documentId: 'DOC-ACCEPTANCE-001',
  documentVersionId: 'DOCVER-ACCEPTANCE-001',
  fileName: 'TEST-ACCEPTANCE-001_多节点测试资料.xlsx',
  versionNo: 'V1',
  usage: '原始提交',
  sourceOrgName: '中石化第五建设有限公司',
  bindingStatus,
  boundAt: '2026-07-31 12:00:00',
  actions: ['submission:submit', 'submission:withdraw']
})

const documentWithBindings = (bindings: NodeFileBinding[]): DocumentAsset => ({
  id: 'DOC-ACCEPTANCE-001',
  projectId: 'QX201903S-13-Y',
  fileName: 'TEST-ACCEPTANCE-001_多节点测试资料.xlsx',
  fileType: 'xlsx',
  materialTypeCode: 'quality_system_document',
  materialCategory: '质量体系资料',
  sourceOrgName: '中石化第五建设有限公司',
  uploaderName: '李工',
  currentVersionId: 'DOCVER-ACCEPTANCE-001',
  fileStatus: '已上传',
  currentOcrStatus: '排队中',
  sliceStatus: '未切片',
  vectorStatus: '未向量化',
  bindings,
  primaryBinding: bindings[0] || null,
  updatedAt: '2026-07-31 12:00:00',
  actions: ['file:view', 'submission:submit']
})

assert.equal(resolveNdtMaterialAction('底片与影像资料', 'register'), 'register-film')
assert.equal(resolveNdtMaterialAction('底片与影像资料', 'upload'), 'upload-material')
assert.equal(resolveNdtMaterialAction('检测报告', 'upload'), 'upload-report')
assert.equal(resolveNdtMaterialAction('问题处理闭环', 'rectify'), 'feedback')

const mixedFile = documentWithBindings([
  binding('B-R21', 21, '草稿挂载'),
  binding('B-R24', 24, '已提交'),
  binding('B-R69', 69, '需补正')
])

assert.equal(documentBindingSummary(mixedFile), '需补正')
assert.deepEqual(
  submittableDocumentBindings(mixedFile).map((item) => item.id),
  ['B-R21', 'B-R69']
)
assert.deepEqual(buildDocumentSubmissionPayload(mixedFile), {
  nodeIds: [21, 69],
  bindingIds: ['B-R21', 'B-R69']
})
assert.equal(buildDocumentSubmissionPayload(documentWithBindings([])), undefined)
assert.equal(documentBindingSummary(documentWithBindings([])), '未关联')
assert.equal(documentBindingSummary(documentWithBindings([binding('B-R21', 21, '草稿挂载')])), '待提交')
assert.equal(documentBindingSummary(documentWithBindings([binding('B-R21', 21, '已提交')])), '审核中')
assert.equal(documentBindingSummary(documentWithBindings([binding('B-R21', 21, '已通过')])), '已通过')

const duplicateNodeFile = documentWithBindings([
  binding('B-R21-A', 21, '草稿挂载'),
  binding('B-R21-B', 21, '需补正'),
  binding('B-R69', 69, '草稿挂载')
])
assert.deepEqual(buildDocumentSubmissionPayload(duplicateNodeFile), {
  nodeIds: [21, 69],
  bindingIds: ['B-R21-A', 'B-R21-B', 'B-R69']
})
