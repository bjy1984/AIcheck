import assert from 'node:assert/strict'

import { formatReviewTokenUsage } from './tokenUsage'

assert.equal(
  formatReviewTokenUsage({
    inputTokens: 3200,
    outputTokens: 480,
    totalTokens: 3680
  }),
  '输入 3,200 · 输出 480 · 总计 3,680 Token'
)

assert.equal(
  formatReviewTokenUsage({
    prompt_tokens: 1200,
    completion_tokens: 86
  }),
  '输入 1,200 · 输出 86 · 总计 1,286 Token'
)

assert.equal(formatReviewTokenUsage(undefined), '')
assert.equal(formatReviewTokenUsage({ inputTokens: -1, outputTokens: Number.NaN }), '')
