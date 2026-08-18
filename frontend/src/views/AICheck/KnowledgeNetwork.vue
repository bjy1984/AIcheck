<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElDescriptions,
  ElDescriptionsItem,
  ElEmpty,
  ElInput,
  ElOption,
  ElSelect,
  ElSkeleton,
  ElTag
} from 'element-plus'
import type { EChartsOption } from 'echarts'
import echarts from '@/plugins/echarts'
import { getKnowledgeNetworkApi } from '@/api/aicheck'
import {
  ADMIN_BOUNDARY_BADGE,
  ADMIN_BOUNDARY_TITLE,
  ADMIN_MENU_ROOT,
  ADMIN_MENU_TITLE,
  buildAdminMenuSections
} from './adminMenuTree'
import type { KnowledgeNetworkNode, KnowledgeNetworkPayload } from '@/api/aicheck'
import { useAppStore } from '@/store/modules/app'
import { useUserStore } from '@/store/modules/user'
import { getAicheckErrorMessage } from '@/utils/aicheckError'
import StaticPageShell from './components/StaticPageShell.vue'
import { radialLayout } from './knowledgeGraphLayout'

const DEFAULT_BUSINESS_PACK_ID = 'engineering_inspection_v1'
const DEFAULT_VISIBLE_TYPES = [
  'business_pack',
  'domain_module',
  'inspection_node',
  'rule',
  'clause_package',
  'standard'
]

const FAMILY_LABELS: Record<string, string> = {
  business: '业务结构',
  evidence: '资料证据',
  rule: '规则约束',
  semantic: '事实语义',
  standard: '标准条款',
  execution: 'Agent 与 Tool'
}

/* 每个节点都写名字。
 *
 * 原先只有 business_pack / domain_module 显示标签，其余十几种类型
 * （规则、标准条款、原子检查项、项目、工具……）在图上就是一个个纯色块——
 * **看得见有东西，但不知道是什么**，只能一个个悬停去问。
 * 那是圆形时代的妥协：圆里塞不下字，只好给大类留标签。
 * 现在框宽跟着文字走，这个妥协没有理由继续存在。 */

const MAJOR_TYPES = new Set(['business_pack', 'domain_module'])

/* 节点画成**矩形**而不是圆。
 *
 * 圆的可用宽度只有直径，中文标签一长，要么溢到球外面压住连线，
 * 要么截成「压力管道安…」。为了塞下字去放大球径，图上又全是巨型圆饼。
 * 矩形按文字长度定宽就没有这个矛盾：名字多长，框就多宽。 */
const LABEL_PADDING_X = 6
const LABEL_PADDING_Y = 4

/* 标签**默认最多 10 个字符**，超出截断加省略号。
 *
 * 中间试过一版「一个字都不省略、长了折行」：259 个全名矩形把周长需求
 * 推到几万像素，整图 fit 之后缩没了——用户的反馈是「根本没法看」。
 * 图上的标签是**索引**，不是文档：认得出是哪一条就够了，
 * 全名在 tooltip（fullName）和右侧详情里，一直都拿得到。 */
const MAX_LABEL_CHARS = 10

function truncateLabel(text: string): string {
  const chars = [...String(text || '')]
  return chars.length > MAX_LABEL_CHARS
    ? `${chars.slice(0, MAX_LABEL_CHARS).join('')}…`
    : chars.join('')
}

/** 单字像素宽。中日韩按一个字宽，其余按 0.56 个字宽——够定框宽了。 */
function charWidth(ch: string, fontSize: number): number {
  return (/[⺀-鿿＀-￯]/.test(ch) ? 1 : 0.56) * fontSize
}

function estimateTextWidth(text: string, fontSize: number): number {
  let width = 0
  for (const ch of text) width += charWidth(ch, fontSize)
  return Math.ceil(width)
}

const SYMBOL_SIZE_BY_TYPE: Record<string, number> = {
  business_pack: 54,
  domain_module: 36,
  inspection_node: 25,
  project: 30,
  rule: 24,
  atomic_check: 18,
  clause_package: 23,
  required_fact: 14,
  standard: 28,
  standard_clause: 16,
  material_type: 18,
  knowledge_source: 24,
  knowledge_file: 16,
  tool: 16,
  thinking_mode: 18,
  agent: 30
}

function labelFontSize(type: string): number {
  if (type === 'business_pack') return 13
  return MAJOR_TYPES.has(type) ? 12 : 10
}

function lineHeightOf(type: string): number {
  return labelFontSize(type) + 4
}

/** 矩形尺寸 [宽, 高]。单行：宽按截断后的文字，高按一行字加内边距。
 *  定宽必须用**截断后**的文字——用全名定宽的话，框又会被撑回长条。 */
