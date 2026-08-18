/**
 * 关系网络：能全屏看，节点文字白色且不溢出球。
 *
 * 三条都是用户实际提出的：
 *
 * 1. **全屏**——关系图挤在半个屏幕里，节点一多就看不清谁连谁。
 * 2. **文字不要溢出**——标签原先用默认位置（节点右侧），长名字直接拖在外面，
 *    和连线、别的节点叠在一起。
 * 3. **文字白色**——原先用主题文字色，深色节点上是深色字。
 * 4. **形状与标签位置翻过两次**——圆 + 圆外标签（长名字压住连线）
 *    → 矩形 + 框内白字（为了塞下中文）→ 现在回到圆 + 圆外浅灰字。
 *    最后这次能成立，靠的是中间补上的确定性径向布局和 hideOverlap：
 *    坐标不再漂、挤不下的标签会自动让位，当年逼着改矩形的前提没有了。
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

/* ---- 形状：圆，文字在圆外面，浅灰色 ----
 *
 * 这里走过一个来回，判据也跟着翻过一次，记下来免得下一个人再绕：
 *   圆 + 圆外默认标签 → 长名字压住连线和别的节点
 *   → 矩形 + 框内白字（矩形按文字定宽，字才塞得下）
 *   → 现在回到圆 + 圆外浅灰字。
 *
 * 能回来是因为中间补上了确定性径向布局（坐标不再漂）和 hideOverlap
 * （挤不下的标签自动让位）——当年逼着改矩形的两个前提都没有了。 */
assert.ok(/symbol: 'circle' as const/.test(sfc), '节点要画成圆')
assert.ok(/symbolSize: nodeCircleSize\(node\.type\)/.test(sfc), '圆的大小按类型给，不再由文字撑')

/* 间距仍要按「圆 + 标签」整体算。
   只按圆径排的话，1:1 时圆是不挤了，标签会压成一片——
   这是「文字移到外面」最容易漏掉的代价。 */
