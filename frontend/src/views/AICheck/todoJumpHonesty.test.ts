/**
 * 待办跳转：定位不成功就不许说「已定位」。
 *
 * 线上实测（2026-08-16，施工方）：
 *   点「去该节点处理」→ 弹出「已定位到待办对应的节点」→ 页面首屏一字未变。
 *
 * 原因是 handleOpenQuickTodo 只做了 loadNodePackage：节点数据取回来了，
 * 而施工方这个视图是文件库，压根不渲染节点包。
 *
 * **系统声称做了一件它没做的事，比什么都不做更糟**——用户会以为自己看漏了，
 * 于是反复点、反复找，最后得出「这个系统的按钮不能信」。
 *
 * 现在：静态视图把节点名填进筛选并滚过去；真滚过去了才说「已定位」，
 * 否则如实说「只切换了项目，请在列表中查找」。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const workbench = readFileSync(fileURLToPath(new URL('./Workbench.vue', import.meta.url)), 'utf8')
const sections = readFileSync(
  fileURLToPath(new URL('./components/WorkbenchRoleStaticSections.vue', import.meta.url)),
  'utf8'
)

const start = workbench.indexOf('const handleOpenQuickTodo')
assert.ok(start > 0, '找不到待办跳转处理函数')
const fn = workbench.slice(start, workbench.indexOf('const loadProjectBundle'))

// 「已定位」这句话必须带条件，不能无条件弹
assert.ok(/if \(targetNodeId > 0 && located\)/.test(fn), '「已定位」必须以真的定位成功为前提')
assert.ok(
  /已切换到待办所属项目；当前视图无法直接定位/.test(fn),
  '定位不了时要如实说明，不能沉默也不能谎称成功'
)

// 光取数据不算定位：必须调静态视图的定位方法
assert.ok(/focusContractorNode/.test(fn), '要调用视图的定位方法，而不是只 loadNodePackage')
const loadAt = fn.indexOf('await loadNodePackage')
const focusAt = fn.indexOf('focusContractorNode')
assert.ok(loadAt > 0 && focusAt > loadAt, '先取数据再定位')

// **定位要按节点筛选，不能往搜索框塞词。**
// 第一版把节点名填进搜索框，线上得到「0 / 10 个文件 · 暂无文件」——
// 搜索匹配的是文件名/资料类别，「节点 16」这四个字不在任何文件名里。
// 把「定位」做成「搜索」，看起来像在筛选，实际是把人筛没了；
// 而空列表比原来的错误提示更糟：用户会以为自己的资料丢了。
assert.ok(/contractorNodeFilter/.test(sections), '要有按节点的筛选状态')
assert.ok(/contractorKeyword\.value = ''/.test(sections), '定位时要清空关键词，不能靠关键词筛选')
assert.ok(
  /file\.relationNodeIds\.includes\(contractorNodeFilter\.value\)/.test(sections),
  '按节点 id 精确判定——用 relationNode 文本匹配，节点 1 会连 11、12 一起命中'
)
// 锁定后必须让用户看见并能退出，否则又是一次「列表莫名其妙变空」
assert.ok(/当前只显示「节点/.test(sections), '锁定节点要有明确提示')
assert.ok(/clearContractorNodeFilter/.test(sections), '要有一键查看全部资料')

// 静态视图这边：定位＝填筛选 + 滚动，并回报是否成功
assert.ok(/const focusContractorNode = async/.test(sections), '静态视图要暴露定位方法')
assert.ok(/scrollIntoView/.test(sections), '定位要把列表滚到可见处')
assert.ok(/defineExpose\(\{ focusContractorNode \}\)/.test(sections), '方法要暴露给父组件')
assert.ok(
  /#contractor-file-list/.test(sections) && /id="contractor-file-list"/.test(sections),
  '滚动锚点必须真实存在——选择器写了而元素没有，滚动会静默失败'
)
