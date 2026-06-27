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
const extractedFields = computed(() => props.packageData?.extractedFields || [])
const evidenceLinks = computed(() => props.packageData?.aiRuns[0]?.evidenceLinks || [])
const latestAiRun = computed(() => props.packageData?.aiRuns[0])
const latestReport = computed(() => props.reports[0])
const latestArchive = computed(() => props.archiveItems[0])
const firstBinding = computed(() => bindings.value[0])
const firstProjectFile = computed(() => projectFiles.value[0])
const firstExtractedField = computed(() => extractedFields.value[0])
const firstEvidence = computed(() => evidenceLinks.value[0])
const firstNdtReport = computed(() => props.ndtReports[0])
const firstNdtFilm = computed(() => props.ndtFilms[0])
const correctionFeedback = computed(() =>
  props.ndtFeedback.find((item) => item.status === '待反馈')
)

const currentNodeLabel = computed(() => {
  if (!props.node) return '未选择节点'
  return `${props.node.nodeId}. ${props.node.name}`
})

const linkedNodeText = computed(() => {
  if (!firstBinding.value) return currentNodeLabel.value
  return `${firstBinding.value.nodeId}. ${props.node?.name || '当前节点'}`
})

const ownerMetricValue = (label: string, fallback: string | number) => {
  return props.metrics.find((metric) => metric.label.includes(label))?.value || fallback
}

const ownerLinkCount = computed(() => ownerMetricValue('链路', 26))
const ownerPassCount = computed(() => ownerMetricValue('通过', 18))
const ownerCorrectionCount = computed(() => ownerMetricValue('补正', 4))
const ownerPendingCount = computed(() => ownerMetricValue('待', 7))

const inspectionStatusRows = computed(() => [
  { label: '文件总数', value: bindings.value.length || props.node?.fileCount || 0 },
  {
    label: '核验完成',
    value: `${props.reviewSteps.filter((step) => getPillClass(step.result) === 'green').length} / ${
      props.reviewSteps.length || 1
    }`
  },
  {
    label: '业务风险',
    value: latestAiRun.value?.suggestion.result === '需补正' ? '1' : '0'
  },
  {
    label: '待确认',
    value: latestAiRun.value?.suggestion.manualConfirmItems[0] || '资格网站截图来源'
  },
  { label: '建议结论', value: latestAiRun.value?.suggestion.result || '待核验' }
])

const contractorFeedback = computed(() => {
  const riskyStep =
    props.reviewSteps.find((step) => getPillClass(step.result) !== 'green') || props.reviewSteps[0]
  return {
    node: currentNodeLabel.value,
    opinion: riskyStep?.desc || '当前节点暂无监检反馈。',
    requirement:
      riskyStep && getPillClass(riskyStep.result) !== 'green'
        ? '按监检意见补充资料并重新提交挂载关系。'
        : '无需修改文件；如监检要求，可补充最新查询截图。',
    deadline: '2026-06-28 18:00',
    result: riskyStep?.result || '待反馈'
  }
})

const ndtSupplement = computed(() => {
  const feedback = correctionFeedback.value
  return {
    item: feedback?.title || '返修复拍后的底片和处理记录',
    step:
      props.reviewSteps.find((step) => getPillClass(step.result) !== 'green')?.title ||
      '返修复拍闭环核验',
    evidence:
      feedback?.description ||
      latestAiRun.value?.suggestion.opinionDraft ||
      'RT 检测报告 R2 第 1 页结论',
    advice: '上传复拍底片并挂载到 40、41 节点。'
  }
})

const getPillClass = (value?: string | number) => {
  const text = String(value || '')
  if (!text) return 'blue'
  if (
    text.includes('通过') ||
    text.includes('满足') ||
    text.includes('归档') ||
    text.includes('只读') ||
    text.includes('合格') ||
    text === '0'
  ) {
    return 'green'
  }
  if (
    text.includes('补正') ||
    text.includes('失败') ||
    text.includes('禁止') ||
    text.includes('风险') ||
    text.includes('缺') ||
    text.includes('异常')
  ) {
    return 'red'
  }
  if (
    text.includes('待') ||
    text.includes('AI') ||
    text.includes('草稿') ||
    text.includes('复核') ||
    text.includes('确认') ||
    text.includes('生成') ||
    text.includes('/')
  ) {
    return 'orange'
  }
  return 'blue'
}
</script>

