/**
 * 核查结论表的「结论」列：认出结论词画成彩色胶囊（见 markdownVerdict.ts）。
 * 重点是不误伤：以结论词为前缀的普通词、别的列里的「符合」都不能被画成胶囊。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { isVerdictColumn, verdictOf } from './markdownVerdict'

assert.deepEqual(verdictOf('符合'), { verdict: '符合', tone: 'success', rest: '' })
assert.deepEqual(verdictOf('  不符合 '), { verdict: '不符合', tone: 'danger', rest: '' })
assert.equal(verdictOf('不符合')?.verdict, '不符合', '「不符合」不能被前缀「符合」抢先匹配')
assert.equal(verdictOf('未通过')?.tone, 'danger', '「未通过」不能被「通过」抢先')
assert.equal(verdictOf('通过')?.tone, 'success')
assert.equal(verdictOf('不适用')?.tone, 'info')
assert.equal(verdictOf('需人工确认')?.tone, 'warning')

// 结论词后面带说明：胶囊加一行灰字
assert.deepEqual(verdictOf('证据不足（施工期只录在项目信息里、本节点资料里没有出处）'), {
  verdict: '证据不足',
  tone: 'warning',
  rest: '（施工期只录在项目信息里、本节点资料里没有出处）'
})
assert.deepEqual(verdictOf('符合：许可范围含 GC1'), {
  verdict: '符合',
  tone: 'success',
  rest: '许可范围含 GC1'
})

// 不误伤
for (const text of [
  '符合要求',
  '符合性检查',
  '通过率 80%',
  '不符合项清单',
  '许可范围符合',
  '',
  '—'
]) {
  assert.equal(verdictOf(text), null, JSON.stringify(text))
}

// 只有表头写着「结论」「判定」的列才按结论列处理
assert.equal(isVerdictColumn('结论'), true)
assert.equal(isVerdictColumn('判定结果'), true)
assert.equal(isVerdictColumn('关键证据'), false)
assert.equal(isVerdictColumn('核查项'), false)

// 组件确实用了它：带引用的单元格（点开看原文）不画胶囊
const source = readFileSync(
  fileURLToPath(new URL('./components/ReviewMarkdownText.vue', import.meta.url)),
  'utf8'
)
assert.ok(source.includes("from '../markdownVerdict'"), '组件要用 markdownVerdict')
assert.ok(/!cell\.some\(\(part\) => part\.reference\)/.test(source), '带引用的单元格不动')
assert.ok(/\.verdict-pill\.is-warning/.test(source), '要有胶囊样式')

console.log('Markdown verdict pills contract passed')