function nodeRectSize(type: string, label: string): [number, number] {
  const fontSize = labelFontSize(type)
  const text = estimateTextWidth(truncateLabel(label), fontSize)
  const width = Math.max(SYMBOL_SIZE_BY_TYPE[type] || 18, text + LABEL_PADDING_X * 2)
  const height = lineHeightOf(type) + LABEL_PADDING_Y * 2
  return [width, height]
}

const graph = ref<KnowledgeNetworkPayload | null>(null)
const loading = ref(false)
const loadError = ref('')
const keyword = ref('')
const selectedTypes = ref<string[]>([])
const selectedNodeId = ref('')
const chartHost = ref<HTMLDivElement>()
const appStore = useAppStore()
const userStore = useUserStore()

let chart: echarts.ECharts | null = null
let resizeObserver: ResizeObserver | null = null

/* 用户正在图上按着鼠标（拖动/缩放）时，不许重绘。
 *
 * setOption 会重建图元。**正在被拖的那个图元一旦被换掉，手势就断了**——
 * 手还按着，图却不动了。这就是「拖拽有时失灵」里剩下的那一半：
 * 前面修掉的是「重绘把视图清零」，这里修的是「重绘把手势打断」。
 * 时机决定了它必然是偶发的：只有重绘恰好落在拖动过程中才会发生。
 *
 * 重绘请求不丢，攒着，等手松开再执行。 */
let interacting = false
let pendingRender = false

const userLabel = computed(
  () =>
    userStore.getUserInfo?.displayName ||
    userStore.getUserInfo?.username ||
    userStore.getUserInfo?.roleLabel ||
    '系统管理员'
)

/* 菜单来自 adminMenuTree —— 后台只有一棵树。
 * 这一页原先自带第三份定义、根名字叫「AI 知识库」，
 * 于是同一个后台在三个页面上显示三副面孔，进来之后 admin 的分组还会消失。
 * 这一页没有 route 对象，用它自己的固定路径高亮。 */
const menuSections = computed(() => buildAdminMenuSections('/knowledge/network'))

const boundaryRows = [
  { label: '模式层', value: '业务包、节点、资料、规则、条款、事实与 Tool' },
  { label: '实例层', value: '当前项目和知识文件（按运行数据动态加入）' },
  { label: '来源', value: '发布 YAML、标准条款包和知识库运行状态' },
  { label: '边界', value: '网络只用于检索、解释与治理，不自动签发结论' }
]

const topStats = computed(() => [
  {
    key: 'nodes',
    label: '节点',
    value: graph.value?.summary.nodeCount || 0,
    tone: 'blue' as const
  },
  {
    key: 'edges',
    label: '关系',
    value: graph.value?.summary.edgeCount || 0,
    tone: 'green' as const
  },
  { key: 'visible', label: '当前显示', value: visibleNodes.value.length, tone: 'orange' as const }
])

const rightCards = computed(() => [
  {
    title: '知识网络版本',
    rows: [
      { label: 'Schema', value: graph.value?.schemaVersion || '--' },
      { label: '业务包', value: graph.value?.businessPackVersion || '--' },
      { label: '节点类型', value: String(graph.value?.nodeTypes.length || 0) },
      { label: '关系类型', value: String(graph.value?.edgeTypes.length || 0) }
    ]
  },
  {
    title: '当前视图',
    rows: [
      { label: '显示节点', value: String(visibleNodes.value.length) },
      { label: '显示关系', value: String(visibleEdges.value.length) },
      { label: '类型筛选', value: String(selectedTypes.value.length) },
      { label: '选中对象', value: selectedNode.value?.label || '--' }
    ]
  },
  {
    title: '使用说明',
    /* 这句话必须跟着行为改。原先写的是「拖动节点调整位置」，
     * 节点改成不可拖之后它就成了假说明——照着做没反应，
     * 用户只会以为是页面坏了。 */
    note: '拖动空白处平移画布；滚轮缩放；点击节点查看其属性和一跳关系；搜索会在当前类型范围内定位匹配对象。'
  }
])

const typeOptions = computed(() => graph.value?.nodeTypes || [])
const nodeById = computed(() => new Map((graph.value?.nodes || []).map((node) => [node.id, node])))

const normalizedKeyword = computed(() => keyword.value.trim().toLocaleLowerCase())

const typeFilteredNodes = computed(() => {
  const allowed = new Set(selectedTypes.value)
  return (graph.value?.nodes || []).filter((node) => allowed.has(node.type))
})

const visibleNodes = computed(() => {
  const query = normalizedKeyword.value
  if (!query) return typeFilteredNodes.value
  const candidates = typeFilteredNodes.value
  const matchedIds = new Set(
    candidates
      .filter((node) => {
        const haystack = [
          node.id,
          node.label,
          node.typeLabel,
          node.description,
          node.group,
          node.status,
          JSON.stringify(node.metadata)
        ]
          .filter(Boolean)
          .join(' ')
          .toLocaleLowerCase()
        return haystack.includes(query)
      })
      .map((node) => node.id)
  )
  if (!matchedIds.size) return []
  const allowedIds = new Set(candidates.map((node) => node.id))
  for (const edge of graph.value?.edges || []) {
    if (matchedIds.has(edge.source) && allowedIds.has(edge.target)) matchedIds.add(edge.target)
    if (matchedIds.has(edge.target) && allowedIds.has(edge.source)) matchedIds.add(edge.source)
  }
  return candidates.filter((node) => matchedIds.has(node.id))
})

