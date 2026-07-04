<script setup lang="ts">
import { computed } from 'vue'
import type {
  AdminConfigOverviewPayload,
  KnowledgeAuditLog,
  KnowledgeConfig,
  KnowledgeFile,
  KnowledgeOverviewPayload,
  KnowledgeRuleVersion,
  KnowledgeSource,
  KnowledgeTask,
  LlmCompareRunSummary
} from '@/api/aicheck'
import type { AiReviewRun, Project, RoleCode } from '@/types/aicheck'

type StaticMode = 'admin' | 'knowledge'
type MetricTone = 'blue' | 'green' | 'orange' | 'red' | 'gray'
type StaticMetric = {
  key: string
  label: string
  value: string | number
  tone?: MetricTone
}

const props = defineProps<{
  mode: StaticMode
  projects?: Project[]
  adminOverview?: AdminConfigOverviewPayload
  adminStats?: StaticMetric[]
  knowledgeOverview?: KnowledgeOverviewPayload
  knowledgeSources?: KnowledgeSource[]
  knowledgeFiles?: KnowledgeFile[]
  knowledgeTasks?: KnowledgeTask[]
  knowledgeRules?: KnowledgeRuleVersion[]
  knowledgeReasoningLogs?: AiReviewRun[]
  knowledgeCompareRuns?: LlmCompareRunSummary[]
  knowledgeConfig?: KnowledgeConfig
  knowledgeAuditLogs?: KnowledgeAuditLog[]
}>()

const projects = computed(() => props.projects || [])
const adminOverview = computed<AdminConfigOverviewPayload>(() => {
  return (
    props.adminOverview || {
      metrics: [],
      orgUnits: [],
      users: [],
      permissionMatrix: [],
      nodeTemplates: [],
      ruleVersions: [],
      workflowStateMachines: [],
      todoRules: [],
      messageTemplates: [],
      toolSources: [],
      fieldMappings: []
    }
  )
})

const knowledgeOverview = computed<KnowledgeOverviewPayload>(() => {
  return props.knowledgeOverview || { metrics: [], libraries: [] }
})

const adminMetrics = computed<StaticMetric[]>(() => {
  if (props.adminStats?.length) return props.adminStats.slice(0, 4)
  return [
    { key: 'project-pages', label: '项目管理页面', value: 3, tone: 'blue' },
    { key: 'permission-pages', label: '权限管理页面', value: 3, tone: 'green' },
    { key: 'workflow-pages', label: '流程待办页面', value: 3, tone: 'orange' },
    { key: 'boundary', label: '后台配置边界', value: '只配置', tone: 'blue' }
  ]
})

const templateMetrics = computed<StaticMetric[]>(() => [
  {
    key: 'rules',
    label: '规则模板',
    value: adminOverview.value.ruleVersions.length || 18,
    tone: 'blue'
  },
  {
    key: 'nodes',
    label: '已绑定节点',
    value:
      adminOverview.value.ruleVersions.reduce((sum, rule) => sum + rule.nodeIds.length, 0) || 46,
    tone: 'green'
  },
  {
    key: 'tools',
    label: '外部工具源',
    value: adminOverview.value.toolSources.length || 4,
    tone: 'blue'
  },
  {
    key: 'fields',
    label: '字段映射',
    value: adminOverview.value.fieldMappings.length || 126,
    tone: 'blue'
  },
  {
    key: 'pending',
    label: '待配置',
    value: adminOverview.value.ruleVersions.filter((rule) => rule.status === '待发布').length || 3,
    tone: 'orange'
  }
])

