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

/** 会把名字写在节点里的类型。其余类型只在悬停/选中时显示标签。 */
const LABELLED_TYPES = new Set(['business_pack', 'domain_module'])

/** 节点里最多显示几个字。超出截断——不是不给看，是 tooltip 和详情里有全名。 */
const MAX_LABEL_CHARS = 12

/* 节点画成**矩形**而不是圆。
 *
 * 圆的可用宽度只有直径，中文标签一长，要么溢到球外面压住连线，
 * 要么截成「压力管道安…」。为了塞下字去放大球径，图上又全是巨型圆饼。
 * 矩形按文字长度定宽就没有这个矛盾：名字多长，框就多宽。 */
const NODE_HEIGHT_RATIO = 0.66
const LABEL_PADDING_X = 14

/** 估算文本像素宽。中日韩按一个字宽，其余按 0.56 个字宽——够定框宽了。 */
function estimateTextWidth(text: string, fontSize: number): number {
  let units = 0
  for (const ch of text) units += /[⺀-鿿＀-￯]/.test(ch) ? 1 : 0.56
  return Math.ceil(units * fontSize)
}

function clipLabel(text: string): string {
  const chars = [...String(text || '')]
  return chars.length > MAX_LABEL_CHARS ? `${chars.slice(0, MAX_LABEL_CHARS - 1).join('')}…` : chars.join('')
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
  return type === 'business_pack' ? 13 : 11
}

/** 矩形尺寸 [宽, 高]。宽度跟着标签走，没有标签的按基准尺寸做小方块。 */
function nodeRectSize(type: string, label: string): [number, number] {
  const base = SYMBOL_SIZE_BY_TYPE[type] || 18
  const height = Math.max(16, Math.round(base * NODE_HEIGHT_RATIO))
  if (!LABELLED_TYPES.has(type)) return [Math.max(16, Math.round(base * 0.8)), height]
  const text = estimateTextWidth(clipLabel(label), labelFontSize(type))
  return [Math.max(base, text + LABEL_PADDING_X * 2), height]
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
    note: '拖动节点调整位置；滚轮缩放；点击节点查看其属性和一跳关系；搜索会在当前类型范围内定位匹配对象。'
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
  const data = visibleNodes.value.map((node) => ({
    id: node.id,
    name: clipLabel(node.label),
    value: node.typeLabel,
    category: familyIndex.get(node.family) ?? familyIndex.get('semantic') ?? 0,
    /* 矩形，宽度跟着文字走。圆形的可用宽度只有直径，
     * 中文名字要么溢到外面压住连线，要么被截成「压力管道安…」。 */
    symbol: 'roundRect' as const,
    symbolSize: nodeRectSize(node.type, node.label),
    draggable: true,
    /* 标签画在框**里**：白字、居中。
     * 原先是默认位置（节点右侧）+ 主题文字色，长名字拖在外面和连线叠在一起；
     * 深色主题下还会和背景撞色。 */
    label: {
      show: LABELLED_TYPES.has(node.type),
      position: 'inside' as const,
      color: '#ffffff',
      fontSize: labelFontSize(node.type),
      fontWeight: 600
    },
    itemStyle: {
      color: colors[node.family as keyof typeof colors] || colors.semantic,
      borderColor: themeColor('--el-bg-color', '#ffffff'),
      borderWidth: selectedNodeId.value === node.id ? 4 : 1.5,
      opacity: selectedNodeId.value && selectedNodeId.value !== node.id ? 0.78 : 0.96
    },
    /* 框里的名字可能被截断，完整名字放这里给 tooltip 用——
     * 截断只是「这里放不下」，不该变成「你看不到全名」。 */
    fullName: node.label,
    nodeType: node.type,
    nodeTypeLabel: node.typeLabel,
    description: node.description
  }))
  const links = visibleEdges.value.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    edgeLabel: edge.label,
    edgeType: edge.type,
    lineStyle: {
      color: colors.edge,
      opacity: 0.45,
      width: edge.type === 'EVALUATED_BY' || edge.type === 'GOVERNED_BY' ? 1.4 : 0.8,
      curveness: 0.08
    }
  }))
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
        layout: 'force',
        data,
        links,
        categories: families.map((family) => ({
          name: FAMILY_LABELS[family],
          itemStyle: { color: colors[family as keyof typeof colors] || colors.semantic }
        })),
        roam: true,
        edgeSymbol: ['none', 'arrow'],
        edgeSymbolSize: [0, 5],
        force: {
          repulsion: data.length > 500 ? 85 : 150,
          gravity: 0.08,
          edgeLength: data.length > 500 ? [24, 70] : [48, 120],
          friction: 0.55,
          layoutAnimation: !window.matchMedia('(prefers-reduced-motion: reduce)').matches
        },
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
        labelLayout: { hideOverlap: true },
        lineStyle: { color: colors.edge, opacity: 0.45 },
        scaleLimit: { min: 0.25, max: 5 }
      }
    ]
  }
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
  }
  if (reset) chart.clear()
  chart.setOption(buildChartOption(), true)
  chart.resize()
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

watch(
  () => [visibleNodes.value, visibleEdges.value, selectedNodeId.value, appStore.getIsDark],
  () => nextTick(() => renderChart()),
  { deep: false }
)

onMounted(() => {
  if (chartHost.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => chart?.resize())
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