const layoutBoxFn = sfc.slice(
  sfc.indexOf('function nodeLayoutBox'),
  sfc.indexOf('const graph = ref')
)
assert.ok(/estimateTextWidth\(/.test(layoutBoxFn), '布局占位没有算标签宽度，标签会互相压')
assert.ok(/LABEL_DISTANCE/.test(layoutBoxFn), '占位要含标签与圆之间的距离')
assert.ok(
  /const \[width, height\] = nodeLayoutBox\(node\.type, node\.label\)/.test(sfc),
  '布局没有用含标签的占位盒'
)

// ---- 文字：圆外、浅灰 ----
const outsideLabels = sfc.match(/position: 'right'/g) || []
assert.ok(outsideLabels.length >= 3, '静态、悬停、选中三处标签都要放在圆外面')
assert.ok(/color: colors\.muted/.test(sfc), '静态标签要用次要文字色（浅灰）')
/* 颜色不能写死成浅灰：浅色主题下几乎看不见。用主题变量才两种主题都成立。 */
assert.ok(!/color: '#9[0-9a-f]{5}'/.test(sfc), '不要写死的浅灰，要跟主题走')

/* 标签**默认最多 10 个字符**，超出截断加省略号。
 *
 * 这里走过一个来回：先截断（8/12 字）→ 用户要求显示全名 → 改成折行显示全
 * → 259 个全名矩形把周长需求推到几万像素，整图 fit 之后缩没了，
 * 用户反馈「根本没法看」→ 定为 10 字符截断。
 * 图上的标签是**索引**不是文档；全名一直在 tooltip 和右侧详情里。 */
assert.match(sfc, /const MAX_LABEL_CHARS = 10/, '默认最多显示 10 个字符')
assert.ok(/function truncateLabel/.test(sfc), '要有截断函数')
assert.ok(/name: truncateLabel\(node\.label\)/.test(sfc), '节点名字要用截断后的文本')
assert.ok(/\}…`/.test(sfc), '截断要带省略号，否则看不出还有内容')
assert.ok(!/function wrapLabel/.test(sfc), '折行已撤——全名折行会把周长推到几万像素')

/* 占位宽必须用**截断后**的文字。用全名算的话，
   占位又被撑回长条，截断就白做了。 */
assert.ok(
  /estimateTextWidth\(truncateLabel\(label\)/.test(layoutBoxFn),
  '占位宽没有按截断后的文字算'
)

/* 每个节点都要有名字。
 *
 * 原先只有 business_pack / domain_module 显示标签，其余十几种类型在图上
 * 就是一个个纯色块——**看得见有东西，但不知道是什么**，只能逐个悬停去问。
 * 那是「圆里塞不下字」时代的妥协；文字挪到圆外面之后更没有理由保留。 */
assert.ok(
  /label: \{\s*show: true,\s*position: 'right'/.test(sfc),
  '还在按类型决定显不显示标签——图上会剩下一片无名色点'
)
assert.ok(!/LABELLED_TYPES/.test(sfc), '标签白名单要去掉，不是改一下成员')

/* 符号固定像素（nodeScaleRatio 0）。隔离页实测：1 会把全景的 13 倍
   堆叠比锁死在所有缩放级别（放大到头也散不开——0818 线上实拍）；
   0.6（默认）放大时符号仍在长，永远到不了干净的 1:1；
   0 才能「越放越开」，~13 倍时达到布局尺度的零重叠。 */
assert.ok(
  /nodeScaleRatio: 0[,\s]/.test(sfc),
  'nodeScaleRatio 必须是 0：放大时只让间距长，才能越放越干净'
)
assert.ok(/max: 20/.test(sfc), 'scaleLimit.max 要够得着 1:1（~13 倍），12 差一点')

/* hideOverlap 必须开：roam 缩放只缩放坐标和符号，标签字号是固定像素。
   布局尺度下零重叠的几何，在「适配全图」的默认视角（zoom≈0.15）仍是
   一墙文字压文字——线上 259 个节点的全景就是这么糊掉的（0818 实拍）。
   全景时标签自动隐藏、节点缩成彩色小块；放大到 1:1 附近几何保证生效，
   标签一个不隐。此前「关掉以免节点变无名色块」的判断只对 zoom=1 成立。 */
assert.ok(
  /labelLayout: \{ hideOverlap: true \}/.test(sfc),
  'hideOverlap 关着的话，全景视角是一墙文字压文字，图根本没法看'
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

/* 3. 节点不可拖。随手一拖经常拖的是某个节点而不是画布，在用户看来
      就是「滑动失灵」。平移是主要操作，挪单个节点不是——何况坐标由布局
      统一算，单独挪一个只会破坏环形结构。 */
assert.ok(/draggable: false/.test(sfc), '节点可拖会把平移吃掉')
assert.ok(/roam: true/.test(sfc), '要能平移缩放')

/* 页面上的「使用说明」必须跟着行为改。
   原先写「拖动节点调整位置」，节点改不可拖之后它就成了假说明——
   照着做没反应，用户只会以为页面坏了。 */
// 只看 note 那一行——注释里引用旧文案是正常的，不该被判成回归
const noteLine = sfc.split('\n').find((line) => line.trim().startsWith('note:')) || ''
assert.ok(noteLine, '找不到使用说明')
assert.ok(!/拖动节点调整位置/.test(noteLine), '使用说明还教用户拖节点，而节点已经不可拖了')
assert.ok(/拖动空白处平移画布/.test(noteLine), '使用说明要告诉用户怎么平移')

/* ---- 拖到一半的重绘要等，不能打断手势 ----
 *
 * 前面修的是「重绘把视图清零」；这里修的是「重绘把手势打断」：
 * setOption 会重建图元，正在被拖的那个一旦被换掉，手还按着图却不动了。
 * 时机决定了它必然偶发——只有重绘恰好落在拖动过程中才会发生。 */
assert.ok(/let interacting = false/.test(sfc), '要记录用户是否正在图上操作')
assert.ok(
  /if \(interacting && !reset\) \{\s*pendingRender = true\s*return\s*\}/.test(sfc),
  '拖动中的重绘要挂起，不能直接执行'
)
// 挂起的重绘必须补做，否则筛选/搜索的结果会静默丢失
assert.ok(/pendingRender = false\s*renderChart\(\)/.test(sfc), '挂起的重绘要在松手后补做')
/* globalout 必须收：鼠标拖出画布外松开时没有 mouseup，
   漏掉这一路 interacting 会永久卡在 true，图再也不刷新——
   比原问题更难查的静默故障。 */
assert.ok(/zr\.on\('globalout', endInteraction\)/.test(sfc), '拖出画布外松手也要结束交互态')
assert.ok(/zr\.on\('mouseup', endInteraction\)/.test(sfc), '松手要结束交互态')
// resize 也会打断手势
assert.ok(/if \(interacting\) return\s*chart\?\.resize\(\)/.test(sfc), '拖动中不许 resize')
assert.ok(/if \(reset\) chart\.resize\(\)/.test(sfc), '只在重置时 resize，不要每次重绘都排一次')

/* ---- 定位到节点：**尚未实现** ----
 *
 * 「点一跳关系把视图移过去」试过五种做法，线上都验证无效：
 *   1. setOption({series:[{center,zoom}]}) 合并式 —— 视图不动
 *   2. 等 finished 之后再下发一次 —— 仍不动
 *   3. dispatchAction graphRoam 算 dx/dy —— 动了，但位移对不上
 *   4. 和 layout:'none' 放同一次 setOption —— 不动
 *   5. notMerge 整份下发 —— 视图回到默认铺开，中心永远是 hub 节点
 *
 * 第 5 版上线过一阵，副作用是**点一跳关系会把视图重置**，比不做更糟，已撤掉。
 * 这里锁住「撤干净了」这个状态：留着半个不生效的实现，
 * 下一个人会以为功能存在，然后花同样的时间再验一遍。 */
assert.ok(!/function centerOnNode/.test(sfc), '未生效的定位实现要撤干净，不要留半个')
assert.ok(!/pendingFocusId/.test(sfc), '定位相关状态要一起撤掉')
assert.ok(!/dispatchAction\(\{[^}]*graphRoam/.test(sfc), 'graphRoam 那条路线上验过位移对不上')

/* ---- 布局：确定性径向分层，不再用力导向 ----
 *
 * 数据是层级（业务包→模块→节点→条款），力导向把层级揉成中心一坨
 * 互相压的矩形——用户的原话是「知识图谱根本没法看」。
 * 几何契约（零重叠、层级半径单调、确定性）在 knowledgeGraphLayout.test.ts
 * 里按真实规模验证；这里只钉住组件**确实在用**那个布局：
 * 模块写对了但组件没接上，图照样没法看，而且不会报错。 */
assert.ok(/from '\.\/knowledgeGraphLayout'/.test(sfc), '组件没有接上径向布局模块')
assert.ok(/const layout = radialLayout\(/.test(sfc), '没有调用径向布局')
assert.ok(/layout: 'none'/.test(sfc), '坐标算好了却没告诉 ECharts 用它（layout 该是 none）')
assert.ok(!/layout: 'force'/.test(sfc), '力导向又回来了——层级会被重新揉成一坨')
assert.ok(!/force: \{/.test(sfc), '力导向参数还留着')
/* 根显式指定为业务包节点。靠「度数最大者恰好是它」是巧合，
   巧合破掉的那天，圆心会换成某个规则节点，整张图的语义就错了。 */
assert.ok(/node\.type === 'business_pack'\)\?\.id/.test(sfc), '根节点没有显式指定为业务包')
/* 树边画实、交叉边画淡。294 条边全一样重的话，
   横向交叉线会把放射结构糊掉——图「没法看」有它一半功劳。 */
assert.ok(/treeEdgeKeys/.test(sfc), '没有区分树边和交叉边')
assert.ok(/isTreeEdge \? 0\.5 : 0\.16/.test(sfc), '交叉边没有画淡')
assert.ok(/curveness: isTreeEdge \? 0 : 0\.35/.test(sfc), '交叉边没有画弯，会和树边混在一起')

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
