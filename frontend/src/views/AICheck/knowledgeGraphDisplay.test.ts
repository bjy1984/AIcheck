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

/* 名字一个字都不省略，长了折行。
 *
 * 上一版截到 8/12 字加省略号，图上一排「压力管道安…」「监检业务判…」——
 * 看得见有东西，仍然不知道是哪一条，和纯色块只差半步。 */
assert.ok(!/clipLabel/.test(sfc), '不许再截断标签，长了要折行')
// 只看图表配置那段：页面别处的 text-overflow: ellipsis 是列表用的，不相干
const optionPart = sfc.slice(sfc.indexOf('function buildChartOption'), sfc.indexOf('</script>'))
assert.ok(!/ellipsis/.test(optionPart), '图表标签不该还留着省略号配置')
assert.ok(/function wrapLabel/.test(sfc), '要有折行函数')
assert.ok(
  /name: wrapLabel\(node\.label, node\.type\)\.join\('\\n'\)/.test(sfc),
  '节点名字要用折行后的多行文本'
)

/* 折行后**高度必须跟着行数涨**，否则第二行直接画到框外面——
   那只是把「横着溢出」换成了「竖着溢出」。 */
const rectBody = sfc.slice(
  sfc.indexOf('function nodeRectSize'),
  sfc.indexOf('function buildChartOption')
)
assert.ok(/lines\.length \* lineHeightOf\(type\)/.test(rectBody), '框高要按行数算')
assert.ok(
  /lines\.map\(\(line\) => estimateTextWidth\(line, fontSize\)\)/.test(rectBody),
  '框宽要按最长那行算'
)
// 行高要同时给 label，否则 ECharts 按默认行距排，和框高对不上
assert.ok(
  /lineHeight: lineHeightOf\(node\.type\)/.test(sfc),
  'label 要用同一个行高，否则文字和框高对不上'
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

/* ---- 平移不能被重画清掉 ----
 *
 * 「滑动有时失灵」的真身：每次 setOption 都传 notMerge=true，
 * 等于每次重画都把画布的平移缩放清零。而重画的触发点很多——
 * 筛选类型、搜索、切主题、选中节点——用户拖到一半碰上一次，图就弹回原位。
 *
 * 三条一起才算修好，少一条都会复发。 */

// 1. notMerge 只在明确要重置视图时用
assert.ok(
  /setOption\(buildChartOption\(\), \{ notMerge: reset, lazyUpdate: true \}\)/.test(sfc),
  'setOption 又写死了 notMerge——平移会被每次重画清掉'
)

// 2. 选中不走重建：它只是换个描边，不该连带清空视图
assert.ok(
  /watch\(selectedNodeId, \(\) => syncSelectionToChart\(\)\)/.test(sfc),
  '选中要用 dispatchAction 同步，不能触发重画'
)
const renderWatch = sfc.slice(sfc.indexOf('watch(\n  () => [visibleNodes'))
assert.ok(
  !/\[visibleNodes\.value, visibleEdges\.value, selectedNodeId\.value/.test(renderWatch),
  'selectedNodeId 又被塞回重画监听了——点一下节点视图就弹回原位'
)
// itemStyle 也不能读 selectedNodeId，否则 option 仍然随选中而变
const itemStylePart = sfc.slice(sfc.indexOf('itemStyle: {'), sfc.indexOf('fullName: node.label'))
assert.ok(
  !/selectedNodeId/.test(itemStylePart),
  'itemStyle 还在读 selectedNodeId——option 会随选中重建'
)

/* 3. 节点不可拖。矩形比圆占的面积大好几倍，随手一拖经常拖的是某个节点，
      在用户看来就是「滑动失灵」。平移是主要操作，挪单个节点不是。 */
assert.ok(/draggable: false/.test(sfc), '节点可拖会把平移吃掉——矩形面积大，命中概率很高')
assert.ok(/roam: true/.test(sfc), '要能平移缩放')

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
