<script setup lang="ts">
import { computed } from 'vue'
import type {
  ArchiveItem,
  NdtFeedback,
  NdtFilm,
  NdtRecord,
  NdtReport,
  NodePackagePayload,
  Project,
  ProjectTreeNode,
  ReportVersion,
  RoleCode,
  WorkbenchSummaryPayload
} from '@/types/aicheck'

type ReviewChainStep = {
  title: string
  desc: string
  tags: string[]
  result: string
}

const props = defineProps<{
  role: RoleCode
  project?: Project
  node?: ProjectTreeNode
  packageData?: NodePackagePayload
  metrics: WorkbenchSummaryPayload['metrics']
  reviewSteps: ReviewChainStep[]
  aiConfidence: string
  reports: ReportVersion[]
  archiveItems: ArchiveItem[]
  ndtFilms: NdtFilm[]
  ndtRecords: NdtRecord[]
  ndtReports: NdtReport[]
  ndtFeedback: NdtFeedback[]
}>()

const bindings = computed(() => props.packageData?.bindings || [])
const projectFiles = computed(() => props.packageData?.projectFiles || [])
const requirements = computed(() => props.packageData?.requirements || [])
const extractedFields = computed(() => props.packageData?.extractedFields || [])
const latestAiRun = computed(() => props.packageData?.aiRuns[0])
const latestReport = computed(() => props.reports[0])
const latestArchive = computed(() => props.archiveItems[0])
const correctionFeedback = computed(() =>
  props.ndtFeedback.find((item) => item.status === '待反馈')
)

const currentNodeLabel = computed(() => {
  if (!props.node) return '未选择节点'
  return `${props.node.nodeId}. ${props.node.name}`
})

const boundProgress = computed(() => {
  const progress = props.node?.requiredProgress
  if (!progress) return `${bindings.value.length}/${requirements.value.length || '-'}`
  return `${progress.done}/${progress.total}`
})

const visibleMetrics = computed(() => {
  if (props.metrics.length) return props.metrics.slice(0, 5)
  return [
    { key: 'files', label: '过程文件', value: bindings.value.length || '-' },
    { key: 'steps', label: '核验步骤', value: props.reviewSteps.length || '-' },
    { key: 'confidence', label: '置信度', value: props.aiConfidence },
    { key: 'reports', label: '报告版本', value: props.reports.length || '-' },
    { key: 'archive', label: '归档资料', value: props.archiveItems.length || '-' }
  ]
})

const processRows = computed(() =>
  bindings.value.slice(0, 5).map((binding, index) => ({
    id: binding.id,
    fileName: binding.fileName,
    version: binding.versionNo,
    usage: binding.usage,
    field:
      extractedFields.value[index]?.fieldName ||
      binding.requirementName ||
      binding.usage ||
      '关键字段',
    evidence: extractedFields.value[index]?.pageNo
      ? `第 ${extractedFields.value[index]?.pageNo} 页`
      : '证据位置待定位',
    status: binding.bindingStatus
  }))
)

const ownerNodeRows = computed(() => {
  const node = props.node
  return [
    {
      group: node?.groupName || '材料',
      node: currentNodeLabel.value,
      fileStatus: node?.status || '待审查',
      reviewStatus: node?.status === '需补正' ? '退回补正' : node?.status || '待审查',
      files: node?.fileCount || bindings.value.length || 0,
      warnings: node?.status === '需补正' ? 1 : 0,
      updatedAt: props.project?.updatedAt || '-'
    },
    {
      group: '焊接（粘接）',
      node: '25. 焊接（粘接）工艺文件',
      fileStatus: '已提交',
      reviewStatus: '待审查',
      files: 6,
      warnings: 0,
      updatedAt: '2026-06-24'
    },
    {
      group: '无损检测',
      node: '40. 无损检测记录、报告',
      fileStatus: '已提交',
      reviewStatus: '待审查',
      files: props.ndtReports.length || 8,
      warnings: 0,
      updatedAt: '2026-06-25'
    },
    {
      group: '无损检测',
      node: '42. 射线检测现场抽查',
      fileStatus: '需补正',
      reviewStatus: '补正中',
      files: 3,
      warnings: 1,
      updatedAt: '2026-06-25'
    }
  ]
})