const visibleEdges = computed(() => {
  const ids = new Set(visibleNodes.value.map((node) => node.id))
  return (graph.value?.edges || []).filter((edge) => ids.has(edge.source) && ids.has(edge.target))
})

const selectedNode = computed(() => nodeById.value.get(selectedNodeId.value) || null)

const selectedRelations = computed(() => {
  if (!selectedNode.value || !graph.value) return []
  return graph.value.edges
    .filter(
      (edge) => edge.source === selectedNode.value?.id || edge.target === selectedNode.value?.id
    )
    .map((edge) => {
      const outgoing = edge.source === selectedNode.value?.id
      const peerId = outgoing ? edge.target : edge.source
      return {
        ...edge,
        direction: outgoing ? 'outgoing' : 'incoming',
        peer: nodeById.value.get(peerId)
      }
    })
    .sort((left, right) => left.label.localeCompare(right.label, 'zh-CN'))
    .slice(0, 40)
})

const selectedMetadata = computed(() =>
  Object.entries(selectedNode.value?.metadata || {}).map(([key, value]) => ({
    key,
    value: formatMetadataValue(value)
  }))
)

function formatMetadataValue(value: unknown) {
  if (value === null || value === undefined || value === '') return '--'
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value, null, 2)
}

function escapeHtml(value: unknown) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;')
}

function themeColor(name: string, fallback: string) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

function chartColors() {
  return {
    business: themeColor('--el-color-primary', '#3b82f6'),
    evidence: themeColor('--el-color-success', '#10b981'),
    rule: themeColor('--el-color-warning', '#f59e0b'),
    semantic: themeColor('--el-color-danger', '#ef4444'),
    standard: themeColor('--el-color-info', '#8b5cf6'),
    execution: themeColor('--el-color-primary-light-3', '#38bdf8'),
    edge: themeColor('--el-border-color', '#cbd5e1'),
    text: themeColor('--el-text-color-primary', '#1f2937'),
    muted: themeColor('--el-text-color-secondary', '#64748b')
  }
}

const graphPane = ref<HTMLElement | null>(null)
const isFullscreen = ref(false)

/* 全屏切换。
 *
 * 两个容易漏的点：
 * 1. **退出全屏不一定经过按钮**——Esc、F11、浏览器手势都会退出，
 *    所以状态要跟着 fullscreenchange 事件走，不能只在点击时取反，
 *    否则退出后按钮还写着「退出全屏」。
 * 2. 容器尺寸变了必须 resize 图表，否则全屏后画布还是原来那么大，
 *    看起来像「点了没反应」。
 */
const syncFullscreenState = () => {
  isFullscreen.value = document.fullscreenElement === graphPane.value
  nextTick(() => chart?.resize())
}

const toggleGraphFullscreen = async () => {
  const host = graphPane.value
  if (!host) return
  try {
    if (document.fullscreenElement) {
      await document.exitFullscreen()
    } else {
      await host.requestFullscreen()
    }
  } catch {
    // 浏览器可能拒绝（权限策略、iframe 限制）。退回普通视图，不弹错——
    // 用户点的是「看大一点」，失败了保持原样即可，不必打断他。
    isFullscreen.value = false
  }
}

