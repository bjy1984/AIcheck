import assert from 'node:assert/strict'

import { resolveInspectionWorkspaceView } from './inspectionWorkspaceView'

assert.equal(resolveInspectionWorkspaceView(undefined), 'list')
assert.equal(resolveInspectionWorkspaceView(''), 'list')
assert.equal(resolveInspectionWorkspaceView('ai'), 'ai')
assert.equal(resolveInspectionWorkspaceView('unknown'), 'list')
assert.equal(resolveInspectionWorkspaceView(['list']), 'list')
assert.equal(resolveInspectionWorkspaceView('list'), 'list')