const contractorFileRows = computed(() => {
  const rows = projectFiles.value.slice(0, 6).map((file, index) => {
    const binding = bindings.value[index]
    return {
      id: file.id,
      fileName: file.fileName,
      usage: binding?.usage || '原始提交',
      version: binding?.versionNo || 'V1',
      fileStatus: file.fileStatus,
      bindStatus: binding?.bindingStatus || '未挂载',
      ocr: file.currentOcrStatus,
      uploader: file.uploaderName,
      relation: binding?.bindingStatus === '需补正' ? '1条' : binding ? '链路反馈' : '-'
    }
  })
  if (rows.length) return rows
  return bindings.value.slice(0, 6).map((binding) => ({
    id: binding.id,
    fileName: binding.fileName,
    usage: binding.usage,
    version: binding.versionNo,
    fileStatus: '已上传',
    bindStatus: binding.bindingStatus,
    ocr: '已识别',
    uploader: binding.sourceOrgName,
    relation: binding.bindingStatus === '需补正' ? '1条' : '链路反馈'
  }))
})

const unboundFiles = computed(() =>
  contractorFileRows.value
    .filter((file) => ['未挂载', '草稿挂载'].includes(String(file.bindStatus)))
    .slice(0, 3)
)

const ndtRecordRows = computed(() =>
  props.ndtRecords.slice(0, 5).map((record) => ({
    id: record.id,
    filmNo: props.ndtFilms.find((film) => film.id === record.filmId)?.filmNo || record.recordNo,
    weldNo: record.weldNo,
    pipelineNo: record.pipelineNo || '-',
    method: record.method,
    testDate: record.testDate,
    level: record.result,
    defect: record.conclusion || '-',
    status: record.sampleStatus
  }))
)

const getPillClass = (value?: string) => {
  if (!value) return 'blue'
  if (
    value.includes('通过') ||
    value.includes('满足') ||
    value.includes('归档') ||
    value.includes('只读') ||
    value.includes('合格')
  ) {
    return 'green'
  }
  if (
    value.includes('补正') ||
    value.includes('失败') ||
    value.includes('禁止') ||
    value.includes('风险') ||
    value.includes('缺')
  ) {
    return 'red'
  }
  if (
    value.includes('待') ||
    value.includes('AI') ||
    value.includes('草稿') ||
    value.includes('复核') ||
    value.includes('确认') ||
    value.includes('生成')
  ) {
    return 'orange'
  }
  return 'blue'
}
</script>