function buildChartOption(): EChartsOption {
  const colors = chartColors()
  const families = Object.keys(FAMILY_LABELS)
  const familyIndex = new Map(families.map((family, index) => [family, index]))
  /* 确定性径向分层布局，替掉力导向。
   * 这份数据是层级（业务包→模块→节点→条款），力导向把层级揉成一坨
   * 互相压的矩形——「知识图谱根本没法看」。理由与几何约束见
   * knowledgeGraphLayout.ts 的文件头。根固定用业务包节点：
   * 度数最大者通常就是它，但显式指定不依赖这个巧合。 */
  const rootId = visibleNodes.value.find((node) => node.type === 'business_pack')?.id
  const layout = radialLayout(
    visibleNodes.value.map((node) => {
      const [width, height] = nodeRectSize(node.type, node.label)
      return { id: node.id, width, height }
    }),
    visibleEdges.value.map((edge) => ({ source: edge.source, target: edge.target })),
    rootId
  )
  const data = visibleNodes.value.map((node) => ({
    id: node.id,
    x: layout.positions.get(node.id)?.x ?? 0,
    y: layout.positions.get(node.id)?.y ?? 0,
    name: truncateLabel(node.label),
    value: node.typeLabel,
    category: familyIndex.get(node.family) ?? familyIndex.get('semantic') ?? 0,
    /* 直角矩形，宽度跟着文字走。圆形的可用宽度只有直径，
     * 中文名字要么溢到外面压住连线，要么被截成「压力管道安…」。 */
    symbol: 'rect' as const,
    symbolSize: nodeRectSize(node.type, node.label),
    /* 节点不可拖。
     *
     * 可拖的时候，鼠标按在节点上是「拖这个点」，按在空白处才是「平移画布」。
     * 圆形时代节点小，多数落点是空白，问题不明显；换成矩形后节点占的面积
     * 大了好几倍，随手一拖经常拖的是某个节点——在用户看来就是「滑动失灵」。
     * 平移是主要操作，挪单个节点不是；坐标由布局统一算，单独挪一个只会破坏环形结构。 */
    draggable: false,
    /* 标签画在框**里**：白字、居中，每个节点都有。
     * 原先是默认位置（节点右侧）+ 主题文字色，长名字拖在外面和连线叠在一起；
     * 深色主题下还会和背景撞色。 */
    label: {
      show: true,
      position: 'inside' as const,
      color: '#ffffff',
      fontSize: labelFontSize(node.type),
      lineHeight: lineHeightOf(node.type),
      fontWeight: 600
    },
    /* 选中态**不写在这里**。
     *
     * 原先 borderWidth / opacity 都读 selectedNodeId，于是点一下节点就要重建
     * 整个 option——而重建会把画布的平移缩放一起清掉，手一松图就弹回原位。
     * 「滑动有时失灵」就是这么来的。选中交给 series.select.itemStyle，
     * 用 dispatchAction 切换，不碰 option。 */
    itemStyle: {
      color: colors[node.family as keyof typeof colors] || colors.semantic,
      borderColor: themeColor('--el-bg-color', '#ffffff'),
      borderWidth: 1.5,
      opacity: 0.96
    },
    /* 框里显示的是折行后的名字，原始名字放这里给 tooltip 用。 */
    fullName: node.label,
    nodeType: node.type,
    nodeTypeLabel: node.typeLabel,
    description: node.description
  }))
  const links = visibleEdges.value.map((edge) => {
    /* 树边（层级骨架）画实、交叉边画淡画弯。294 条边全一样重的话，
       横向交叉线会把放射结构糊掉——图「没法看」有它一半功劳。 */
    const isTreeEdge =
      layout.treeEdgeKeys.has(`${edge.source}->${edge.target}`) ||
      layout.treeEdgeKeys.has(`${edge.target}->${edge.source}`)
    return {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      edgeLabel: edge.label,
      edgeType: edge.type,
      lineStyle: {
        color: colors.edge,
        opacity: isTreeEdge ? 0.5 : 0.16,
        width: isTreeEdge ? 1.2 : 0.8,
        curveness: isTreeEdge ? 0 : 0.35
      }
    }
  })
  return {
    animationDurationUpdate: 280,
    backgroundColor: 'transparent',
    aria: {
      enabled: true,
      description: `知识网络，当前显示 ${data.length} 个节点和 ${links.length} 条关系。`
    },
    tooltip: {
      trigger: 'item',
      confine: true,
      formatter: (params: unknown) => {
        const item = params as { dataType?: string; data?: Record<string, unknown> }
        const datum = item.data || {}
        if (item.dataType === 'edge') {
          return `<strong>${escapeHtml(datum.edgeLabel)}</strong><br/><span>${escapeHtml(datum.edgeType)}</span>`
        }
        return `<strong>${escapeHtml(datum.fullName ?? datum.name)}</strong><br/><span>${escapeHtml(datum.nodeTypeLabel)}</span>${datum.description ? `<br/><span>${escapeHtml(datum.description)}</span>` : ''}`
      }
    },
    legend: [
      {
        type: 'scroll',
        top: 6,
        left: 8,
        right: 8,
        textStyle: { color: colors.muted },
        data: families.map((family) => FAMILY_LABELS[family])
      }
    ],
    series: [
      {
        type: 'graph',
        /* 坐标已由 radialLayout 算好——确定性布局，打开即稳定。
           不再有「布局一直在漂、定位对不准、截图判据被动画污染」那一类问题。 */
        layout: 'none',
        data,
        links,
        categories: families.map((family) => ({
          name: FAMILY_LABELS[family],
          itemStyle: { color: colors[family as keyof typeof colors] || colors.semantic }
        })),
        roam: true,
        edgeSymbol: ['none', 'arrow'],
        edgeSymbolSize: [0, 5],
        emphasis: {
          focus: 'adjacency',
          // 悬停态也要白字居中：只改静态样式的话，鼠标一移上去标签又跳回球外。
          label: { show: true, position: 'inside', color: '#ffffff', fontWeight: 600 },
          lineStyle: { opacity: 0.9, width: 2 }
        },
        blur: {
          itemStyle: { opacity: 0.18 },
          lineStyle: { opacity: 0.08 }
        },
        select: {
          itemStyle: {
            borderColor: themeColor('--el-text-color-primary', '#111827'),
            borderWidth: 4
          },
          label: { show: true, position: 'inside', color: '#ffffff', fontWeight: 600 }
        },
        selectedMode: 'single',
        /* hideOverlap 必须开。
         *
         * roam 缩放只缩放坐标和符号，**标签字号是固定像素**：布局尺度下
         * 零重叠的几何，在「适配全图」的默认视角（zoom≈0.15）仍是一墙文字
         * 压文字——线上 259 个节点的全景就是这么糊掉的。
         * 开了之后：全景挤不下的标签自动隐藏（节点缩成彩色小块，颜色即类别），
         * 放大到 1:1 附近，几何保证生效，标签一个不隐。
         * 之前担心的「隐掉标签变无名色块」只发生在缩得很小时——那时字本来
         * 也读不了，色块反而是正确的表达。 */
        labelLayout: { hideOverlap: true },
        lineStyle: { color: colors.edge, opacity: 0.45 },
        scaleLimit: { min: 0.2, max: 12 }
      }
    ]
  }
}

