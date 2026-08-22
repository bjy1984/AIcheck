import assert from 'node:assert/strict'
const contracts = (await import('../../types/aicheck')) as Record<string, unknown>

/* 完成态能呈现实际结论；失败态只能呈现标准化失败原因，绝不能复用创建 run
   时写入的“已进入队列” opinionDraft。该 selector 被工作台可见输出和时间线共用。 */
assert.equal(typeof contracts.selectAiReviewDisplay, 'function', '缺少 AI 运行显示选择器')
const selectAiReviewDisplay = contracts.selectAiReviewDisplay as (run: unknown) => {
  conclusion: string
  outputText: string
  failed: boolean
}

const completed = selectAiReviewDisplay({
  status: '完成',
  suggestion: { result: '证据不足', opinionDraft: '证据不足，需要补充焊接工艺评定。' }
})
assert.deepEqual(completed, {
  conclusion: '证据不足',
  outputText: '证据不足，需要补充焊接工艺评定。',
  failed: false
})

const failed = selectAiReviewDisplay({
  status: '失败',
  failure: { reason: '模型服务超时，请稍后重试。' },
  suggestion: {
    result: '需人工确认',
    opinionDraft: 'AI 复核已进入队列，完成后将更新审查建议。'
  }
})
assert.deepEqual(failed, {
  conclusion: '模型服务超时，请稍后重试。',
  outputText: '模型服务超时，请稍后重试。',
  failed: true
})
assert.doesNotMatch(failed.outputText, /已进入队列/, '失败态不能显示排队占位建议')

console.log('AI timeline conclusion rendering contract passed')
