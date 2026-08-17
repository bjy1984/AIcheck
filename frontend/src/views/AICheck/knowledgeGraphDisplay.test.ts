/**
 * 关系网络：能全屏看，节点文字白色且不溢出球。
 *
 * 三条都是用户实际提出的：
 *
 * 1. **全屏**——关系图挤在半个屏幕里，节点一多就看不清谁连谁。
 * 2. **文字不要溢出球**——标签原先用默认位置（球右侧），长名字直接拖在球外，
 *    和连线、别的球叠在一起。
 * 3. **文字白色**——原先用主题文字色，深色球上是深色字。
 *
 * ## 几个容易漏的地方
 *
 * - 悬停态和选中态各有一份 label 配置。**只改静态那份，鼠标一移上去
 *   标签又跳回球外、变回黑字**——同一条规则写在三处，这轮已栽过五次。
 * - 退出全屏不一定经过按钮（Esc / F11 / 浏览器手势），状态要跟
 *   fullscreenchange 走；只在点击时取反，退出后按钮会一直写着「退出全屏」。
 * - 容器尺寸变了必须 resize 图表，否则全屏后画布还是原尺寸，
 *   看起来像「点了没反应」。
 * - `:fullscreen` 下容器脱离原布局，不显式给高度画布会塌成 0 高。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const sfc = readFileSync(fileURLToPath(new URL('./KnowledgeNetwork.vue', import.meta.url)), 'utf8')

// ---- 文字：白色、球内、截断 ----
const labelBlocks = sfc.match(/position: 'inside'/g) || []
assert.ok(labelBlocks.length >= 3, '静态、悬停、选中三处标签都要画在球内')

const whiteLabels = sfc.match(/color: '#ffffff'/g) || []
assert.ok(whiteLabels.length >= 3, '三处标签都要是白字')

// 截断宽度按球径算——写死字数的话，大球留白、小球照样溢出
assert.ok(
  /width: Math\.max\(0, \(SYMBOL_SIZE_BY_TYPE\[node\.type\] \|\| 18\) \* 2 - 8\)/.test(sfc),
  '截断宽度要按 symbolSize 算，不能写死字数'
)
assert.ok(/overflow: 'truncate'/.test(sfc), '超出球径要截断')
assert.ok(/ellipsis: '…'/.test(sfc), '截断要有省略号，否则看不出还有内容')

// 不该再用会随主题变深的文字色
const seriesPart = sfc.slice(sfc.indexOf('series: ['))
assert.ok(
  !/label: \{ show: true, color: colors\.text/.test(seriesPart),
  '还留着主题文字色的标签——深色球上会是深色字'
)

// ---- 全屏 ----
assert.ok(/const isFullscreen = ref\(false\)/.test(sfc), '要有全屏状态')
assert.ok(/requestFullscreen\(\)/.test(sfc), '要真的进全屏，不是放大 div')
assert.ok(/exitFullscreen\(\)/.test(sfc), '要能退出')

// 状态跟事件走，不是点击时取反
assert.ok(
  /addEventListener\('fullscreenchange', syncFullscreenState\)/.test(sfc),
  '要监听 fullscreenchange——Esc 退出时按钮文案得跟着变'
)
assert.ok(
  /removeEventListener\('fullscreenchange', syncFullscreenState\)/.test(sfc),
  '卸载时要摘掉监听'
)

// 尺寸变化后要 resize
const syncFn = sfc.slice(
  sfc.indexOf('const syncFullscreenState'),
  sfc.indexOf('const toggleGraphFullscreen')
)
assert.ok(/chart\?\.resize\(\)/.test(syncFn), '全屏切换后要 resize，否则画布还是原尺寸')

// 全屏样式要给高度，否则画布塌成 0
assert.ok(/\.graph-pane:fullscreen \{/.test(sfc), '要有全屏样式')
assert.ok(/height: 100vh/.test(sfc), '全屏容器要铺满高度')
assert.ok(/height: calc\(100vh - 24px\)/.test(sfc), '全屏时画布也要跟着变高')

// 按钮定位需要定位上下文，否则会飘到别处
const paneStyle = sfc.slice(sfc.indexOf('.graph-pane {'))
assert.ok(/position: relative/.test(paneStyle.slice(0, 300)), 'graph-pane 要是定位上下文')

console.log('Knowledge graph display contract passed')
