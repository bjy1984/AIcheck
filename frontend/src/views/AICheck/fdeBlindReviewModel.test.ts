import assert from 'node:assert/strict'

import { ALERT_THRESHOLD, formatPct, indexAlert, indexLabel } from './fdeBlindReviewModel'

// P12 F4：橡皮图章指数显示带符号；无样本显示待盲审
assert.equal(indexLabel(null), '待盲审')
assert.equal(
  indexLabel({ value: 0.1234, blindDivergence: 0.3, regularDivergence: 0.18, sampleSize: 10 }),
  '+0.123'
)
assert.equal(
  indexLabel({ value: -0.05, blindDivergence: 0.1, regularDivergence: 0.15, sampleSize: 10 }),
  '-0.050'
)
assert.equal(formatPct(0.2), '20.0%')
assert.equal(formatPct(null), '—')

// 样本不足 5 不报警；≥5 且低于阈值才报警（与后端 AICHECK_RUBBER_STAMP_ALERT_THRESHOLD 同口径）
assert.equal(
  indexAlert({ value: 0, blindDivergence: 0.2, regularDivergence: 0.2, sampleSize: 4 }),
  false
)
assert.equal(
  indexAlert({ value: 0, blindDivergence: 0.2, regularDivergence: 0.2, sampleSize: 5 }),
  true
)
assert.equal(
  indexAlert({
    value: ALERT_THRESHOLD,
    blindDivergence: 0.25,
    regularDivergence: 0.2,
    sampleSize: 9
  }),
  false
)
assert.equal(indexAlert(null), false)
