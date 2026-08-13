import assert from 'node:assert/strict'

import { resolveInspectionWorkspaceView } from './inspectionWorkspaceView'

assert.equal(resolveInspectionWorkspaceView(undefined), 'ai')
assert.equal(resolveInspectionWorkspaceView(''), 'ai')
assert.equal(resolveInspectionWorkspaceView('ai'), 'ai')
assert.equal(resolveInspectionWorkspaceView('unknown'), 'ai')
assert.equal(resolveInspectionWorkspaceView(['list']), 'ai')
assert.equal(resolveInspectionWorkspaceView('list'), 'list')