const adminRuleRows = computed(() => {
  const rows = adminOverview.value.ruleVersions.slice(0, 4).map((rule) => ({
    id: rule.id,
    name: rule.name,
    node: rule.nodeIds.length ? `${rule.nodeIds.join('、')} 节点` : '按模板配置',
    object:
      rule.ruleKey.includes('Welder') || rule.name.includes('焊工')
        ? '人员证书'
        : rule.ruleKey.includes('NDT') || rule.name.includes('检测')
          ? '检测报告'
          : rule.ruleKey.includes('Material') || rule.name.includes('材料')
            ? '材料证明'
            : '业务资料',
    steps: rule.description || '真实性、有效期、持证项目、一致性',
    version: rule.version,
    status: rule.status
  }))
  if (rows.length) return rows
  return [
    {
      id: 'rule-welder',
      name: 'Welder-Qualification-B',
      node: '24. 焊工资格证及持证合格项目',
      object: '人员证书',
      steps: '真实性、有效期、持证项目、一致性',
      version: 'v2.1',
      status: '启用'
    },
    {
      id: 'rule-material',
      name: 'Material-Certificate-C',
      node: '16. 产品质量证明文件',
      object: '材料证明',
      steps: '炉批号、规格材质、标准版本、一致性',
      version: 'v1.8',
      status: '启用'
    },
    {
      id: 'rule-ndt',
      name: 'NDT-Report-C',
      node: '40. 无损检测记录、报告',
      object: '检测报告',
      steps: '报告底片、比例、评定级别、返修闭环',
      version: 'v1.4',
      status: '待完善'
    }
  ]
})

const adminToolRows = computed(() => {
  const rows = adminOverview.value.toolSources.slice(0, 4).map((tool) => ({
    id: tool.id,
    name: tool.name,
    type: tool.toolType,
    input: tool.endpoint || '配置项输入',
    fallback: tool.status === '异常' ? '降级检索' : '人工确认'
  }))
  if (rows.length) return rows
  return [
    {
      id: 'welder-query',
      name: '焊工资格查询',
      type: '网页/截图',
      input: '证书编号',
      fallback: '人工确认'
    },
    { id: 'material-std', name: '材料标准库', type: '接口', input: '标准号', fallback: '降级检索' },
    {
      id: 'date-rule',
      name: '日期覆盖规则',
      type: '内置规则',
      input: '起止日期',
      fallback: '阻断提交'
    },
    {
      id: 'ocr-locator',
      name: 'OCR 证据定位',
      type: '服务',
      input: '文件版本',
      fallback: '低置信度确认'
    }
  ]
})

const roleLabel = (role: RoleCode) => {
  const labels: Record<RoleCode, string> = {
    inspection: '监检人员',
    contractor: '施工方经办',
    ndt: '无损检测经办',
    owner: '建设方用户',
    admin: '系统管理员',
    fde: 'FDE'
  }
  return labels[role]
}

const adminPermissionRows = computed(() => {
  const rows = adminOverview.value.permissionMatrix
  const roles: RoleCode[] = ['inspection', 'contractor', 'ndt', 'owner', 'admin', 'fde']
  const getPolicy = (role: RoleCode, key: 'view' | 'upload' | 'review' | 'config') => {
    const row = rows.find((item) => item.role === role)
    if (!row) {
      if (key === 'view') return '允许'
      if (key === 'config') return role === 'admin' ? '允许' : '禁止'
      if (key === 'review') return role === 'inspection' ? '允许' : '禁止'
      return role === 'owner' ? '禁止' : '允许'
    }
    if (key === 'view') return row.actions.includes('project:view') ? '允许' : '禁止'
    if (key === 'upload') {
      if (role === 'inspection' && row.actions.includes('file:upload')) return '节点附件'
      return row.actions.includes('file:upload') ? '允许' : '禁止'
    }
    if (key === 'review') return row.actions.includes('review:save') ? '允许' : '禁止'
    return row.actions.includes('admin:config') ? '允许' : '禁止'
  }
  return [
    {
      action: '查看项目树',
      policies: roles.map((role) => ({ role, value: getPolicy(role, 'view') }))
    },
    {
      action: '上传文件',
      policies: roles.map((role) => ({ role, value: getPolicy(role, 'upload') }))
    },
    {
      action: '审查/退回',
      policies: roles.map((role) => ({ role, value: getPolicy(role, 'review') }))
    },
    {
      action: '配置规则模板',
      policies: roles.map((role) => ({ role, value: getPolicy(role, 'config') }))
    }
  ]
})

