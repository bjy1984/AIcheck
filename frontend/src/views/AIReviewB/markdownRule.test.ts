/**
 * 回答里单独一行的 --- 要渲染成分隔线，不是三个裸短横（2026-11-10 生产回答里就有）。
 * 模型常在「核查结论」表和「说明」之间写它。
 *
 * 用源码断言而不是挂载组件：这个 SFC 的解析在 computed 里，没有单独导出。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const source = readFileSync(
  fileURLToPath(new URL('./components/ReviewMarkdownText.vue', import.meta.url)),
  'utf8'
)

const match = /const isRuleLine = \(line: string\) => (\/.*\/)\.test\(line\)/.exec(source)
assert.ok(match, '没找到 isRuleLine')
const isRule = (line: string) => new RegExp(match[1].slice(1, -1)).test(line)

for (const line of ['---', '----', '***', '___', '  ---  ']) assert.equal(isRule(line), true, line)
for (const line of ['--', '- 一项', '| --- | --- |', '文字 ---', '-*-', '']) {
  assert.equal(isRule(line), false, JSON.stringify(line))
}

// 段落遇到分隔线要断开，否则它会被并进上一段文字
assert.ok(/isBlockStart[\s\S]{0,200}isRuleLine\(line\)/.test(source), '分隔线要算块起点')
assert.ok(source.includes('<hr v-else-if="block.type === \'rule\'"'), '要渲染成 hr')
assert.ok(/\.markdown-rule\s*\{[^}]*border-top/.test(source), '分隔线要有样式')

console.log('Markdown rule rendering contract passed')