<template>
  <div class="workbench-right-static-details">
    <template v-if="role === 'inspection'">
      <section class="right-card">
        <h3>当前证据定位</h3>
        <div class="body">
          <table class="table compact">
            <tbody>
              <tr>
                <th>证据字段</th>
                <td>{{
                  firstEvidence?.fieldName || firstExtractedField?.fieldName || '证书编号'
                }}</td>
              </tr>
              <tr>
                <th>文件页码</th>
                <td>{{ firstEvidence?.pageNo ? `第 ${firstEvidence.pageNo} 页` : '第 1 页' }}</td>
              </tr>
              <tr
                ><th>核验步骤</th><td>{{ reviewSteps[0]?.title || '证书真实性核验' }}</td></tr
              >
              <tr><th>外部工具</th><td>资格审查网站查询截图</td></tr>
              <tr>
                <th>证据状态</th>
                <td><span class="pill orange">需人工确认来源有效性</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="right-card">
        <h3>文件属性</h3>
        <div class="body">
          <table class="table compact">
            <tbody>
              <tr
                ><th>文件名</th><td>{{ firstBinding?.fileName || '当前节点资料预览' }}</td></tr
              >
              <tr
                ><th>所属节点</th><td>{{ node?.groupName || '-' }} / {{ currentNodeLabel }}</td></tr
              >
              <tr
                ><th>资料项</th
                ><td>{{
                  firstBinding?.requirementName || firstBinding?.usage || '节点资料项'
                }}</td></tr
              >
              <tr
                ><th>来源单位</th
                ><td>{{ firstBinding?.sourceOrgName || project?.contractorOrgName || '-' }}</td></tr
              >
              <tr
                ><th>上传人</th><td>{{ firstProjectFile?.uploaderName || '施工方 李工' }}</td></tr
              >
              <tr
                ><th>文件版本</th><td>{{ firstBinding?.versionNo || 'V1' }}</td></tr
              >
              <tr
                ><th>业务链路</th><td><span class="pill green">已生成</span></td></tr
              >
              <tr
                ><th>关联证据数</th
                ><td
                  >{{ evidenceLinks.length || 0 }} 条
                  <span class="action-text">查看证据链</span></td
                ></tr
              >
            </tbody>
          </table>
        </div>
      </section>

      <section class="right-card">
        <h3>节点审查状态</h3>
        <div class="body">
          <table class="table compact">
            <tbody>
              <tr v-for="row in inspectionStatusRows" :key="row.label">
                <th>{{ row.label }}</th>
                <td>
                  <span
                    v-if="['建议结论', '业务风险'].includes(row.label)"
                    :class="['pill', getPillClass(row.value)]"
                  >
                    {{ row.value }}
                  </span>
                  <template v-else>{{ row.value }}</template>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>

    <template v-else-if="role === 'contractor'">
      <section class="right-card">
        <h3>当前反馈摘要</h3>
        <div class="body">
          <table class="table compact">
            <tbody>
              <tr
                ><th>反馈节点</th><td>{{ contractorFeedback.node }}</td></tr
              >
              <tr
                ><th>监检意见</th><td>{{ contractorFeedback.opinion }}</td></tr
              >
              <tr
                ><th>补正要求</th><td>{{ contractorFeedback.requirement }}</td></tr
              >
              <tr
                ><th>截止时间</th><td>{{ contractorFeedback.deadline }}</td></tr
              >
            </tbody>
          </table>
        </div>
      </section>

      <section class="right-card">
        <h3>业务链路只读摘要</h3>
        <div class="body">
          <table class="table compact">
            <tbody>
              <tr
                ><th>审查对象</th><td>{{ reviewSteps[0]?.title || currentNodeLabel }}</td></tr
              >
              <tr
                ><th>核验链路</th
                ><td>{{ reviewSteps[0]?.desc || '业务链路等待监检反馈。' }}</td></tr
              >
              <tr>
                <th>建议结论</th>
                <td
                  ><span :class="['pill', getPillClass(contractorFeedback.result)]">{{
                    contractorFeedback.result
                  }}</span></td
                >
              </tr>
              <tr
                ><th>施工方动作</th><td>{{ contractorFeedback.requirement }}</td></tr
              >
            </tbody>
          </table>
        </div>
      </section>

      <section class="right-card">
        <h3>文件属性</h3>
        <div class="body">
          <table class="table compact">
            <tbody>
              <tr
                ><th>文件名</th
                ><td>{{
                  firstBinding?.fileName || firstProjectFile?.fileName || '项目文件'
                }}</td></tr
              >
              <tr
                ><th>项目级状态</th
                ><td
                  ><span
                    :class="['pill', getPillClass(firstProjectFile?.fileStatus || '已上传')]"
                    >{{ firstProjectFile?.fileStatus || '已上传' }}</span
                  ></td
                ></tr
              >
              <tr
                ><th>挂载节点</th><td>{{ linkedNodeText }}</td></tr
              >
              <tr
                ><th>资料项</th><td>{{ firstBinding?.requirementName || '节点资料项' }}</td></tr
              >
              <tr
                ><th>文件用途</th><td>{{ firstBinding?.usage || '原始提交' }}</td></tr
              >
              <tr
                ><th>挂载状态</th
                ><td
                  ><span :class="['pill', getPillClass(firstBinding?.bindingStatus || '未挂载')]">{{
                    firstBinding?.bindingStatus || '未挂载'
                  }}</span></td
                ></tr
              >
              <tr
                ><th>关联意见</th
                ><td
                  >{{ getPillClass(contractorFeedback.result) === 'red' ? '1 条' : '链路反馈' }}
                  <span class="action-text">查看</span></td
                ></tr
              >
            </tbody>
          </table>
        </div>
      </section>

      <section class="right-card">
        <h3>处理进度</h3>
        <div class="body">
          <div class="timeline">
            <div class="time-row"
              ><span class="time-dot red"></span
              ><div><strong>监检反馈</strong><br />{{ contractorFeedback.opinion }}</div></div
            >
            <div class="time-row"
              ><span class="time-dot orange"></span
              ><div><strong>补正草稿</strong><br />已新增复验报告和差异说明。</div></div
            >
            <div class="time-row"
              ><span class="time-dot"></span
              ><div><strong>等待提交</strong><br />提交文件及挂载关系后进入重新审查。</div></div
            >
          </div>
        </div>
      </section>
    </template>

    <template v-else-if="role === 'ndt'">
      <section class="right-card">
        <h3>链路补充提示</h3>
        <div class="body">
          <table class="table compact">
            <tbody>
              <tr
                ><th>需补充项</th><td>{{ ndtSupplement.item }}</td></tr
              >
              <tr
                ><th>关联步骤</th><td>{{ ndtSupplement.step }}</td></tr
              >
              <tr
                ><th>关联证据</th><td>{{ ndtSupplement.evidence }}</td></tr
              >
              <tr
                ><th>处理建议</th><td>{{ ndtSupplement.advice }}</td></tr
              >
            </tbody>
          </table>
        </div>
      </section>

      <section class="right-card">
        <h3>资料属性</h3>
        <div class="body">
          <table class="table compact">
            <tbody>
              <tr
                ><th>资料名称</th
                ><td>{{
                  firstNdtReport?.reportNo || firstBinding?.fileName || 'RT 检测报告 R2.pdf'
                }}</td></tr
              >
              <tr
                ><th>所属节点</th
                ><td>{{ node?.groupName || '无损检测' }} / {{ currentNodeLabel }}</td></tr
              >
              <tr
                ><th>关联节点</th
                ><td>{{
                  firstNdtReport?.relatedFilmIds.length ? '40、41、65' : currentNodeLabel
                }}</td></tr
              >
              <tr
                ><th>检测方法</th
                ><td>{{ firstNdtReport?.method || firstNdtFilm?.method || 'RT' }}</td></tr
              >
              <tr
                ><th>底片数量</th
                ><td>{{ firstNdtReport?.relatedFilmIds.length || ndtFilms.length || '-' }}</td></tr
              >
              <tr
                ><th>资料状态</th
                ><td
                  ><span :class="['pill', getPillClass(firstNdtReport?.status || '草稿')]">{{
                    firstNdtReport?.status || '草稿'
                  }}</span></td
                ></tr
              >
              <tr
                ><th>OCR/图像</th><td><span class="pill blue">识别中</span></td></tr
              >
            </tbody>
          </table>
        </div>
      </section>

      <section class="right-card">
        <h3>办理进度</h3>
        <div class="body">
          <div class="timeline">
            <div class="time-row"
              ><span class="time-dot"></span
              ><div
                ><strong>检测记录已导入</strong><br />{{
                  ndtRecords.length || 0
                }}
                条记录已完成节点挂载。</div
              ></div
            >
            <div class="time-row"
              ><span class="time-dot orange"></span
              ><div
                ><strong>报告待提交</strong><br />{{
                  firstNdtReport?.reportNo || 'RT 检测报告'
                }}
                当前状态：{{ firstNdtReport?.status || '草稿' }}。</div
              ></div
            >
            <div class="time-row"
              ><span class="time-dot red"></span
              ><div
                ><strong>现场抽查需补正</strong><br />{{
                  correctionFeedback?.description || '补充拍摄时间和焊口编号标识。'
                }}</div
              ></div
            >
          </div>
        </div>
      </section>
    </template>

    <template v-else-if="role === 'owner'">
      <section class="right-card">
        <h3>当前节点资料摘要</h3>
        <div class="body">
          <table class="table compact">
            <tbody>
              <tr
                ><th>当前节点</th><td>{{ currentNodeLabel }}</td></tr
              >
              <tr
                ><th>业务大类</th><td>{{ node?.groupName || '-' }}</td></tr
              >
              <tr
                ><th>资料状态</th
                ><td
                  ><span :class="['pill', getPillClass(node?.status)]">{{
                    node?.status || '-'
                  }}</span></td
                ></tr
              >
              <tr
                ><th>审查状态</th
                ><td>{{ node?.status === '需补正' ? '退回补正' : node?.status || '-' }}</td></tr
              >
              <tr
                ><th>挂载资料数</th><td>{{ node?.fileCount || bindings.length || 0 }}</td></tr
              >
              <tr
                ><th>最近异常</th
                ><td>{{
                  node?.status === '需补正'
                    ? '炉批号与材料清单不一致，需补充说明。'
                    : '暂无高风险异常。'
                }}</td></tr
              >
            </tbody>
          </table>
        </div>
      </section>

      <section class="right-card">
        <h3>业务链路状态</h3>
        <div class="body">
          <table class="table compact">
            <tbody>
              <tr
                ><th>已生成链路</th><td>{{ ownerLinkCount }} 个节点</td></tr
              >
              <tr
                ><th>满足要求</th><td>{{ ownerPassCount }} 个</td></tr
              >
              <tr
                ><th>需补正</th><td>{{ ownerCorrectionCount }} 个</td></tr
              >
              <tr
                ><th>待人工确认</th><td>{{ ownerPendingCount }} 个</td></tr
              >
            </tbody>
          </table>
        </div>
      </section>

      <section class="right-card">
        <h3>最近异常提醒</h3>
        <div class="body">
          <div class="timeline">
            <div class="time-row"
              ><span class="time-dot red"></span
              ><div><strong>材料质量证明文件</strong><br />炉批号差异说明缺失。</div></div
            >
            <div class="time-row"
              ><span class="time-dot red"></span
              ><div
                ><strong>射线检测现场抽查</strong><br />照片缺少拍摄时间和焊口编号标识。</div
              ></div
            >
            <div class="time-row"
              ><span class="time-dot orange"></span
              ><div
                ><strong>报告归档</strong><br />{{
                  latestReport?.status || latestArchive?.status || '待生成'
                }}。</div
              ></div
            >
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.workbench-right-static-details {
  width: 100%;
}

.right-card {
  margin-top: 12px;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 6px;
  transition:
    border-color 0.18s ease,
    box-shadow 0.18s ease;
}

.right-card:hover,
.right-card:focus-within {
  border-color: #c4d5ee;
  box-shadow: 0 2px 8px rgba(20, 34, 56, 0.08);
}

.right-card h3 {
  padding: 13px 16px;
  margin: 0;
  font-size: 18px;
  line-height: 1.2;
  border-bottom: 1px solid var(--line-soft);
}

.right-card .body {
  padding: 14px 16px;
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
  width: 128px;
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
  .right-card,
  .table th,
  .table td,
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
