import assert from 'node:assert/strict'

import { getRoleDefaultPath, resolveRoleEntryPath } from './roleAccess'

assert.equal(getRoleDefaultPath('inspection'), '/ai-review-b')
assert.equal(resolveRoleEntryPath('inspection'), '/ai-review-b')
assert.equal(resolveRoleEntryPath('inspection', '/'), '/ai-review-b')
assert.equal(
  resolveRoleEntryPath('inspection', '/ai-review-b?projectId=P-1&nodeId=2'),
  '/ai-review-b?projectId=P-1&nodeId=2'
)
assert.equal(
  resolveRoleEntryPath('inspection', '/workbench/inspection?projectId=P-1&nodeId=2'),
  '/workbench/inspection?projectId=P-1&nodeId=2'
)
assert.equal(resolveRoleEntryPath('inspection', '/workbench/contractor'), '/ai-review-b')

assert.equal(getRoleDefaultPath('contractor'), '/workbench/contractor')
assert.equal(getRoleDefaultPath('ndt'), '/workbench/ndt')
assert.equal(getRoleDefaultPath('owner'), '/workbench/owner')
assert.equal(getRoleDefaultPath('admin'), '/admin/overview')
assert.equal(getRoleDefaultPath('fde'), '/fde/dashboard')