/* 「点一跳关系把视图定位过去」——**尚未实现**，五种做法线上都验过无效。
 *
 * 补记：现在布局换成了确定性 radial（见 knowledgeGraphLayout.ts），
 * 坐标不再漂移，「点击那一刻的坐标两秒后就不对了」这层障碍已经不存在。
 * 若要重做定位，别再从下面五条老路里挑，先从 fitView/dataZoom 方向验证。
 *
 * 记录在这里，免得下一个人再走一遍：
 *   1. setOption({series:[{center,zoom}]}) 合并式下发 —— 视图不动
 *   2. 等布局 finished 之后再下发一次 —— 仍不动
 *   3. dispatchAction graphRoam 算 dx/dy —— 动了，但位移对不上
 *   4. 和 layout:'none' 放同一次 setOption —— 不动
 *   5. notMerge 整份下发 —— 视图回到默认铺开，中心永远是 hub 节点「工业管道」
 *
 * 共同现象：视图最终总是回到「按包围盒自动铺开」的状态，
 * 也就是 center 根本没被采纳。原因还没查清。
 *
 * 曾经带着第 5 版上线过一阵，副作用是**点一跳关系会把视图重置**——
 * 比不做更糟，所以撤掉了。现在点一跳关系只选中，不动视图。 */

/** 把选中态推给图表——用 action，不重建 option，这样不会丢平移缩放。 */
function syncSelectionToChart() {
  if (!chart) return
  chart.dispatchAction({ type: 'unselect', seriesIndex: 0 })
  if (!selectedNodeId.value) return
  const index = visibleNodes.value.findIndex((node) => node.id === selectedNodeId.value)
  if (index >= 0) chart.dispatchAction({ type: 'select', seriesIndex: 0, dataIndex: index })
}

function renderChart(reset = false) {
  if (!chartHost.value || loading.value) return
  if (!chartHost.value.clientWidth || !chartHost.value.clientHeight) {
    requestAnimationFrame(() => {
      if (chartHost.value?.clientWidth && chartHost.value?.clientHeight) renderChart(reset)
    })
    return
  }
  if (!chart) {
    chart = echarts.init(chartHost.value)
    chart.on('click', (params: unknown) => {
      const event = params as { dataType?: string; data?: { id?: string } }
      if (event.dataType === 'node' && event.data?.id) {
        selectedNodeId.value = String(event.data.id)
      }
    })
    /* 手按下去到松开之间不重绘。globalout 也要收——鼠标拖出画布外松开时
     * 不会有 mouseup，漏掉这一路会把 interacting 永久卡在 true，
     * 那样图就再也不刷新了：一个比原问题更难查的静默故障。 */
    const zr = chart.getZr()
    const endInteraction = () => {
      if (!interacting) return
      interacting = false
      if (pendingRender) {
        pendingRender = false
        renderChart()
      }
    }
    zr.on('mousedown', () => {
      interacting = true
    })
    zr.on('mouseup', endInteraction)
    zr.on('globalout', endInteraction)
  }
  /* 拖到一半来的重绘，攒着等松手——直接重绘会把正在拖的图元换掉，手势就断了。
   * reset 是用户主动要求重置视图，那时没有正在进行的手势，不用等。 */
  if (interacting && !reset) {
    pendingRender = true
    return
  }
  /* notMerge 只在**明确要重置视图**时用（首次加载、点「重置视图」）。
   *
   * 原先每次 setOption 都传 true，等于每次重画都把画布的平移缩放清零。
   * 而重画的触发点很多——筛选类型、搜索、切主题、选中节点——
   * 用户拖到一半只要碰上一次，图就弹回原位，看起来就是「滑动失灵」。 */
  if (reset) chart.clear()
  chart.setOption(buildChartOption(), { notMerge: reset, lazyUpdate: true })
  /* 只有重置时才 resize。容器尺寸变化由 ResizeObserver 负责——
   * 每次重绘都无脑 resize 是多余的一次重排，也多一次打断手势的机会。 */
  if (reset) chart.resize()
  syncSelectionToChart()
}

