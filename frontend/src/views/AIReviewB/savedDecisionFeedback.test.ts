/**
 * 保存成功之后，页面上必须留下痕迹。
 *
 * 实操验证（2026-08-15）：人工复核结论确实写进了库（OPN-6758E422，
 * 内容与填写一致、结果「证据不足」），而界面上——
 *
 *   - 输入框里 51 个字原封不动；
 *   - 页面任何地方都看不到刚保存的那条。
 *
 * 从监检的角度，这和「没保存成功」长得一模一样，于是再点一次。
 * 同一节点因此攒下 3 条重复的「证据不足」。对监督检验系统来说，
 * 一个节点上出现多条互相独立的人工结论，是数据完整性问题。
 *
 * 数据本来就在：接口一直在 latestHumanDecision 里返回它，前端从来没渲染。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const sfc = readFileSync(
  fileURLToPath(new URL('./ConversationalReviewWorkbenchB.vue', import.meta.url)),
  'utf8'
)

// 已保存的结论要有数据源，并且渲染出来
assert.ok(sfc.includes('const savedHumanDecision'), '没有把已保存结论取出来')
assert.ok(sfc.includes('latestHumanDecision'), '没有用接口已经返回的字段')
assert.ok(sfc.includes('class="saved-decision"'), '已保存的结论没有渲染到页面上')

// 结论和意见正文都要显示——只显示「已保存」而不显示存了什么，
// 用户仍然无法判断存下来的是不是自己刚写的那条
const block = sfc.slice(
  sfc.indexOf('class="saved-decision"'),
  sfc.indexOf('<label>审查结论</label>')
)
assert.ok(block.includes('savedHumanDecision.result'), '要显示存下来的结论')
assert.ok(block.includes('savedHumanDecision.opinion'), '要显示存下来的意见正文')

// 保存成功后清空输入框
const handler = sfc.slice(sfc.indexOf('const handleSaveReviewOpinion'))
const body = handler.slice(0, handler.indexOf('\nconst ', 1))
const successAt = body.indexOf("ElMessage.success('人工复核结论已保存')")
const clearAt = body.indexOf("reviewOpinion.value = ''")
assert.ok(successAt >= 0 && clearAt > successAt, '保存成功后没有清空输入框')

console.log('Saved human decision feedback contract passed')