const knowledgeMetrics = computed<StaticMetric[]>(() => {
  if (knowledgeOverview.value.metrics.length) return knowledgeOverview.value.metrics.slice(0, 5)
  return [
    {
      key: 'standard',
      label: '标准规范',
      value: props.knowledgeSources?.length || 14,
      tone: 'blue'
    },
    {
      key: 'project-file',
      label: '项目文件',
      value: props.knowledgeFiles?.length || 126,
      tone: 'green'
    },
    { key: 'ocr', label: 'OCR 完成率', value: '91%', tone: 'blue' },
    { key: 'vector', label: '向量化完成率', value: '84%', tone: 'orange' },
    {
      key: 'failed',
      label: '失败任务',
      value: props.knowledgeTasks?.filter((task) => task.status === '失败').length || 7,
      tone: 'red'
    }
  ]
})

const knowledgeSources = computed(() => props.knowledgeSources || [])
const knowledgeFiles = computed(() => props.knowledgeFiles || [])
const knowledgeTasks = computed(() => props.knowledgeTasks || [])
const knowledgeRules = computed(() => props.knowledgeRules || [])
const knowledgeReasoningLogs = computed(() => props.knowledgeReasoningLogs || [])
const knowledgeCompareRuns = computed(() => props.knowledgeCompareRuns || [])
const knowledgeAuditLogs = computed(() => props.knowledgeAuditLogs || [])

const knowledgeFileDetail = computed(() => {
  const file = knowledgeFiles.value[0]
  return {
    name: file ? `${file.fileName}` : '钢管质量证明书.pdf V2',
    hash: file?.documentVersionId || '8d34...af91',
    ocr: file
      ? `${file.ocrStatus}，切片 ${file.chunkCount} 个`
      : '8 页已识别，字段 42 个，低置信度 2 个',
    chunk: file ? `${file.chunkCount} 个业务片段` : '36 个业务片段，平均 420 字',
    model: props.knowledgeConfig?.embeddingModel || 'embedding-v3-large',
    index: knowledgeOverview.value.libraries[1]?.indexVersion || 'proj-v2026.06.26',
    node: file?.nodeName || '16. 产品质量证明文件、18. 材料复验报告',
    references: `${knowledgeReasoningLogs.value.length || 4} 次 AI 业务审查链路引用`
  }
})

const getPillClass = (value?: string | number) => {
  const text = String(value || '')
  if (!text) return 'blue'
  if (
    text.includes('通过') ||
    text.includes('满足') ||
    text.includes('健康') ||
    text.includes('启用') ||
    text.includes('成功') ||
    text.includes('完成') ||
    text.includes('发布') ||
    text.includes('允许') ||
    text.includes('已识别') ||
    text.includes('已向量化') ||
    text.includes('已切片')
  ) {
    return 'green'
  }
  if (
    text.includes('失败') ||
    text.includes('禁止') ||
    text.includes('停用') ||
    text.includes('异常') ||
    text.includes('需补正')
  ) {
    return 'red'
  }
  if (
    text.includes('待') ||
    text.includes('索引') ||
    text.includes('运行') ||
    text.includes('排队') ||
    text.includes('识别中') ||
    text.includes('向量化中') ||
    text.includes('草稿') ||
    text.includes('节点附件')
  ) {
    return 'orange'
  }
  return 'blue'
}
</script>