function resetView() {
  selectedNodeId.value = ''
  renderChart(true)
}

function showAllTypes() {
  selectedTypes.value = typeOptions.value.map((item) => item.type)
}

function restoreCoreTypes() {
  selectedTypes.value = DEFAULT_VISIBLE_TYPES.filter((type) =>
    typeOptions.value.some((item) => item.type === type)
  )
  keyword.value = ''
  selectedNodeId.value = ''
}

function selectRelatedNode(node: KnowledgeNetworkNode | undefined) {
  if (!node) return
  if (!selectedTypes.value.includes(node.type))
    selectedTypes.value = [...selectedTypes.value, node.type]
  keyword.value = ''
  selectedNodeId.value = node.id
  /* 注意：这里**不会把视图移到那个节点上**。
   * 定位试过五种做法，线上都验证无效，详见上面 layoutSettled 附近的记录。
   * 节点在屏幕外时，用户仍然只能看到右侧详情变了，图上没动静。 */
  nextTick(() => renderChart())
}

async function loadGraph() {
  loading.value = true
  loadError.value = ''
  try {
    const response = await getKnowledgeNetworkApi({
      businessPackId: DEFAULT_BUSINESS_PACK_ID,
      includeRuntime: true
    })
    if (response.code !== 0 || !response.data) {
      throw new Error('知识网络接口未返回有效数据。')
    }
    graph.value = response.data
    selectedTypes.value = DEFAULT_VISIBLE_TYPES.filter((type) =>
      response.data.nodeTypes.some((item) => item.type === type)
    )
    selectedNodeId.value = `business-pack:${response.data.businessPackId}`
    await nextTick()
    renderChart(true)
  } catch (error) {
    loadError.value = getAicheckErrorMessage(error, '知识网络加载失败，请检查接口或业务包状态。')
  } finally {
    loading.value = false
    await nextTick()
    if (!loadError.value) renderChart(true)
  }
}

/* 数据/主题变了才重画。
 * selectedNodeId **不在这里**——选中只是换个描边，却会连带重建 option，
 * 把用户拖好的视图清零。它走 syncSelectionToChart。 */
watch(
  () => [visibleNodes.value, visibleEdges.value, appStore.getIsDark],
  () => nextTick(() => renderChart()),
  { deep: false }
)

watch(selectedNodeId, () => syncSelectionToChart())

onMounted(() => {
  if (chartHost.value && typeof ResizeObserver !== 'undefined') {
    // 拖动中不 resize：选中节点会让右侧详情变高，容器跟着抖一下，
    // 这一下 resize 足够把正在进行的拖动打断。
    resizeObserver = new ResizeObserver(() => {
      if (interacting) return
      chart?.resize()
    })
    resizeObserver.observe(chartHost.value)
  }
  // 退出全屏可以不经过按钮（Esc / F11 / 浏览器手势），所以听事件而不是在点击时取反
  document.addEventListener('fullscreenchange', syncFullscreenState)
  loadGraph()
})

onBeforeUnmount(() => {
  document.removeEventListener('fullscreenchange', syncFullscreenState)
  resizeObserver?.disconnect()
  resizeObserver = null
  chart?.dispose()
  chart = null
})
</script>

