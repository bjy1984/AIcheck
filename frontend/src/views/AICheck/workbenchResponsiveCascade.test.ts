import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const workbenchSource = readFileSync(new URL('./Workbench.vue', import.meta.url), 'utf8')
const responsiveSource = readFileSync(new URL('./workbenchResponsive.css', import.meta.url), 'utf8')

const inlineStyleStart = workbenchSource.indexOf('<style scoped>')
const inlineStyleEnd = workbenchSource.indexOf('</style>', inlineStyleStart)
const responsiveStyleStart = workbenchSource.indexOf(
  '<style scoped src="./workbenchResponsive.css"></style>'
)

assert.ok(inlineStyleStart >= 0 && inlineStyleEnd > inlineStyleStart, '找不到工作台基础样式块')
assert.ok(responsiveStyleStart >= 0, '工作台没有加载响应式 scoped 样式')
assert.ok(
  responsiveStyleStart > inlineStyleEnd,
  '响应式样式必须在桌面基础样式之后，才能以相同选择器优先级覆盖桌面规则'
)
assert.equal(
  workbenchSource.match(/workbenchResponsive\.css/g)?.length,
  1,
  '响应式样式只能加载一次'
)

for (const requiredRule of [
  '@media (width <= 1360px)',
  '@media (width <= 900px)',
  '@media (width <= 560px)',
  '@media (prefers-reduced-motion: reduce)'
]) {
  assert.ok(responsiveSource.includes(requiredRule), `响应式样式缺少 ${requiredRule}`)
}

console.log('Workbench responsive cascade contract passed')
