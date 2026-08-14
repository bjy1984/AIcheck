import assert from 'node:assert/strict'

import {
  resolveReviewSidebarLayout,
  resolveReviewWorkbenchContext
} from './embeddedReviewWorkbench'

assert.deepEqual(resolveReviewWorkbenchContext({ embedded: false, projectId: '', nodeId: 0 }), {
  source: 'standalone'
})
assert.deepEqual(resolveReviewWorkbenchContext({ embedded: true, projectId: '', nodeId: 0 }), {
  source: 'waiting'
})
assert.deepEqual(resolveReviewWorkbenchContext({ embedded: true, projectId: 'P-001', nodeId: 0 }), {
  source: 'waiting'
})
assert.deepEqual(resolveReviewWorkbenchContext({ embedded: true, projectId: 'P-001', nodeId: 2 }), {
  source: 'embedded',
  projectId: 'P-001',
  nodeId: 2
})

const sidebarCases = [
  {
    input: { embedded: false, leftCollapsed: false, rightCollapsed: false },
    expected: {
      layoutClasses: [],
      leftLabel: '收起节点导航',
      rightLabel: '收起上下文',
      leftExpanded: true,
      rightExpanded: true
    }
  },
  {
    input: { embedded: false, leftCollapsed: true, rightCollapsed: false },
    expected: {
      layoutClasses: ['is-left-collapsed'],
      leftLabel: '展开节点导航',
      rightLabel: '收起上下文',
      leftExpanded: false,
      rightExpanded: true
    }
  },
  {
    input: { embedded: false, leftCollapsed: false, rightCollapsed: true },
    expected: {
      layoutClasses: ['is-right-collapsed'],
      leftLabel: '收起节点导航',
      rightLabel: '展开上下文',
      leftExpanded: true,
      rightExpanded: false
    }
  },
  {
    input: { embedded: false, leftCollapsed: true, rightCollapsed: true },
    expected: {
      layoutClasses: ['is-left-collapsed', 'is-right-collapsed'],
      leftLabel: '展开节点导航',
      rightLabel: '展开上下文',
      leftExpanded: false,
      rightExpanded: false
    }
  },
  {
    input: { embedded: true, leftCollapsed: true, rightCollapsed: true },
    expected: {
      layoutClasses: [],
      leftLabel: '收起节点导航',
      rightLabel: '收起上下文',
      leftExpanded: true,
      rightExpanded: true
    }
  }
] as const

for (const sidebarCase of sidebarCases) {
  assert.deepEqual(resolveReviewSidebarLayout(sidebarCase.input), sidebarCase.expected)
}