<template>
  <StaticPageShell
    brand-mark="KB"
    title="AI 知识库管理"
    :status="loadError ? '知识网络异常' : loading ? '知识网络构建中' : '知识网络可用'"
    :status-tone="loadError ? 'red' : loading ? 'orange' : 'green'"
    search-placeholder="搜索知识库、标准、规则或项目"
    :user-label="userLabel"
    :top-stats="topStats"
    :menu-title="ADMIN_MENU_TITLE"
    :menu-root="ADMIN_MENU_ROOT"
    :menu-sections="menuSections"
    :boundary-title="ADMIN_BOUNDARY_TITLE"
    :boundary-badge="ADMIN_BOUNDARY_BADGE"
    boundary-tone="green"
    :boundary-rows="boundaryRows"
    right-title="网络说明"
    :right-subtitle="
      graph ? `${graph.businessPackId} · ${graph.businessPackVersion}` : '正在读取版本'
    "
    :right-cards="rightCards"
    workspace-mode="wide"
    right-panel-mode="drawer"
    right-toggle-label="网络信息"
    search-scope="knowledge"
    task-area="knowledge"
  >
    <section class="knowledge-network-page" aria-labelledby="knowledge-network-heading">
      <ElCard shadow="never" class="network-toolbar-card">
        <div class="network-heading-row">
          <div>
            <h2 id="knowledge-network-heading">工业管道监督检验知识网络</h2>
            <p>从现有业务包、规则、条款、资料类型、事实路径和 Tool 绑定实时编译。</p>
          </div>
          <div class="network-version-tags">
            <ElTag effect="plain">{{ graph?.schemaVersion || '--' }}</ElTag>
            <ElTag type="success" effect="plain">{{ graph?.businessPackVersion || '--' }}</ElTag>
          </div>
        </div>

        <div class="network-controls" aria-label="知识网络筛选">
          <ElInput
            v-model="keyword"
            clearable
            placeholder="搜索节点、规则、事实、标准或 Tool"
            aria-label="搜索知识网络"
          />
          <ElSelect
            v-model="selectedTypes"
            multiple
            collapse-tags
            collapse-tags-tooltip
            placeholder="选择节点类型"
            aria-label="选择节点类型"
          >
            <ElOption
              v-for="item in typeOptions"
              :key="item.type"
              :label="`${item.label}（${item.count}）`"
              :value="item.type"
            />
          </ElSelect>
          <div class="network-control-actions">
            <ElButton @click="restoreCoreTypes">核心网络</ElButton>
            <ElButton @click="showAllTypes">显示全部</ElButton>
            <ElButton @click="resetView">重置视图</ElButton>
            <ElButton type="primary" :loading="loading" @click="loadGraph">重新构建</ElButton>
          </div>
        </div>
      </ElCard>

      <ElAlert
        v-if="loadError"
        class="network-error"
        type="error"
        :title="loadError"
        :closable="false"
        show-icon
      >
        <template #default>
          <ElButton size="small" type="primary" plain @click="loadGraph">重新加载</ElButton>
        </template>
      </ElAlert>

      <ElCard shadow="never" class="network-surface-card">
        <div class="network-surface-header">
          <div>
            <strong>关系网络</strong>
            <span>{{ visibleNodes.length }} 个节点 · {{ visibleEdges.length }} 条关系</span>
          </div>
          <ElTag v-if="keyword" type="info" effect="plain">搜索：{{ keyword }}</ElTag>
        </div>

        <div class="network-layout">
          <div ref="graphPane" class="graph-pane">
            <!-- 全屏：关系图在半个屏幕里根本看不清，节点一多就挤成一团。 -->
            <ElButton
              class="graph-fullscreen-btn"
              size="small"
              :title="isFullscreen ? '退出全屏（Esc）' : '全屏查看'"
              @click="toggleGraphFullscreen"
            >
              {{ isFullscreen ? '退出全屏' : '全屏' }}
            </ElButton>
            <ElSkeleton v-if="loading" animated :rows="12" />
            <ElEmpty v-else-if="!visibleNodes.length" description="当前条件下没有匹配的知识节点" />
            <div
              v-show="!loading && visibleNodes.length"
              ref="chartHost"
              class="knowledge-graph"
              role="img"
              :aria-label="`知识网络，显示 ${visibleNodes.length} 个节点和 ${visibleEdges.length} 条关系`"
            ></div>
          </div>

          <aside class="node-detail" aria-label="知识节点详情">
            <ElEmpty v-if="!selectedNode" description="点击网络节点查看详情" />
            <template v-else>
              <div class="node-detail-heading">
                <div>
                  <ElTag effect="plain">{{ selectedNode.typeLabel }}</ElTag>
                  <ElTag v-if="selectedNode.status" type="info" effect="plain">
                    {{ selectedNode.status }}
                  </ElTag>
                </div>
                <h3>{{ selectedNode.label }}</h3>
                <p v-if="selectedNode.description">{{ selectedNode.description }}</p>
                <code>{{ selectedNode.id }}</code>
              </div>

              <ElDescriptions
                v-if="selectedMetadata.length"
                class="node-metadata"
                :column="1"
                border
                size="small"
              >
                <ElDescriptionsItem
                  v-for="item in selectedMetadata.slice(0, 12)"
                  :key="item.key"
                  :label="item.key"
                >
                  <pre>{{ item.value }}</pre>
                </ElDescriptionsItem>
              </ElDescriptions>

              <div class="relation-heading">
                <strong>一跳关系</strong>
                <ElTag effect="plain">{{ selectedRelations.length }}</ElTag>
              </div>
              <div class="relation-list">
                <button
                  v-for="relation in selectedRelations"
                  :key="relation.id"
                  type="button"
                  class="relation-row"
                  @click="selectRelatedNode(relation.peer)"
                >
                  <span>{{ relation.direction === 'outgoing' ? '→' : '←' }}</span>
                  <div>
                    <small>{{ relation.label }}</small>
                    <strong>{{ relation.peer?.label || '未知节点' }}</strong>
                  </div>
                  <ElTag size="small" effect="plain">{{ relation.peer?.typeLabel || '--' }}</ElTag>
                </button>
              </div>
            </template>
          </aside>
        </div>
      </ElCard>
    </section>
  </StaticPageShell>
