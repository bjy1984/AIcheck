import assert from 'node:assert/strict'

import { getRoleDefaultPath, resolveRoleEntryPath } from './roleAccess'

// 两套监检界面合并为一套（2026-08-16）：/ai-review-b 下线，
// 对话式复核以 embedded 方式留在 /workbench/inspection 里。
assert.equal(getRoleDefaultPath('inspection'), '/workbench/inspection')
assert.equal(resolveRoleEntryPath('inspection'), '/workbench/inspection')
assert.equal(resolveRoleEntryPath('inspection', '/'), '/workbench/inspection')
// 老链接要**带着查询串**翻译过去：收藏夹里那条 /ai-review-b?projectId=…&nodeId=…
// 应当落在工作台的同一个节点上，而不是被打回默认页让人重新找一遍。
assert.equal(
  resolveRoleEntryPath('inspection', '/ai-review-b?projectId=P-1&nodeId=2'),
  '/workbench/inspection?projectId=P-1&nodeId=2&view=ai'
)
// 本来就是工作台地址的，原样保留——用户没从对话页来，不该替他切视图。
assert.equal(
  resolveRoleEntryPath('inspection', '/workbench/inspection?projectId=P-1&nodeId=2'),
  '/workbench/inspection?projectId=P-1&nodeId=2'
)
assert.equal(resolveRoleEntryPath('inspection', '/workbench/contractor'), '/workbench/inspection')

assert.equal(getRoleDefaultPath('contractor'), '/workbench/contractor')
assert.equal(getRoleDefaultPath('ndt'), '/workbench/ndt')
assert.equal(getRoleDefaultPath('owner'), '/workbench/owner')
assert.equal(getRoleDefaultPath('admin'), '/admin/overview')
assert.equal(getRoleDefaultPath('fde'), '/fde/dashboard')
