import assert from 'node:assert/strict'

import type { AutoReviewPolicy, AutoReviewStatus } from '@/api/aicheck'
import { autoReviewModeLabel, autoReviewStatusSummary } from './autoReviewPresentation'

const policy = (values: Partial<AutoReviewPolicy>): AutoReviewPolicy => ({
  id: 'ARP-1',
  projectId: 'P-1',
  tenantId: 'T-1',
  enabled: false,
  triggerModes: ['ocr_mounted', 'daily_schedule'],
  dailyTime: '02:00',
  timezone: 'Asia/Shanghai',
  reviewMode: 'gap_precheck',
  debounceSeconds: 300,
  revision: 1,
  etag: 'etag',
  ...values
})

assert.equal(autoReviewModeLabel(policy({ enabled: false })), '自动审查：已关闭')
assert.equal(
  autoReviewModeLabel(policy({ enabled: true, triggerModes: ['ocr_mounted'] })),
  '自动审查：实时'
)
assert.equal(
  autoReviewModeLabel(policy({ enabled: true, triggerModes: ['daily_schedule'] })),
  '自动审查：每天 02:00'
)
assert.equal(
  autoReviewModeLabel(
    policy({ enabled: true, triggerModes: ['ocr_mounted', 'daily_schedule'] })
  ),
  '自动审查：实时 + 每天 02:00'
)

const status = {
  policy: policy({ enabled: true }),
  pendingNodeCount: 3,
  runningProjectRunCount: 2,
  failedProjectRunCount: 1
} as AutoReviewStatus
assert.equal(autoReviewStatusSummary(status), '待审节点 3 · 执行中 2 · 失败 1')
assert.equal(autoReviewStatusSummary(undefined), '状态加载中')
