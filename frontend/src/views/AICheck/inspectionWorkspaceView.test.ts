import assert from 'node:assert/strict'

import { opensAiAssistant, resolveInspectionWorkspaceView } from './inspectionWorkspaceView'

assert.equal(resolveInspectionWorkspaceView(undefined), 'list')
assert.equal(resolveInspectionWorkspaceView(''), 'list')
// view=ai 是旧链接：页面落在完整工作台，AI 助手另外弹出
assert.equal(resolveInspectionWorkspaceView('ai'), 'list')
assert.equal(resolveInspectionWorkspaceView('unknown'), 'list')
assert.equal(resolveInspectionWorkspaceView(['list']), 'list')
assert.equal(resolveInspectionWorkspaceView('list'), 'list')
assert.equal(resolveInspectionWorkspaceView('important'), 'important')

assert.equal(opensAiAssistant('ai'), true)
assert.equal(opensAiAssistant('list'), false)
assert.equal(opensAiAssistant('important'), false)
assert.equal(opensAiAssistant(undefined), false)
assert.equal(opensAiAssistant(['ai']), false)
