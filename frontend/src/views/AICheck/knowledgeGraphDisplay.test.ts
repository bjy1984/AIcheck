/**
 * 关系网络：能全屏看，节点文字白色且不溢出球。
 *
 * 三条都是用户实际提出的：
 *
 * 1. **全屏**——关系图挤在半个屏幕里，节点一多就看不清谁连谁。
 * 2. **文字不要溢出**——标签原先用默认位置（节点右侧），长名字直接拖在外面，
 *    和连线、别的节点叠在一起。
 * 3. **文字白色**——原先用主题文字色，深色节点上是深色字。
 * 4. **换成矩形**——先按「画在球里 + 截断」改过一版，但圆的可用宽度只有直径，
 *    中文名字不是溢出就是截成「压力管道安…」；为了塞字放大球径，
 *    图上又全成了巨型圆饼。矩形按文字长度定宽，这个矛盾就不存在。
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

// ---- 形状：直角矩形，宽度跟着文字走 ----
assert.ok(/symbol: 'rect' as const/.test(sfc), '节点要画成矩形，不是圆')
assert.ok(!/roundRect/.test(sfc), '不要圆角')
assert.ok(
  /symbolSize: nodeRectSize\(node\.type, node\.label\)/.test(sfc),
  '尺寸要按类型和标签算出来，不能是一个标量球径'
)

/* 宽度必须真的依赖文本，否则「换成矩形」只是把圆压扁，
   长名字照样溢出——这是最容易糊弄过去的一步。 */
const rectFn = sfc.slice(
  sfc.indexOf('function nodeRectSize'),
  sfc.indexOf('function buildChartOption')
)
assert.ok(/estimateTextWidth\(/.test(rectFn), '矩形宽度没有参考文字宽度，等于把圆压扁了')
assert.ok(/LABEL_PADDING_X \* 2/.test(rectFn), '文字两侧要留内边距，否则字贴着边框')

// ---- 文字：白色、框内 ----
const labelBlocks = sfc.match(/position: 'inside'/g) || []
assert.ok(labelBlocks.length >= 3, '静态、悬停、选中三处标签都要画在框内')

const whiteLabels = sfc.match(/color: '#ffffff'/g) || []
assert.ok(whiteLabels.length >= 3, '三处标签都要是白字')

// 超长名字先截，再据此定框宽——两者用同一个函数，不然框宽和实际文字对不上
assert.ok(/ellipsis|…/.test(sfc), '截断要有省略号，否则看不出还有内容')
assert.ok(
  /const text = estimateTextWidth\(clipLabel\(label, type\)/.test(sfc),
  '定框宽要用截断后的文字，否则超长名字会撑出一个巨宽的框'
)

/* 每个节点都要有名字。
 *
 * 原先只有 business_pack / domain_module 显示标签，其余十几种类型在图上
 * 就是一个个纯色块——**看得见有东西，但不知道是什么**，只能逐个悬停去问。
 * 那是圆形时代的妥协（圆里塞不下字）；框宽跟着文字走之后没有理由保留。 */
assert.ok(
  /label: \{\s*show: true,\s*position: 'inside'/.test(sfc),
  '还在按类型决定显不显示标签——图上会剩下一片无名色块'
)
assert.ok(!/LABELLED_TYPES/.test(sfc), '标签白名单要去掉，不是改一下成员')

/* hideOverlap 必须关掉：标签在框里，一旦判为重叠就整个隐掉，
   图上又会出现「一个纯色块，不知道是什么」——正是这次要修的问题。 */
assert.ok(
  /labelLayout: \{ hideOverlap: false \}/.test(sfc),
  'hideOverlap 开着会把框里的字整个隐掉，节点重新变回无名色块'
)

/* 截断的是显示，不是信息：完整名字要留给 tooltip。
   否则「放不下」就变成了「看不到」。 */
assert.ok(/fullName: node\.label/.test(sfc), '完整名字要带在数据里')
assert.ok(/datum\.fullName \?\? datum\.name/.test(sfc), 'tooltip 要显示完整名字')

// 不该再用会随主题变深的文字色
const seriesPart = sfc.slice(sfc.indexOf('series: ['))
assert.ok(
  !/label: \{ show: true, color: colors\.text/.test(seriesPart),
  '还留着主题文字色的标签——深色节点上会是深色字'
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