</template>

<style scoped>
.knowledge-network-page {
  display: grid;
  min-width: 0;
  gap: 14px;
}

.network-toolbar-card,
.network-surface-card {
  border-color: var(--el-border-color-light);
}

.network-heading-row,
.network-surface-header,
.relation-heading {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
}

.network-heading-row h2 {
  margin: 0;
  color: var(--el-text-color-primary);
  font-size: 18px;
  font-weight: 500;
  line-height: 26px;
}

.network-heading-row p,
.network-surface-header span,
.node-detail-heading p {
  margin: 4px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 20px;
}

.network-version-tags,
.network-control-actions,
.node-detail-heading > div {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.network-controls {
  display: grid;
  grid-template-columns: minmax(220px, 0.8fr) minmax(280px, 1.2fr) auto;
  gap: 10px;
  margin-top: 16px;
  align-items: center;
}

.network-control-actions {
  justify-content: flex-end;
}

.network-error {
  align-items: center;
}

.network-surface-card :deep(.el-card__body) {
  padding: 0;
}

.network-surface-header {
  min-height: 52px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--el-border-color-light);
}

.network-surface-header > div {
  display: flex;
  gap: 10px;
  align-items: baseline;
}

.network-surface-header strong,
.relation-heading strong {
  color: var(--el-text-color-primary);
  font-size: 14px;
  font-weight: 500;
}

.network-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(290px, 340px);
  min-height: 680px;
}

/* 全屏时铺满整屏。:fullscreen 下容器脱离原布局，
   不给高度的话画布会塌成 0 高——「点了全屏结果一片空白」。 */
.graph-pane:fullscreen {
  width: 100vw;
  height: 100vh;
  padding: 12px;
  background: var(--el-bg-color, #fff);
}

.graph-pane:fullscreen .knowledge-graph {
  height: calc(100vh - 24px);
}

.graph-fullscreen-btn {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 5;
}

.graph-pane {
  /* 全屏按钮用 absolute 定位，这里必须是定位上下文——
     不加的话按钮会挂到更外层的祖先上，飘到页面别处去。 */
  position: relative;
  min-width: 0;
  min-height: 680px;
  padding: 8px;
}

.knowledge-graph {
  width: 100%;
  height: 664px;
  min-height: 520px;
  outline: none;
}

.node-detail {
  min-width: 0;
  padding: 16px;
  background: var(--el-fill-color-lighter);
  border-left: 1px solid var(--el-border-color-light);
}

.node-detail-heading {
  display: grid;
  gap: 8px;
}

.node-detail-heading h3 {
  margin: 0;
  color: var(--el-text-color-primary);
  font-size: 16px;
  font-weight: 500;
  line-height: 24px;
}

.node-detail-heading code {
  display: block;
  overflow-wrap: anywhere;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.node-metadata {
  margin-top: 16px;
}

.node-metadata pre {
  max-width: 100%;
  margin: 0;
  overflow-wrap: anywhere;
  color: var(--el-text-color-regular);
  font-family: inherit;
  font-size: 12px;
  line-height: 18px;
  white-space: pre-wrap;
}

.relation-heading {
  margin: 18px 0 8px;
}

.relation-list {
  display: grid;
  gap: 6px;
}

.relation-row {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr) auto;
  width: 100%;
  min-height: 52px;
  padding: 8px;
  color: var(--el-text-color-regular);
  text-align: left;
  cursor: pointer;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-light);
  border-radius: var(--el-border-radius-base);
  gap: 8px;
  align-items: center;
}

.relation-row:hover,
.relation-row:focus-visible {
  background: var(--el-color-primary-light-9);
  border-color: var(--el-color-primary-light-5);
  outline: 2px solid var(--el-color-primary-light-7);
  outline-offset: 1px;
}

.relation-row div {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.relation-row small {
  color: var(--el-text-color-secondary);
  font-size: 11px;
}

.relation-row strong {
  overflow: hidden;
  color: var(--el-text-color-primary);
  font-size: 12px;
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (width <= 1180px) {
  .network-controls {
    grid-template-columns: 1fr 1fr;
  }

  .network-control-actions {
    grid-column: 1 / -1;
    justify-content: flex-start;
  }

  .network-layout {
    grid-template-columns: minmax(0, 1fr) minmax(260px, 300px);
  }
}

@media (width <= 820px) {
  .network-heading-row,
  .network-surface-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .network-controls,
  .network-layout {
    grid-template-columns: 1fr;
  }

  .network-control-actions {
    grid-column: auto;
  }

  .network-layout,
  .graph-pane {
    min-height: 540px;
  }

  .knowledge-graph {
    height: 524px;
  }

  .node-detail {
    border-top: 1px solid var(--el-border-color-light);
    border-left: 0;
  }
}
</style>