<template>
  <div class="admin-knowledge-static-deep">
    <template v-if="mode === 'admin'">
      <section class="static-card">
        <div class="static-card-head">
          <h2>一、合同功能 1-3 模块入口</h2>
          <div class="sub">每个入口均对应二级静态页面，覆盖合同要求的核心字段、筛选和状态。</div>
        </div>
        <div class="static-card-body">
          <div class="metrics four">
            <div v-for="metric in adminMetrics" :key="metric.key" class="metric">
              <div class="metric-label">{{ metric.label }}</div>
              <div :class="['metric-value', metric.tone || 'blue']">{{ metric.value }}</div>
            </div>
          </div>
          <table aria-hidden="true" class="table module-table">
            <thead>
              <tr><th>合同项</th><th>新增前端页面</th><th>关键覆盖内容</th><th>入口</th></tr>
            </thead>
            <tbody>
              <tr class="selected">
                <td>1. 项目管理与基础配置</td>
                <td>项目列表、项目详情、项目立项向导</td>
                <td
                  >立项、项目详情、状态筛选、参建单位维护；当前
                  {{ projects.length || 0 }} 个项目</td
                >
                <td><span class="action-text">项目列表</span></td>
              </tr>
              <tr>
                <td>2. 用户中心与组织权限</td>
                <td>组织用户、角色权限配置、项目成员授权</td>
                <td
                  >{{ adminOverview.orgUnits.length }} 个组织、{{
                    adminOverview.users.length
                  }}
                  个账号、动作级授权</td
                >
                <td><span class="action-text">组织用户</span></td>
              </tr>
              <tr>
                <td>3. 流程管理与待办任务</td>
                <td>流程状态机、待办规则配置、流程实例详情</td>
                <td
                  >{{ adminOverview.workflowStateMachines.length }} 个状态机、{{
                    adminOverview.todoRules.length
                  }}
                  条待办规则</td
                >
                <td><span class="action-text">流程状态机</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="static-card">
        <div class="static-card-head"><h2>二、模板概览</h2></div>
        <div class="static-card-body">
          <div class="metrics">
            <div v-for="metric in templateMetrics" :key="metric.key" class="metric">
              <div class="metric-label">{{ metric.label }}</div>
              <div :class="['metric-value', metric.tone || 'blue']">{{ metric.value }}</div>
            </div>
          </div>
        </div>
      </section>

      <section class="static-card">
        <div class="static-card-head">
          <h2>三、规则模板列表</h2>
          <div class="sub">规则模板定义审查链路结构，不保存具体项目结论</div>
        </div>
        <div class="static-card-body">
          <table aria-hidden="true" class="table">
            <thead>
              <tr
                ><th>模板名称</th><th>适用节点</th><th>审查对象</th><th>核验步骤</th><th>版本</th
                ><th>状态</th><th>操作</th></tr
              >
            </thead>
            <tbody>
              <tr
                v-for="(rule, index) in adminRuleRows"
                :key="rule.id"
                :class="{ selected: index === 0 }"
              >
                <td>{{ rule.name }}</td>
                <td>{{ rule.node }}</td>
                <td>{{ rule.object }}</td>
                <td>{{ rule.steps }}</td>
                <td>{{ rule.version }}</td>
                <td
                  ><span :class="['pill', getPillClass(rule.status)]">{{ rule.status }}</span></td
                >
                <td
                  ><span class="action-text">{{ index === 2 ? '配置字段' : '编辑模板' }}</span></td
                >
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <div class="split">
        <section class="static-card">
          <div class="static-card-head"><h2>四、当前模板核验步骤</h2></div>
          <div class="static-card-body">
            <div class="review-chain">
              <div class="review-step">
                <div class="step-no">1</div>
                <div
                  ><div class="step-title">证书真实性核验</div
                  ><div class="step-desc"
                    >输入证书编号、姓名、身份证尾号；输出证书是否存在和身份是否一致。</div
                  ></div
                >
                <span class="pill blue">工具</span>
              </div>
              <div class="review-step">
                <div class="step-no">2</div>
                <div
                  ><div class="step-title">有效期覆盖核验</div
                  ><div class="step-desc"
                    >输入证书有效期和项目周期；由日期规则判断是否覆盖施工周期。</div
                  ></div
                >
                <span class="pill green">规则</span>
              </div>
              <div class="review-step">
                <div class="step-no">3</div>
                <div
                  ><div class="step-title">持证项目适配核验</div
                  ><div class="step-desc"
                    >输入焊接方法、材质、规格范围；匹配项目焊接工艺要求。</div
                  ></div
                >
                <span class="pill green">规则</span>
              </div>
            </div>
          </div>
        </section>
        <section class="static-card">
          <div class="static-card-head"><h2>五、外部核验工具源</h2></div>
          <div class="static-card-body">
            <table aria-hidden="true" class="table compact">
              <thead
                ><tr><th>工具源</th><th>类型</th><th>输入字段</th><th>失败处理</th></tr></thead
              >
              <tbody>
                <tr v-for="tool in adminToolRows" :key="tool.id">
                  <td>{{ tool.name }}</td>
                  <td>{{ tool.type }}</td>
                  <td>{{ tool.input }}</td>
                  <td>{{ tool.fallback }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <section class="static-card">
        <div class="static-card-head">
          <h2>六、动作级权限矩阵</h2>
          <div class="sub">后台配置权限，不替代后端校验</div>
        </div>
        <div class="static-card-body">
          <table aria-hidden="true" class="table">
            <thead>
              <tr>
                <th>动作</th>
                <th v-for="policy in adminPermissionRows[0]?.policies || []" :key="policy.role">
                  {{ roleLabel(policy.role) }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in adminPermissionRows" :key="row.action">
                <td>{{ row.action }}</td>
                <td v-for="policy in row.policies" :key="`${row.action}-${policy.role}`">
                  <span :class="['pill', getPillClass(policy.value)]">{{ policy.value }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>

    <template v-else>
      <section class="static-card">
        <div class="static-card-head">
          <h2>一、知识库总览</h2>
          <div class="sub">标准规范、项目文件、规则版本和推理证据的整体状态</div>
        </div>
        <div class="static-card-body">
          <div class="metrics">
            <div v-for="metric in knowledgeMetrics" :key="metric.key" class="metric">
              <div class="metric-label">{{ metric.label }}</div>
              <div :class="['metric-value', metric.tone || 'blue']">{{ metric.value }}</div>
            </div>
          </div>
          <table aria-hidden="true" class="table module-table">
            <thead
              ><tr
                ><th>知识库</th><th>文件数</th><th>切片数</th><th>向量数</th><th>索引版本</th
                ><th>健康状态</th><th>最近更新</th></tr
              ></thead
            >
            <tbody>
              <tr
                v-for="(library, index) in knowledgeOverview.libraries"
                :key="library.key"
                :class="{ selected: index === 0 }"
              >
                <td>{{ library.name }}</td>
                <td>{{ library.fileCount }}</td>
                <td>{{ library.chunkCount }}</td>
                <td>{{ library.vectorCount }}</td>
                <td>{{ library.indexVersion }}</td>
                <td
                  ><span :class="['pill', getPillClass(library.status)]">{{
                    library.status
                  }}</span></td
                >
                <td>{{ library.updatedAt }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="static-card">
        <div class="static-card-head">
          <h2>二、标准规范库</h2>
          <div class="sub">标准文件、条文拆分、版本、适用范围、OCR 与向量化状态</div>
        </div>
        <div class="static-card-body">
          <table aria-hidden="true" class="table">
            <thead
              ><tr
                ><th>标准/规范</th><th>类别</th><th>版本</th><th>条文切片</th><th>OCR</th
                ><th>向量化</th><th>状态</th></tr
              ></thead
            >
            <tbody>
              <tr
                v-for="(source, index) in knowledgeSources.slice(0, 4)"
                :key="source.id"
                :class="{ selected: index === 0 }"
              >
                <td>{{ source.name }}</td>
                <td>{{ source.sourceType }}</td>
                <td>{{ source.version || '-' }}</td>
                <td>{{ source.chunkCount }}</td>
                <td><span class="pill green">已识别</span></td>
                <td
                  ><span :class="['pill', getPillClass(source.vectorStatus)]">{{
                    source.vectorStatus
                  }}</span></td
                >
                <td
                  ><span :class="['pill', getPillClass(source.status)]">{{
                    source.status
                  }}</span></td
                >
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="static-card">
        <div class="static-card-head">
          <h2>三、项目文件知识库</h2>
          <div class="sub">从项目文件知识库、节点文件包、无损检测资料和监检资料同步入库</div>
        </div>
        <div class="static-card-body">
          <table aria-hidden="true" class="table">
            <thead
              ><tr
                ><th>项目</th><th>节点</th><th>文件</th><th>OCR</th><th>切片</th><th>向量</th
                ><th>索引</th></tr
              ></thead
            >
            <tbody>
              <tr
                v-for="(file, index) in knowledgeFiles.slice(0, 4)"
                :key="file.id"
                :class="{ selected: index === 0 }"
              >
                <td>{{ file.projectName || '未绑定项目' }}</td>
                <td>{{ file.nodeName || '-' }}</td>
                <td>{{ file.fileName }}</td>
                <td
                  ><span :class="['pill', getPillClass(file.ocrStatus)]">{{
                    file.ocrStatus
                  }}</span></td
                >
                <td
                  ><span :class="['pill', getPillClass(file.sliceStatus)]">{{
                    file.sliceStatus
                  }}</span></td
                >
                <td
                  ><span :class="['pill', getPillClass(file.vectorStatus)]">{{
                    file.vectorStatus
                  }}</span></td
                >
                <td>{{ knowledgeOverview.libraries[1]?.indexVersion || '-' }}</td>
              </tr>
            </tbody>
          </table>
          <div class="subsection-title">选中文件知识详情</div>
          <table aria-hidden="true" class="table compact">
            <tbody>
              <tr
                ><th>文件</th><td>{{ knowledgeFileDetail.name }}</td
                ><th>Hash</th><td>{{ knowledgeFileDetail.hash }}</td></tr
              >
              <tr
                ><th>OCR 文本</th><td>{{ knowledgeFileDetail.ocr }}</td
                ><th>切片</th><td>{{ knowledgeFileDetail.chunk }}</td></tr
              >
              <tr
                ><th>向量模型</th><td>{{ knowledgeFileDetail.model }}</td
                ><th>索引版本</th><td>{{ knowledgeFileDetail.index }}</td></tr
              >
              <tr
                ><th>关联节点</th><td>{{ knowledgeFileDetail.node }}</td
                ><th>推理引用</th><td>{{ knowledgeFileDetail.references }}</td></tr
              >
            </tbody>
          </table>
        </div>
      </section>

      <div class="split">
        <section class="static-card">
          <div class="static-card-head">
            <h2>四、OCR/向量任务中心</h2>
            <span class="pill orange"
              >{{
                knowledgeTasks.filter((task) => task.status === '失败').length || 7
              }}
              个失败</span
            >
          </div>
          <div class="static-card-body">
            <table aria-hidden="true" class="table compact">
              <thead
                ><tr><th>任务</th><th>对象</th><th>状态</th><th>进度</th></tr></thead
              >
              <tbody>
                <tr v-for="task in knowledgeTasks.slice(0, 3)" :key="task.id">
                  <td>{{ task.id }}</td>
                  <td>{{ task.targetName }}</td>
                  <td
                    ><span :class="['pill', getPillClass(task.status)]">{{ task.status }}</span></td
                  >
                  <td>{{ task.progress }}%</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
        <section class="static-card">
          <div class="static-card-head">
            <h2>五、知识检索测试</h2>
            <span class="pill blue">召回验证</span>
          </div>
          <div class="static-card-body">
            <table aria-hidden="true" class="table compact">
              <tbody>
                <tr><th>测试问题</th><td>焊工资格证有效期是否覆盖项目施工周期？</td></tr>
                <tr><th>召回范围</th><td>标准规范库 + 当前项目文件知识库 + 业务规则知识库</td></tr>
                <tr><th>命中证据</th><td>TSG Z6002 条文、资格证页码、施工计划页码</td></tr>
                <tr><th>相似度</th><td>0.91 / 0.88 / 0.84</td></tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <section class="static-card">
        <div class="static-card-head">
          <h2>六、监检业务判断规则管理</h2>
          <div class="sub">规则模板、Prompt、字段映射和工具源版本统一发布和回滚</div>
        </div>
        <div class="static-card-body">
          <table aria-hidden="true" class="table">
            <thead
              ><tr
                ><th>规则模板</th><th>适用节点</th><th>规则版本</th><th>Prompt</th><th>字段映射</th
                ><th>状态</th><th>操作</th></tr
              ></thead
            >
            <tbody>
              <tr
                v-for="(rule, index) in knowledgeRules.slice(0, 4)"
                :key="rule.id"
                :class="{ selected: index === 0 }"
              >
                <td>{{ rule.name }}</td>
                <td>{{ rule.nodeIds.join('、') || '-' }}</td>
                <td>{{ rule.version }}</td>
                <td>{{ rule.promptVersion }}</td>
                <td>{{ rule.outputSchemaVersion }}</td>
                <td
                  ><span :class="['pill', getPillClass(rule.status)]">{{ rule.status }}</span></td
                >
                <td
                  ><span class="action-text">{{
                    rule.status === '待发布' ? '模型评估' : '查看引用'
                  }}</span></td
                >
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="static-card">
        <div class="static-card-head">
          <h2>七、推理链路历史日志</h2>
          <div class="sub">回溯每次 AI 审查链路的输入、规则、召回、模型输出和人工处理结果</div>
        </div>
        <div class="static-card-body">
          <table aria-hidden="true" class="table">
            <thead
              ><tr
                ><th>时间</th><th>节点</th><th>审查对象</th><th>规则版本</th><th>模型</th
                ><th>召回证据</th><th>AI 建议</th><th>人工处理</th></tr
              ></thead
            >
            <tbody>
              <tr
                v-for="(run, index) in knowledgeReasoningLogs.slice(0, 4)"
                :key="run.id"
                :class="{ selected: index === 0 }"
              >
                <td>{{ run.finishedAt || '-' }}</td>
                <td>{{ run.nodeId }}</td>
                <td>{{ run.subject }}</td>
                <td>{{ run.ruleVersion }}</td>
                <td>{{ run.model }}</td>
                <td>{{ run.evidenceLinks.length }} 条</td>
                <td
                  ><span :class="['pill', getPillClass(run.suggestion.result)]">{{
                    run.suggestion.result
                  }}</span></td
                >
                <td>{{ run.status }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="static-card">
        <div class="static-card-head">
          <h2>八、多 LLM 反馈对比</h2>
          <div class="sub">同一审查对象在不同模型下的建议结果对比，仅用于规则优化和质量评估</div>
        </div>
        <div class="static-card-body">
          <div class="kb-compare">
            <div v-for="run in knowledgeCompareRuns.slice(0, 3)" :key="run.runId" class="kb-model">
              <h4>{{ run.modelCodes.join(' / ') }}</h4>
              <p>{{ run.question }}</p>
              <span class="pill blue">{{ run.createdAt }}</span>
            </div>
            <div v-if="!knowledgeCompareRuns.length" class="kb-model">
              <h4>LLM-A / LLM-B / LLM-C</h4>
              <p>结论对比用于发现证据引用差异、截图时效风险和规则优化项。</p>
              <span class="pill orange">等待对比</span>
            </div>
          </div>
        </div>
      </section>

      <div class="split">
        <section class="static-card">
          <div class="static-card-head"><h2>九、知识库配置</h2></div>
          <div class="static-card-body">
            <table aria-hidden="true" class="table compact">
              <tbody>
                <tr
                  ><th>Embedding</th
                  ><td>{{ knowledgeConfig?.embeddingModel || 'embedding-v3-large' }}</td></tr
                >
                <tr
                  ><th>切片策略</th
                  ><td
                    >{{ knowledgeConfig?.chunkSize || 900 }} 字，{{
                      knowledgeConfig?.chunkOverlap || 120
                    }}
                    overlap</td
                  ></tr
                >
                <tr
                  ><th>召回策略</th
                  ><td
                    >Top {{ knowledgeConfig?.topKDefault || 5
                    }}{{ knowledgeConfig?.rerankEnabled ? ' + rerank' : '' }}</td
                  ></tr
                >
                <tr
                  ><th>证据模式</th
                  ><td>{{
                    knowledgeConfig?.evidenceStrictMode ? '严格引用 EvidenceLink' : '普通引用'
                  }}</td></tr
                >
              </tbody>
            </table>
          </div>
        </section>
        <section class="static-card">
          <div class="static-card-head"><h2>十、操作审计日志</h2></div>
          <div class="static-card-body">
            <table aria-hidden="true" class="table compact">
              <tbody>
                <tr v-for="log in knowledgeAuditLogs.slice(0, 3)" :key="log.id">
                  <th>{{ log.createdAt }}</th>
                  <td>{{ log.actorName }} {{ log.action }} {{ log.objectType }}</td>
                </tr>
                <tr v-if="!knowledgeAuditLogs.length"
                  ><th>09:31</th><td>系统重建项目文件知识库索引 proj-v2026.06.26</td></tr
                >
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </template>
  </div>
</template>

<style scoped>
.admin-knowledge-static-deep {
  width: 100%;
}

.static-card {
  margin-bottom: 12px;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 6px;
  box-shadow: 0 1px 2px rgb(20 34 56 / 4%);
  transition:
    border-color 0.18s ease,
    box-shadow 0.18s ease;
}

.static-card:hover,
.static-card:focus-within {
  border-color: #c4d5ee;
  box-shadow: 0 2px 8px rgb(20 34 56 / 8%);
}

.static-card-head {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  min-height: 50px;
  padding: 13px 16px;
  border-bottom: 1px solid var(--line-soft);
}

.static-card-body {
  padding: 14px 16px;
}

h2 {
  margin: 0;
  font-size: 21px;
  line-height: 1.2;
}

h4 {
  margin: 0 0 8px;
  font-size: 16px;
}

p {
  margin: 0 0 10px;
  font-size: 14px;
  font-weight: 700;
  line-height: 1.6;
  color: #344054;
}

.sub {
  font-size: 14px;
  font-weight: 700;
  color: var(--muted);
}

.split {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 12px;
}

.metrics {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
}

.metrics.four {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.metric {
  min-height: 72px;
  padding: 14px;
  background: #fbfdff;
  border: 1px solid var(--line);
  border-radius: 6px;
}

.metric-label {
  font-size: 13px;
  font-weight: 800;
  color: var(--muted);
}

.metric-value {
  margin-top: 8px;
  font-size: 24px;
  font-weight: 900;
  line-height: 1;
  color: var(--blue);
}

.metric-value.green {
  color: var(--green);
}

.metric-value.orange {
  color: var(--orange);
}

.metric-value.red {
  color: var(--red);
}

.metric-value.gray {
  color: #64748b;
}

.module-table {
  margin-top: 12px;
}

.subsection-title {
  margin: 14px 0 10px;
  font-size: 13px;
  font-weight: 800;
  color: #344054;
}

.table {
  width: 100%;
  font-size: 14px;
  border-collapse: collapse;
  table-layout: fixed;
}

.table th,
.table td {
  padding: 10px 11px;
  overflow: hidden;
  text-align: left;
  text-overflow: ellipsis;
  vertical-align: middle;
  border: 1px solid var(--line-soft);
  transition: background-color 0.18s ease;
}

.table th {
  font-weight: 900;
  color: #485a73;
  background: var(--head);
}

.table.compact th,
.table.compact td {
  padding: 8px 9px;
  font-size: 13px;
}

.table tbody tr:hover th,
.table tbody tr:hover td {
  background: #f4f8ff;
}

.table tr.selected td,
.table tr.selected th {
  background: var(--blue-soft);
}

.pill {
  display: inline-flex;
  min-height: 24px;
  padding: 3px 8px;
  font-size: 13px;
  font-weight: 800;
  line-height: 1;
  color: var(--blue-2);
  white-space: nowrap;
  background: var(--blue-soft);
  border: 1px solid #bcd4ff;
  border-radius: 5px;
  align-items: center;
  justify-content: center;
}

.pill.blue {
  color: var(--blue-2);
  background: var(--blue-soft);
  border-color: #bcd4ff;
}

.pill.green {
  color: var(--green);
  background: var(--green-soft);
  border-color: #bdebd1;
}

.pill.orange {
  color: var(--orange);
  background: var(--orange-soft);
  border-color: #ffd399;
}

.pill.red {
  color: var(--red);
  background: var(--red-soft);
  border-color: #ffc5bd;
}

.action-text {
  display: inline-flex;
  min-height: 24px;
  padding: 0 6px;
  font-weight: 900;
  color: var(--blue-2);
  border-radius: 5px;
  transition:
    color 0.18s ease,
    background-color 0.18s ease;
  align-items: center;
}

.action-text:hover {
  color: var(--blue);
  background: var(--blue-soft);
}

@media (prefers-reduced-motion: reduce) {
  .static-card,
  .table th,
  .table td,
  .action-text {
    transition: none;
  }
}

.review-chain {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.review-step {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) auto;
  gap: 12px;
  align-items: start;
  padding: 12px;
  background: #fbfdff;
  border: 1px solid var(--line-soft);
  border-radius: 6px;
}

.step-no {
  display: grid;
  width: 28px;
  height: 28px;
  font-weight: 900;
  color: #fff;
  background: var(--blue);
  border-radius: 50%;
  place-items: center;
}

.step-title {
  font-weight: 900;
}

.step-desc {
  margin-top: 6px;
  font-size: 14px;
  line-height: 1.6;
  color: #344054;
}

.kb-compare {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.kb-model {
  min-height: 130px;
  padding: 14px;
  background: #fbfdff;
  border: 1px solid var(--line-soft);
  border-radius: 6px;
}
</style>
