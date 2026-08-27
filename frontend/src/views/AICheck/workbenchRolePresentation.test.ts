import assert from 'node:assert/strict'

import * as presentation from './workbenchRolePresentation'

const {
  projectSubmissionMeta,
  submittedFileCountLabel,
  submittedNodeMeta,
  workbenchRolePresentation
} = presentation as typeof presentation & {
  projectSubmissionMeta?: (nodeCount: number, submittedFileCount: number) => string
  submittedFileCountLabel?: (submittedFileCount: number) => string
  submittedNodeMeta?: (inspectionType: string, submittedFileCount: number) => string
}

assert.equal(typeof submittedNodeMeta, 'function', '节点摘要必须提供只按已提交文件数展示的口径')
assert.equal(submittedNodeMeta?.('C', 3), 'C 类 · 已提交 3 个文件')
assert.equal(submittedFileCountLabel?.(3), '3 个文件')
assert.equal(projectSubmissionMeta?.(69, 76), '节点 69 · 提交 76')

assert.deepEqual(workbenchRolePresentation('contractor'), {
  showBreadcrumb: false,
  intro: '统一上传项目资料并提交，根据监检意见补充完善相关资料。'
})

assert.equal(
  workbenchRolePresentation('inspection').showBreadcrumb,
  true,
  '隐藏施工方面包屑不能影响其他角色'
)

console.log('Workbench role presentation contract passed')
