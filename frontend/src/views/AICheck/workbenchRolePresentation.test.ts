import assert from 'node:assert/strict'

import { workbenchRolePresentation } from './workbenchRolePresentation'

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
