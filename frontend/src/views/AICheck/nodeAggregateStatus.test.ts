import assert from 'node:assert/strict'

import { aggregateNodeStatus, nodeNeedsAttention } from './nodeAggregateStatus'

const item = (key: string, status: string, label = key) => ({ key, label, status })

// —— 优先级：需关注 > 进行中 > 未开始 > 已完成 ——
// 一个节点只要还有一项要人管，它就是要人管的，哪怕另外六项都完成了。
// 按「完成得最多」排会把真正卡住的节点藏起来。
;(() => {
  const seven = [
    item('submission', '已完成', '资料提交'),
    item('ocr', '已完成', 'OCR 抽取'),
    item('evidence', '已完成', '证据确认'),
    item('ai', '已完成', 'AI 复核'),
    item('manual', '需关注', '人工结论'),
    item('report', '已完成', '报告复核'),
    item('archive', '已完成', '签发归档')
  ]
  const result = aggregateNodeStatus(seven)
  assert.equal(result.tone, 'attention')
  assert.equal(result.label, '需要处理')
  // 必须指名道姓说是哪一步——只说「需关注」等于让人自己再翻一遍七项
  assert.equal(result.blockedAt, '人工结论')
  assert.equal(result.progress, '6/7')
})()

// 执行失败也算要人管
assert.equal(aggregateNodeStatus([item('ai', '执行失败', 'AI 复核')]).tone, 'attention')

// 进行中：告诉人系统在跑哪一步，他不必动
;(() => {
  const r = aggregateNodeStatus([
    item('ocr', '处理中', 'OCR 抽取'),
    item('ai', '未开始', 'AI 复核')
  ])
  assert.equal(r.tone, 'running')
  assert.equal(r.label, '系统处理中')
  assert.equal(r.blockedAt, 'OCR 抽取')
})()

// 需关注压过进行中：有东西卡住时，「还有别的在跑」不是重点
;(() => {
  const r = aggregateNodeStatus([
    item('ocr', '处理中', 'OCR 抽取'),
    item('manual', '需关注', '人工结论')
  ])
  assert.equal(r.tone, 'attention')
  assert.equal(r.blockedAt, '人工结论')
})()

// 全部完成
;(() => {
  const r = aggregateNodeStatus([item('a', '已完成'), item('b', '已完成')])
  assert.equal(r.tone, 'done')
  assert.equal(r.blockedAt, '')
})()

// 有进展但没人在跑、也没卡住 —— 通常是等上游资料，不该显示成「未开始」
;(() => {
  const r = aggregateNodeStatus([item('a', '已完成'), item('b', '未开始')])
  assert.equal(r.tone, 'idle')
  assert.equal(r.label, '等待资料')
  assert.equal(r.progress, '1/2')
})()

// 全未开始
assert.equal(aggregateNodeStatus([item('a', '未开始')]).label, '未开始')

// 英文状态也要认：ai_runs 写中文、review_runs 写英文，是历史遗留
assert.equal(aggregateNodeStatus([item('a', 'failed')]).tone, 'attention')
assert.equal(aggregateNodeStatus([item('a', 'running')]).tone, 'running')
assert.equal(aggregateNodeStatus([item('a', 'completed')]).tone, 'done')

// 数据没到时不能显示成「已完成」——那会让人以为审完了
;(() => {
  const r = aggregateNodeStatus(undefined)
  assert.equal(r.tone, 'idle')
  assert.equal(r.label, '未开始')
})()
assert.equal(aggregateNodeStatus([]).label, '未开始')

// 脏数据不能把整张表带崩
assert.equal(aggregateNodeStatus([null as never, undefined as never]).label, '未开始')

// —— 筛选 ——
assert.equal(nodeNeedsAttention([item('a', '需关注')]), true)
assert.equal(nodeNeedsAttention([item('a', '已完成')]), false)
assert.equal(nodeNeedsAttention(undefined), false)
