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

const menuSections = [
  {
    id: 'knowledge-network-navigation',
    title: '知识库管理',
    meta: '现有知识资产',
    defaultOpen: true,
    items: [
      {
        index: '01',
        label: '知识库总览',
        badge: '总览',
        tone: 'green' as const,
        route: '/knowledge/overview'
      },
      {
        index: '02',
        label: '标准规范库',
        badge: '标准',
        tone: 'blue' as const,
        route: '/knowledge/sources'
      },
      {
        index: '03',
        label: '项目文件知识库',
        badge: '项目',
        tone: 'green' as const,
        route: '/knowledge/files'
      },
      {
        index: '04',
        label: '任务中心',
        badge: '任务',
        tone: 'orange' as const,
        route: '/knowledge/tasks'
      },
      {
        index: '05',
        label: '监检业务判断规则管理',
        badge: '规则',
        tone: 'blue' as const,
        route: '/knowledge/rules'
      },
      {
        index: '06',
        label: '知识检索测试',
        badge: '测试',
        tone: 'blue' as const,
        route: '/knowledge/retrieval'
      },
      {
        index: '07',
        label: '知识网络',
        badge: '当前',
        tone: 'green' as const,
        route: '/knowledge/network',
        active: true
      },
      {
        index: '08',
        label: '推理链路历史日志',
        badge: '日志',
        tone: 'green' as const,
        route: '/knowledge/reasoning'
      },
      {
        index: '09',
        label: '多 LLM 反馈对比',
        badge: '评估',
        tone: 'green' as const,
        route: '/knowledge/compare'
      },
      {
        index: '10',
        label: '知识库配置与审计',
        badge: '策略',
        tone: 'blue' as const,
        route: '/knowledge/config'
      }
    ]
  }
]

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

function buildChartOption(): EChartsOption {
  const colors = chartColors()
  const families = Object.keys(FAMILY_LABELS)
  const familyIndex = new Map(families.map((family, index) => [family, index]))
  const majorLabelTypes = new Set(['business_pack', 'domain_module'])
  const data = visibleNodes.value.map((node) => ({
    id: node.id,
    name: node.label,
    value: node.typeLabel,
    category: familyIndex.get(node.family) ?? familyIndex.get('semantic') ?? 0,
    symbolSize: SYMBOL_SIZE_BY_TYPE[node.type] || 18,
    draggable: true,
    label: {
      show: majorLabelTypes.has(node.type),
      color: colors.text,
      fontSize: node.type === 'business_pack' ? 13 : 11,
      fontWeight: 500
    },
    itemStyle: {
      color: colors[node.family as keyof typeof colors] || colors.semantic,
      borderColor: themeColor('--el-bg-color', '#ffffff'),
      borderWidth: selectedNodeId.value === node.id ? 4 : 1.5,
      opacity: selectedNodeId.value && selectedNodeId.value !== node.id ? 0.78 : 0.96
    },
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
        return `<strong>${escapeHtml(datum.name)}</strong><br/><span>${escapeHtml(datum.nodeTypeLabel)}</span>${datum.description ? `<br/><span>${escapeHtml(datum.description)}</span>` : ''}`
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
          label: { show: true, color: colors.text, fontWeight: 500 },
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
          label: { show: true, color: colors.text }
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
  loadGraph()
})

onBeforeUnmount(() => {
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
    menu-title="知识资产"
    menu-root="AI 知识库"
    :menu-sections="menuSections"
    peer-nav-title="同级功能"
    :peer-nav-items="[]"
    boundary-title="知识网络边界"
    boundary-badge="可追溯"
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
          <div class="graph-pane">
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

.graph-pane {
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