<template>
  <div class="role-static-sections">
    <template v-if="role === 'contractor'">
      <section class="card">
        <div class="card-head">
          <h2>一、项目文件库</h2>
          <div class="sub">本单位项目级文件、版本、OCR、提交状态和挂载状态</div>
        </div>
        <div class="card-body">
          <table class="table">
            <thead>
              <tr>
                <th>文件名</th>
                <th>文件用途</th>
                <th>版本</th>
                <th>文件状态</th>
                <th>挂载状态</th>
                <th>OCR</th>
                <th>上传人</th>
                <th>关联意见</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(file, index) in contractorFileRows"
                :key="file.id"
                :class="{ selected: index === 0 }"
              >
                <td>{{ file.fileName }}</td>
                <td>{{ file.usage }}</td>
                <td>{{ file.version }}</td>
                <td
                  ><span :class="['pill', getPillClass(file.fileStatus)]">{{
                    file.fileStatus
                  }}</span></td
                >
                <td
                  ><span :class="['pill', getPillClass(file.bindStatus)]">{{
                    file.bindStatus
                  }}</span></td
                >
                <td>{{ file.ocr }}</td>
                <td>{{ file.uploader }}</td>
                <td>{{ file.relation }}</td>
                <td><span class="action-text">查看/替换</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <div class="split">
        <section class="card">
          <div class="card-head"><h2>二、项目文件上传区</h2></div>
          <div class="card-body">
            <div class="upload-box">
              ⇧ 点击或拖拽多个文件到此处上传
              <br />
              <span class="sub"
                >支持 pdf、doc、docx、xls、xlsx、jpg、png、zip；可批量设置来源、用途和备注</span
              >
            </div>
          </div>
        </section>
        <section class="card">
          <div class="card-head"><h2>三、批量挂载设置</h2></div>
          <div class="card-body">
            <table class="table compact">
              <tbody>
                <tr>
                  <th>批量节点</th>
                  <td>
                    <span class="pill blue">{{ currentNodeLabel }}</span>
                    <span class="pill blue">18. 材料复验报告、无损检测报告</span>
                  </td>
                </tr>
                <tr><th>默认用途</th><td>原始提交 / 补正附件 / 整改说明 / 证明材料</td></tr>
                <tr
                  ><th>提交规则</th
                  ><td>至少 1 个文件已选择挂载节点；未挂载文件只能保存草稿。</td></tr
                >
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <section class="card">
        <div class="card-head">
          <h2>四、监检业务链路反馈</h2>
          <div class="sub">施工方只查看反馈和补正要求，不编辑 AI 审查链路</div>
        </div>
        <div class="card-body">
          <table class="table">
            <thead>
              <tr
                ><th>反馈节点</th><th>审查对象</th><th>链路结论</th><th>关键依据</th
                ><th>施工方动作</th></tr
              >
            </thead>
            <tbody>
              <tr
                v-for="(step, index) in reviewSteps.slice(0, 3)"
                :key="step.title"
                :class="{ selected: index === 0 }"
              >
                <td>{{ currentNodeLabel }}</td>
                <td>{{ step.title }}</td>
                <td
                  ><span :class="['pill', getPillClass(step.result)]">{{ step.result }}</span></td
                >
                <td>{{ step.desc }}</td>
                <td>{{
                  step.result.includes('补正')
                    ? '上传补正附件并提交挂载关系'
                    : '无需补正，等待监检确认'
                }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="card">
        <div class="card-head">
          <h2>五、上传挂载设置</h2>
          <div class="sub">同一文件可挂载到多个节点，每个挂载关系分别保存资料项和用途</div>
        </div>
        <div class="card-body">
          <table class="table">
            <thead>
              <tr
                ><th>文件名</th><th>挂载节点</th><th>资料项</th><th>文件用途</th><th>必传</th
                ><th>版本</th><th>文件状态</th><th>挂载状态</th></tr
              >
            </thead>
            <tbody>
              <tr
                v-for="(binding, index) in bindings.slice(0, 5)"
                :key="binding.id"
                :class="{ selected: index === 0 }"
              >
                <td>{{ binding.fileName }}</td>
                <td>{{ binding.nodeId }}. {{ node?.name || '当前节点' }}</td>
                <td>{{ binding.requirementName || '节点资料项' }}</td>
                <td>{{ binding.usage }}</td>
                <td>{{ requirements[index]?.requiredType || '是' }}</td>
                <td>{{ binding.versionNo }}</td>
                <td><span class="pill blue">已上传</span></td>
                <td
                  ><span :class="['pill', getPillClass(binding.bindingStatus)]">{{
                    binding.bindingStatus
                  }}</span></td
                >
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <div class="split">
        <section class="card">
          <div class="card-head">
            <h2>六、未挂载文件池</h2>
            <span class="pill orange">{{ unboundFiles.length }} 个文件</span>
          </div>
          <div class="card-body">
            <table class="table compact">
              <tbody>
                <tr v-for="file in unboundFiles" :key="file.id">
                  <th>{{ file.fileName }}</th>
                  <td>{{ file.usage }}</td>
                  <td><span class="pill orange">未挂载</span></td>
                </tr>
                <tr v-if="!unboundFiles.length">
                  <th>当前无未挂载文件</th>
                  <td>文件均已进入节点挂载关系</td>
                  <td><span class="pill green">已处理</span></td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
        <section class="card">
          <div class="card-head"><h2>七、整改说明</h2></div>
          <div class="card-body">
            <div class="textarea-like">
              已补充材料复验报告，并上传炉批号差异说明。补正资料将随本批文件提交并保持证据链可追溯。
            </div>
          </div>
        </section>
      </div>

      <section class="card">
        <div class="card-head"><h2>八、文件批次摘要</h2></div>
        <div class="card-body">
          <div class="metrics">
            <div class="metric"
              ><div class="metric-label">本批文件</div
              ><div class="metric-value">{{ contractorFileRows.length }}</div></div
            >
            <div class="metric"
              ><div class="metric-label">已选择挂载</div
              ><div class="metric-value green">{{ bindings.length }}</div></div
            >
            <div class="metric"
              ><div class="metric-label">未挂载</div
              ><div class="metric-value orange">{{ unboundFiles.length }}</div></div
            >
            <div class="metric"
              ><div class="metric-label">需补正</div
              ><div class="metric-value red">{{
                bindings.filter((item) => item.bindingStatus === '需补正').length
              }}</div></div
            >
            <div class="metric"
              ><div class="metric-label">业务链路反馈</div
              ><div class="metric-value green">{{ reviewSteps.length }}</div></div
            >
          </div>
        </div>
      </section>
    </template>

    <template v-else-if="role === 'ndt'">
      <section class="card">
        <div class="card-head"><h2>一、检测任务摘要</h2></div>
        <div class="card-body">
          <div class="metrics">
            <div class="metric"
              ><div class="metric-label">底片编号</div
              ><div class="metric-value">{{ ndtFilms.length || '-' }}</div></div
            >
            <div class="metric"
              ><div class="metric-label">本批新增</div
              ><div class="metric-value green">{{
                ndtFilms.filter((item) => item.status === '草稿' || item.status === '待提交').length
              }}</div></div
            >
            <div class="metric"
              ><div class="metric-label">检测报告</div
              ><div class="metric-value">{{ ndtReports.length || '-' }}</div></div
            >
            <div class="metric"
              ><div class="metric-label">挂载节点</div
              ><div class="metric-value">{{
                new Set(ndtRecords.map((item) => item.nodeId)).size || 1
              }}</div></div
            >
            <div class="metric"
              ><div class="metric-label">业务核验</div
              ><div class="metric-value orange"
                >{{ reviewSteps.filter((item) => getPillClass(item.result) === 'green').length }}/{{
                  reviewSteps.length || 1
                }}</div
              ></div
            >
          </div>
        </div>
      </section>

      <section class="card">
        <div class="card-head">
          <h2>二、检测资料业务核验链路</h2>
          <div class="sub">无损检测机构查看链路状态并补充过程文件，不执行监检审查</div>
        </div>
        <div class="card-body">
          <div class="review-chain">
            <div v-for="(step, index) in reviewSteps" :key="step.title" class="review-step">
              <div class="step-no">{{ index + 1 }}</div>
              <div>
                <div class="step-title">{{ step.title }}</div>
                <div class="step-desc">{{ step.desc }}</div>
                <div class="evidence-row">
                  <span v-for="tag in step.tags" :key="tag" class="pill blue">{{ tag }}</span>
                </div>
              </div>
              <span :class="['pill', getPillClass(step.result)]">{{ step.result }}</span>
            </div>
          </div>
        </div>
      </section>

      <section class="card">
        <div class="card-head">
          <h2>三、底片编号与检测记录</h2>
          <div class="sub">维护结构化检测记录，提交后进入监检审查</div>
        </div>
        <div class="card-body">
          <table class="table">
            <thead>
              <tr
                ><th>底片编号</th><th>焊口编号</th><th>管线号</th><th>方法</th><th>检测日期</th
                ><th>评定级别</th><th>缺陷代码</th><th>资料状态</th></tr
              >
            </thead>
            <tbody>
              <tr
                v-for="(record, index) in ndtRecordRows"
                :key="record.id"
                :class="{ selected: index === 0 }"
              >
                <td>{{ record.filmNo }}</td>
                <td>{{ record.weldNo }}</td>
                <td>{{ record.pipelineNo }}</td>
                <td>{{ record.method }}</td>
                <td>{{ record.testDate }}</td>
                <td>{{ record.level }}</td>
                <td>{{ record.defect }}</td>
                <td
                  ><span :class="['pill', getPillClass(record.status)]">{{
                    record.status
                  }}</span></td
                >
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="card">
        <div class="card-head">
          <h2>四、检测报告与节点挂载</h2>
          <div class="sub">无损检测资料只挂载到授权的无损检测相关节点</div>
        </div>
        <div class="card-body">
          <table class="table">
            <thead>
              <tr
                ><th>资料名称</th><th>资料类型</th><th>版本</th><th>挂载节点</th><th>处理状态</th
                ><th>操作</th></tr
              >
            </thead>
            <tbody>
              <tr
                v-for="(report, index) in ndtReports.slice(0, 4)"
                :key="report.id"
                :class="{ selected: index === 0 }"
              >
                <td>{{ report.reportNo }}</td>
                <td>检测报告</td>
                <td>V{{ index + 1 }}</td>
                <td>{{ report.relatedFilmIds.length ? '40、41、65' : currentNodeLabel }}</td>
                <td
                  ><span :class="['pill', getPillClass(report.status)]">{{
                    report.status
                  }}</span></td
                >
                <td><span class="action-text">查看/替换</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <div class="split">
        <section class="card">
          <div class="card-head"><h2>五、检测报告上传</h2></div>
          <div class="card-body">
            <div class="upload-box">
              ⇧ 上传检测报告、底片清单或图像包
              <br />
              <span class="sub">上传后选择无损检测节点：40、41、42、65</span>
            </div>
          </div>
        </section>
        <section class="card">
          <div class="card-head"><h2>六、补正材料</h2></div>
          <div class="card-body">
            <table class="table compact">
              <tbody>
                <tr
                  ><th>补正节点</th
                  ><td>{{ correctionFeedback?.nodeId || 42 }}. 射线检测现场抽查</td></tr
                >
                <tr
                  ><th>监检意见</th
                  ><td>{{
                    correctionFeedback?.description || '现场抽查照片缺少拍摄时间和焊口编号标识。'
                  }}</td></tr
                >
                <tr
                  ><th>当前处理</th
                  ><td
                    ><span
                      :class="['pill', getPillClass(correctionFeedback?.status || '补正中')]"
                      >{{ correctionFeedback?.status || '补正中' }}</span
                    ></td
                  ></tr
                >
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </template>

    <template v-else-if="role === 'owner'">
      <section class="card">
        <div class="card-head">
          <h2>一、项目基础信息</h2>
          <span class="pill green">只读模式</span>
        </div>
        <div class="card-body">
          <div class="metrics owner-metrics">
            <div v-for="metric in visibleMetrics.slice(0, 4)" :key="metric.key" class="metric">
              <div class="metric-label">{{ metric.label }}</div>
              <div :class="['metric-value', metric.tone || getPillClass(String(metric.value))]">{{
                metric.value
              }}</div>
            </div>
          </div>
        </div>
      </section>

      <section class="card">
        <div class="card-head">
          <h2>二、节点状态总览</h2>
          <div class="sub">展示授权可见的节点资料摘要，不提供办理入口</div>
        </div>
        <div class="card-body">
          <table class="table">
            <thead>
              <tr
                ><th>业务大类</th><th>检测节点</th><th>资料状态</th><th>审查状态</th
                ><th>挂载资料数</th><th>异常数量</th><th>最近更新时间</th></tr
              >
            </thead>
            <tbody>
              <tr
                v-for="(row, index) in ownerNodeRows"
                :key="row.node"
                :class="{ selected: index === 0 }"
              >
                <td>{{ row.group }}</td>
                <td>{{ row.node }}</td>
                <td
                  ><span :class="['pill', getPillClass(row.fileStatus)]">{{
                    row.fileStatus
                  }}</span></td
                >
                <td>{{ row.reviewStatus }}</td>
                <td>{{ row.files }}</td>
                <td>{{ row.warnings }}</td>
                <td>{{ row.updatedAt }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="card">
        <div class="card-head">
          <h2>三、业务审查链路只读摘要</h2>
          <div class="sub">建设方仅查看状态和摘要，不查看办理按钮</div>
        </div>
        <div class="card-body">
          <table class="table">
            <thead>
              <tr
                ><th>检测节点</th><th>审查对象</th><th>业务链路摘要</th><th>建议/状态</th
                ><th>人工确认</th></tr
              >
            </thead>
            <tbody>
              <tr
                v-for="(step, index) in reviewSteps"
                :key="step.title"
                :class="{ selected: index === 0 }"
              >
                <td>{{ currentNodeLabel }}</td>
                <td>{{ step.title }}</td>
                <td>{{ step.desc }}</td>
                <td
                  ><span :class="['pill', getPillClass(step.result)]">{{ step.result }}</span></td
                >
                <td>{{ step.result.includes('需') ? '已退回责任单位' : '待监检确认' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <div class="split">
        <section class="card">
          <div class="card-head"><h2>四、关键时间线</h2></div>
          <div class="card-body">
            <div class="timeline">
              <div class="time-row"
                ><span class="time-dot"></span
                ><div
                  ><strong>06-20 首批资料上传</strong><br />施工方完成材料与焊接资料初次提交。</div
                ></div
              >
              <div class="time-row"
                ><span class="time-dot"></span
                ><div
                  ><strong>06-23 检测资料提交</strong><br />无损检测机构提交检测记录与报告。</div
                ></div
              >
              <div class="time-row"
                ><span class="time-dot red"></span
                ><div
                  ><strong>06-25 监检退回材料补正</strong
                  ><br />材料节点存在炉批号差异说明缺失。</div
                ></div
              >
              <div class="time-row"
                ><span class="time-dot orange"></span
                ><div
                  ><strong>06-30 预计报告确认</strong><br />当前报告草稿处于监检复核中。</div
                ></div
              >
            </div>
          </div>
        </section>
        <section class="card">
          <div class="card-head"><h2>五、报告与归档状态</h2></div>
          <div class="card-body">
            <table class="table compact">
              <tbody>
                <tr
                  ><th>监检报告</th
                  ><td>{{ latestReport?.title || '工业管道施工监督检验报告 V0.8' }}</td
                  ><td
                    ><span :class="['pill', getPillClass(latestReport?.status || '复核中')]">{{
                      latestReport?.status || '复核中'
                    }}</span></td
                  ></tr
                >
                <tr
                  ><th>过程资料包</th><td>{{ latestArchive?.name || '待报告确认后生成归档包' }}</td
                  ><td
                    ><span :class="['pill', getPillClass(latestArchive?.status || '待生成')]">{{
                      latestArchive?.status || '待生成'
                    }}</span></td
                  ></tr
                >
                <tr
                  ><th>最近异常</th><td>材料节点需补正、现场抽查照片需补正</td
                  ><td><span class="pill red">2项</span></td></tr
                >
                <tr
                  ><th>查看权限</th><td>仅可查看授权项目资料摘要和报告预览</td
                  ><td><span class="pill green">只读</span></td></tr
                >
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </template>

    <template v-else-if="role === 'inspection'">
      <section class="card">
        <div class="card-head">
          <h2>四、审查对象与项目要求</h2>
          <div class="sub">明确当前审查对象、项目要求和使用规则</div>
        </div>
        <div class="card-body">
          <div class="chain-grid">
            <div class="chain-card">
              <h4>审查对象</h4>
              <p
                >{{ currentNodeLabel }}；文件包 {{ bindings.length }} 个文件；必传完成
                {{ boundProgress }}。</p
              >
            </div>
            <div class="chain-card">
              <h4>项目要求</h4>
              <p
                >{{ project?.name || '当前项目' }}；{{ project?.type || '工业管道' }}；{{
                  project?.region || '-'
                }}；资料应覆盖节点要求和项目施工周期。</p
              >
            </div>
            <div class="chain-card">
              <h4>规则版本</h4>
              <p
                >规则模板：{{
                  latestAiRun?.ruleVersion || 'Welder-Qualification-B-v2.1'
                }}；Prompt：{{ latestAiRun?.promptVersion || '24-焊工资格-v1.5' }}。</p
              >
            </div>
          </div>
        </div>
      </section>

      <section class="card">
        <div class="card-head">
          <h2>五、过程文件</h2>
          <div class="sub">本次业务核验使用的文件、版本和证据来源</div>
        </div>
        <div class="card-body">
          <table class="table">
            <thead>
              <tr
                ><th>过程文件</th><th>版本</th><th>用途</th><th>关键字段</th><th>证据位置</th
                ><th>状态</th></tr
              >
            </thead>
            <tbody>
              <tr
                v-for="(row, index) in processRows"
                :key="row.id"
                :class="{ selected: index === 0 }"
              >
                <td>{{ row.fileName }}</td>
                <td>{{ row.version }}</td>
                <td>{{ row.usage }}</td>
                <td>{{ row.field }}</td>
                <td>{{ row.evidence }}</td>
                <td
                  ><span :class="['pill', getPillClass(row.status)]">{{ row.status }}</span></td
                >
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="card">
        <div class="card-head">
          <h2>六、证据链与标准依据</h2>
          <div class="sub">业务结论必须能追溯到文件、字段、工具结果和标准条款</div>
        </div>
        <div class="card-body">
          <table class="table">
            <thead>
              <tr
                ><th>核验项</th><th>引用证据</th><th>引用标准/规则</th><th>步骤结论</th
                ><th>操作</th></tr
              >
            </thead>
            <tbody>
              <tr
                v-for="(step, index) in reviewSteps"
                :key="step.title"
                :class="{ selected: index === 0 }"
              >
                <td>{{ step.title }}</td>
                <td>{{ step.tags.join('；') || '证据链待加载' }}</td>
                <td>{{ latestAiRun?.ruleVersion || `业务规则 R-${index + 1}` }}</td>
                <td
                  ><span :class="['pill', getPillClass(step.result)]">{{ step.result }}</span></td
                >
                <td><span class="action-text">定位证据</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="card">
        <div class="card-head">
          <h2>七、业务规则说明</h2>
          <div class="sub">用于说明当前节点 AI 核验和人工审查采用的规则边界</div>
        </div>
        <div class="card-body">
          <table class="table compact">
            <tbody>
              <tr
                ><th>规则模板</th
                ><td
                  >{{ latestAiRun?.ruleVersion || 'Welder-Qualification-B-v2.1' }}
                  <span class="pill green">当前使用</span></td
                ></tr
              >
              <tr
                ><th>适用节点</th><td>{{ currentNodeLabel }}</td></tr
              >
              <tr
                ><th>输入资料</th
                ><td>{{
                  bindings
                    .map((item) => item.fileName)
                    .slice(0, 5)
                    .join('、') || '资格证、名册、工艺文件、施焊记录、外部查询结果'
                }}</td></tr
              >
              <tr><th>输出格式</th><td>核验步骤、步骤结论、引用证据、建议结论、人工确认项</td></tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="card">
        <div class="card-body">
          <div class="metrics">
            <div class="metric"
              ><div class="metric-label">过程文件</div
              ><div class="metric-value">{{ bindings.length }}</div></div
            >
            <div class="metric"
              ><div class="metric-label">核验步骤</div
              ><div class="metric-value green"
                >{{ reviewSteps.length }} / {{ reviewSteps.length || 1 }}</div
              ></div
            >
            <div class="metric"
              ><div class="metric-label">证据引用</div
              ><div class="metric-value">{{ latestAiRun?.evidenceLinks.length || 0 }} 条</div></div
            >
            <div class="metric"
              ><div class="metric-label">业务风险</div
              ><div class="metric-value green">{{
                latestAiRun?.suggestion.result === '需补正' ? 1 : 0
              }}</div></div
            >
            <div class="metric"
              ><div class="metric-label">待人工确认</div
              ><div class="metric-value orange"
                >{{ latestAiRun?.suggestion.manualConfirmItems.length || 0 }} 项</div
              ></div
            >
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.role-static-sections {
  width: 100%;
}

.card {
  margin-bottom: 12px;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 6px;
  box-shadow: var(--shadow);
}

.card-head {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  min-height: 50px;
  padding: 13px 16px;
  border-bottom: 1px solid var(--line-soft);
}

.card-body {
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
  line-height: 1.2;
}

p {
  margin: 0;
  color: #344054;
  font-size: 14px;
  font-weight: 700;
  line-height: 1.7;
}

.sub {
  margin-top: 6px;
  color: var(--muted);
  font-size: 14px;
  font-weight: 700;
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

.owner-metrics {
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
  color: var(--muted);
  font-size: 13px;
  font-weight: 800;
}

.metric-value {
  margin-top: 8px;
  color: var(--blue);
  font-size: 24px;
  font-weight: 900;
  line-height: 1;
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

.table {
  width: 100%;
  font-size: 14px;
  table-layout: fixed;
  border-collapse: collapse;
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
  color: #485a73;
  font-weight: 900;
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
  align-items: center;
  justify-content: center;
  min-height: 24px;
  padding: 3px 8px;
  color: var(--blue-2);
  font-size: 13px;
  font-weight: 800;
  line-height: 1;
  white-space: nowrap;
  background: var(--blue-soft);
  border: 1px solid #bcd4ff;
  border-radius: 5px;
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
  transition:
    background-color 0.18s ease,
    border-color 0.18s ease;
}

.review-step:hover {
  background: #f8fbff;
  border-color: #c4d5ee;
}

.step-no {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  color: #fff;
  font-weight: 900;
  background: var(--blue);
  border-radius: 50%;
}

.step-title {
  font-weight: 900;
}

.step-desc {
  margin-top: 6px;
  color: #344054;
  font-size: 14px;
  line-height: 1.6;
}

.evidence-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.chain-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.chain-card {
  min-height: 116px;
  padding: 14px;
  background: #fbfdff;
  border: 1px solid var(--line-soft);
  border-radius: 6px;
  transition:
    background-color 0.18s ease,
    border-color 0.18s ease;
}

.chain-card:hover {
  background: #f8fbff;
  border-color: #c4d5ee;
}

.upload-box {
  display: grid;
  min-height: 128px;
  place-items: center;
  padding: 22px;
  color: #37506f;
  font-size: 18px;
  font-weight: 900;
  text-align: center;
  background: #f8fbff;
  border: 1px dashed #9db8df;
  border-radius: 6px;
}

.textarea-like {
  min-height: 128px;
  padding: 11px 12px;
  color: #26364e;
  font-weight: 800;
  line-height: 1.7;
  background: #fff;
  border: 1px solid #cbd8ea;
  border-radius: 5px;
}

.action-text {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 6px;
  color: var(--blue-2);
  font-weight: 900;
  border-radius: 5px;
  transition:
    color 0.18s ease,
    background-color 0.18s ease;
}

.action-text:hover {
  color: var(--blue);
  background: var(--blue-soft);
}

@media (prefers-reduced-motion: reduce) {
  .table th,
  .table td,
  .review-step,
  .chain-card,
  .action-text {
    transition: none;
  }
}

.timeline {
  display: grid;
  gap: 12px;
}

.time-row {
  display: grid;
  grid-template-columns: 14px minmax(0, 1fr);
  gap: 10px;
  color: #344054;
  font-size: 14px;
  font-weight: 700;
  line-height: 1.6;
}

.time-dot {
  width: 11px;
  height: 11px;
  margin-top: 6px;
  background: var(--green);
  border-radius: 50%;
}

.time-dot.red {
  background: var(--red);
}

.time-dot.orange {
  background: var(--orange);
}
</style>
