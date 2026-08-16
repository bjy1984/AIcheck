/**
 * 模型输出的 findings JSON 要变成人能读的结论。
 *
 * 线上实测（2026-08-16，监检工作台节点 24）：「AI 建议（待人工确认）」下面
 * 直接打出原始 JSON——监检要在花括号和转义引号里找结论。
 * **这不是「不好看」，是让人读不到判定**；读不到判定的界面等于没给判定。
 *
 * 反过来也要守住：解析不出来就原样返回文本。模型偶尔回纯文字，
 * 那时候把原文给人看是对的，硬套结构只会把内容吃掉。
 */
import assert from 'node:assert/strict'
import { parseAiFindings } from './aiFindings'

// 线上实测的真实输出（截断）
const REAL = JSON.stringify({
  findings: [
    {
      findingType: 'insufficient_evidence',
      severity: 'medium',
      title: '焊工资格证及持证合格项目证据不足，需人工确认',
      description: 'OCR 证据不完整：缺少完整 OCR 文本和可定位的文档范围证据。',
      evidenceRefs: [{ evidenceLinkId: 'R24EV-65B8B5FF8238' }, { evidenceLinkId: 'R24EV-2' }],
      ruleRefs: ['TSG D7006']
    }
  ]
})

const real = parseAiFindings(REAL)
assert.equal(real.length, 1)
assert.equal(real[0].typeLabel, '证据不足', 'findingType 要翻成中文')
assert.equal(real[0].severityLabel, '中')
assert.equal(real[0].severity, 'medium')
assert.ok(real[0].title.startsWith('焊工资格证'))
assert.equal(real[0].evidenceCount, 2, '证据条数要数出来，让人知道有没有依据')
assert.equal(real[0].ruleCount, 1)

// ```json 围栏：模型常这么包一层
const fenced = parseAiFindings('```json\n' + REAL + '\n```')
assert.equal(fenced.length, 1, '围栏包裹的也要认')

// 顶层数组
assert.equal(parseAiFindings(JSON.stringify([{ title: '直接数组' }])).length, 1)

// 纯文字：必须返回空，让调用方原样显示——**吃掉内容比不排版更糟**
assert.deepEqual(parseAiFindings('你好，我是复核助手。'), [])
assert.deepEqual(parseAiFindings(''), [])
assert.deepEqual(parseAiFindings('{ 这不是合法 JSON'), [])

// 空壳条目不占位：没有标题也没有描述的，显示出来只是噪音
assert.deepEqual(parseAiFindings(JSON.stringify({ findings: [{ severity: 'low' }] })), [])

// 未知类型照原样显示，不编一个标签
const unknown = parseAiFindings(
  JSON.stringify({ findings: [{ findingType: 'weird_kind', title: 'x' }] })
)
assert.equal(unknown[0].typeLabel, 'weird_kind')

// 模型没给严重度时不能瞎补
const noSeverity = parseAiFindings(JSON.stringify({ findings: [{ title: 'x' }] }))
assert.equal(noSeverity[0].severityLabel, '')
assert.equal(noSeverity[0].severity, '')

console.log('aiFindings：全部断言通过')
