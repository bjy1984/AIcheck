import assert from 'node:assert/strict'

import { plainWording, usesPlainWording, wordingFor } from './reviewerWording'

// 施工方、无损检测、建设方换说法；监检、管理员、FDE 看原文
assert.equal(usesPlainWording('contractor'), true)
assert.equal(usesPlainWording('ndt'), true)
assert.equal(usesPlainWording('owner'), true)
assert.equal(usesPlainWording('inspection'), false)
assert.equal(usesPlainWording('admin'), false)
assert.equal(usesPlainWording('fde'), false)

const cases: Array<[string, string]> = [
  ['AI 预审中', '预审中'],
  ['AI预审中', '预审中'],
  ['待人工确认', '待审核员确认'],
  ['需人工复核', '需审核员复核'],
  ['AI 审查完成', '审查完成'],
  ['AI 已完成，等待人工确认', '审核已完成，等待审核员确认'],
  ['人工智能审查', '审查'],
  ['证据不足，需人工确认', '证据不足，需审核员确认'],
  // 不做通配：施工方自己挂的资料叫「人工挂载」，不是审核员挂的
  ['整份资料 · 人工挂载（张工）', '整份资料 · 人工挂载（张工）'],
  // 产品名里的 AI 不动
  ['AIcheck 平台', 'AIcheck 平台'],
  ['退回补正提醒', '退回补正提醒']
]
for (const [input, expected] of cases) assert.equal(plainWording(input), expected, input)
assert.equal(plainWording(undefined), '')

assert.equal(wordingFor('owner')('待人工确认'), '待审核员确认')
assert.equal(wordingFor('inspection')('待人工确认'), '待人工确认', '监检照原样看')
