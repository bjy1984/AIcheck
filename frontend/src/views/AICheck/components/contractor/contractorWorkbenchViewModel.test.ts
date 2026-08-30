import assert from 'node:assert/strict'

import type { DocumentAsset, NodeFileBinding, RectificationItem } from '@/types/aicheck'
import {
  buildContractorWorkbenchModel,
  contractorStatusFilterOptions,
  resolveContractorSummaryTarget,
  sortContractorFeedback
} from './contractorWorkbenchViewModel'

const makeBinding = (
  id: string,
  documentId: string,
  bindingStatus: NodeFileBinding['bindingStatus']
): NodeFileBinding => ({
  id,
  projectId: 'P-1',
  nodeId: 16,
  documentId,
  documentVersionId: `${documentId}-V1`,
  fileName: `${documentId}.pdf`,
  versionNo: 'V1',
  usage: '原始提交',
  sourceOrgName: '施工单位',
  bindingStatus,
  boundAt: '2026-08-20 09:00:00',
  actions: []
})

const makeFile = (
  id: string,
  updatedAt: string,
  bindings: NodeFileBinding[] = [],
  overrides: Partial<DocumentAsset> = {}
): DocumentAsset => ({
  id,
  projectId: 'P-1',
  fileName: `${id}.pdf`,
  fileType: 'PDF',
  materialCategory: '材料证明与复验',
  materialCategorySource: 'auto',
  sourceOrgName: '施工单位',
  uploaderName: '李工',
  currentVersionId: `${id}-V1`,
  fileStatus: '已上传',
  currentOcrStatus: '已识别',
  sliceStatus: '已切片',
  vectorStatus: '已向量化',
  bodyUploaded: true,
  bindings,
  updatedAt,
  actions: [],
  ...overrides
})

const files = [
  makeFile('DOC-PENDING', '2026-08-20 10:05:00', [
    makeBinding('B-PENDING', 'DOC-PENDING', '草稿挂载')
  ]),
  makeFile('DOC-REVIEWING', '2026-08-20 10:04:00', [
    makeBinding('B-REVIEWING', 'DOC-REVIEWING', '已提交')
  ]),
  makeFile('DOC-CORRECTION', '2026-08-20 10:03:00', [
    makeBinding('B-CORRECTION', 'DOC-CORRECTION', '需补正')
  ]),
  makeFile('DOC-PASSED', '2026-08-20 10:02:00', [makeBinding('B-PASSED', 'DOC-PASSED', '已通过')]),
  makeFile('DOC-UNLINKED', '2026-08-20 10:01:00'),
  makeFile('DOC-PROCESSING', '2026-08-20 10:00:00', [], {
    currentOcrStatus: '识别中',
    sliceStatus: '待切片',
    vectorStatus: '待向量化'
  })
]

const rectifications: RectificationItem[] = [
  {
    id: 'REC-OPEN',
    projectId: 'P-1',
    nodeId: 16,
    status: '待反馈',
    comment: '请补充质量证明文件。',
    createdAt: '2026-08-20 09:00:00',
    bindingIds: ['B-CORRECTION']
  },
  {
    id: 'REC-CLOSED',
    projectId: 'P-1',
    nodeId: 24,
    status: '已关闭',
    comment: '已完成补正。',
    createdAt: '2026-08-19 09:00:00'
  }
]

const model = buildContractorWorkbenchModel({ projectFiles: files, rectifications })

assert.deepEqual(
  contractorStatusFilterOptions,
  ['全部', '待提交', '审核中', '需补正', '已通过', '已作废'],
  '上传资料列表不能展示“未关联”分类及其数量'
)

assert.deepEqual(
  model.summaryCards.map(({ key, count }) => ({ key, count })),
  [
    { key: 'feedback', count: 1 },
    { key: 'pending', count: 1 },
    { key: 'reviewing', count: 1 }
  ],
  '状态卡必须只统计当前需要办理或跟踪的真实业务状态'
)

assert.deepEqual(
  Object.fromEntries(model.primaryTabs.map(({ key, count }) => [key, count])),
  {
    全部: 6,
    待提交: 1,
    审核中: 1,
    需补正: 1,
    已通过: 1
  },
  '资料列表一级状态数量必须与每份文件的挂载状态一致'
)

assert.deepEqual(
  model.recentUpload,
  {
    total: 6,
    successful: 5,
    processing: 1,
    failed: 0
  },
  '最近上传摘要必须把处理中资料与上传成功资料分开'
)

assert.equal(model.files[0]?.documentId, 'DOC-PENDING', '资料列表必须按更新时间从新到旧排列')

assert.deepEqual(resolveContractorSummaryTarget('feedback'), {
  anchor: '#contractor-feedback-list',
  tab: null
})
assert.deepEqual(resolveContractorSummaryTarget('pending'), {
  anchor: '#contractor-file-list',
  tab: '待提交'
})
assert.deepEqual(resolveContractorSummaryTarget('reviewing'), {
  anchor: '#contractor-file-list',
  tab: '审核中'
})

assert.deepEqual(
  sortContractorFeedback([
    { id: 'REC-CLOSED', status: '已关闭', createdAt: '2026-08-20 09:00:00' },
    { id: 'REC-RESUBMITTED', status: '已重新提交', createdAt: '2026-08-20 11:00:00' },
    { id: 'REC-PENDING-OLD', status: '待反馈', createdAt: '2026-08-20 08:00:00' },
    { id: 'REC-PENDING-NEW', status: '待反馈', createdAt: '2026-08-20 12:00:00' }
  ]).map((item) => item.id),
  ['REC-PENDING-NEW', 'REC-PENDING-OLD', 'REC-RESUBMITTED', 'REC-CLOSED'],
  '待反馈意见必须优先展示，同状态按创建时间从新到旧'
)

console.log('Contractor workbench view model contract passed')
