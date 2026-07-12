<script setup lang="ts">
import { computed, ref } from 'vue'
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

type ContractorFileStatus = '全部' | '待提交' | '审核中' | '需补正' | '已通过' | '已作废'
type ContractorSortKey = 'updatedDesc' | 'updatedAsc' | 'status' | 'version'
type ContractorMaterialStatus = '已覆盖' | '部分上传' | '待上传' | '需补正'
type ContractorMaterialRequirement = {
  category: string
  requiredItems: string
  keywords: string[]
  missingHint: string
  nodeRefs: string
}
type ContractorFileRow = {
  id: string
  documentId: string
  fileName: string
  materialCategory: string
  requirementName: string
  necessity: '必传' | '条件必传' | '可选'
  usage: string
  version: string
  status: Exclude<ContractorFileStatus, '全部'>
  sourceOrgName: string
  relationNode: string
  feedback: string
  ocr: string
  processingStatus: string
  uploader: string
  updatedAt: string
}

const props = defineProps<{
  role: RoleCode
  project?: Project
  node?: ProjectTreeNode
  packageData?: NodePackagePayload
  readOnly?: boolean
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

const emit = defineEmits<{
  upload: [materialCategory?: string]
  bind: []
  rectify: [rectificationId?: string]
  'file-view': [documentId: string]
  'file-bind': [documentId: string]
  'file-submit': [documentId: string]
  'file-delete': [documentId: string]
}>()

const bindings = computed(() => props.packageData?.bindings || [])
const projectFiles = computed(() => props.packageData?.projectFiles || [])
const rectifications = computed(() => props.packageData?.rectifications || [])
const requirements = computed(() => props.packageData?.requirements || [])
const extractedFields = computed(() => props.packageData?.extractedFields || [])
const latestAiRun = computed(() => props.packageData?.aiRuns[0])
const latestReport = computed(() => props.reports[0])
const latestArchive = computed(() => props.archiveItems[0])
const correctionFeedback = computed(() =>
  props.ndtFeedback.find((item) => item.status === '待反馈')
)

const contractorStatusFilter = ref<ContractorFileStatus>('全部')
const contractorUsageFilter = ref('全部用途')
const contractorKeyword = ref('')
const contractorSort = ref<ContractorSortKey>('updatedDesc')
const contractorPage = ref(1)
const contractorPageSize = 5

const contractorStatusOptions: ContractorFileStatus[] = [
  '全部',
  '待提交',
  '审核中',
  '需补正',
  '已通过',
  '已作废'
]

const contractorMaterialRequirements: ContractorMaterialRequirement[] = [
  {
    category: '资质证照',
    requiredItems: '施工单位安装许可证、设计单位资质、焊工资格证、元件制造许可',
    keywords: ['许可证', '资质', '焊工', '制造许可', '许可资质'],
    missingHint: '核验施工/设计/检测/制造单位资质和人员证书是否覆盖项目范围',
    nodeRefs: 'R01、R02、R03、R12、R57'
  },
  {
    category: '设计资料',
    requiredItems: '图纸目录、设计说明、数据表、材料表、布置图、强度/应力计算',
    keywords: ['设计', '图纸', '施工图', '说明书', '数据表', '特性表', '材料表', '计算书'],
    missingHint: '补齐设计基础资料、计算书、设计变更或特殊标准符合性说明',
    nodeRefs: 'R04、R06、R08、R09、R51'
  },
  {
    category: '施工方案',
    requiredItems: '施工组织设计、施工方案、试压/泄漏/吹扫清洗专项方案',
    keywords: ['施工方案', '施工组织', '试压方案', '泄漏试验', '吹扫', '清洗方案'],
    missingHint: '确认方案审批页、建设单位批复和专项试验方案是否齐全',
    nodeRefs: 'R11、R47、R55、R56'
  },
  {
    category: '焊接资料',
    requiredItems: 'WPS/PQR、焊材证明、焊材烘干/领用、组对、焊接记录、返修闭环',
    keywords: ['焊接', '焊材', 'WPS', 'PQR', '焊缝', '返修', '组对'],
    missingHint: '补齐焊材过程记录、焊缝编号、外观检查和返修闭环资料',
    nodeRefs: 'R13、R14、R15、R16、R17、R18、R19'
  },
  {
    category: '热处理资料',
    requiredItems: '热处理工艺卡、评定报告、仪表校验、曲线、热处理报告、硬度报告',
    keywords: ['热处理', '硬度', '温控', '热电偶', '曲线'],
    missingHint: '若不涉及热处理，应在资料状态中标记不适用；涉及时需上传完整过程资料',
    nodeRefs: 'R20、R21、R22'
  },
  {
    category: '防腐保温资料',
    requiredItems: '防腐/保温材料证明、施工记录、补口补伤、电火花检测、阴保资料',
    keywords: ['防腐', '保温', '涂料', '补口', '补伤', '电火花', '阴极保护', '静电接地'],
    missingHint: '核验材料批号、厚度、漏点检测、电火花仪器检定和阴保验收资料',
    nodeRefs: 'R31-R35、R38、R39'
  },
  {
    category: '安装交工资料',
    requiredItems: '元件检查、安装记录、支吊架、穿跨越、单线图、静电接地、交工资料',
    keywords: ['交工', '安装记录', '支吊架', '穿跨越', '单线图', '元件检查', '接地'],
    missingHint: '补齐安装过程记录、穿跨越记录、支撑件和单线图等交工资料',
    nodeRefs: 'R36-R43'
  },
  {
    category: '安全附件与阀门',
    requiredItems: '安全阀/爆破片/紧急切断阀资料、校验报告、阀门试验记录',
    keywords: ['安全阀', '爆破片', '紧急切断', '阀门', '校验', '压力试验'],
    missingHint: '核验安全附件产品资料、安装位置、校验报告和阀门耐压试验记录',
    nodeRefs: 'R44、R45、R46、R68'
  },
  {
    category: '试验与吹扫资料',
    requiredItems: '压力表检定、耐压试验、泄漏试验、吹扫清洗记录、现场确认资料',
    keywords: ['耐压', '压力表', '泄漏', '吹扫', '清洗', '试验记录', '试验报告'],
    missingHint: '补齐压力表检定、试验参数、过程照片/视频和监检确认记录',
    nodeRefs: 'R48、R49、R50、R54、R55、R56'
  },
  {
    category: '材料证明与复验',
    requiredItems: '产品质量证明、出厂检验、到货验收、抽样复验、材料复验、标志移植',
    keywords: ['质量证明', '材质', '材料', '复验', '出厂检验', '验收', '标志移植'],
    missingHint: '核验产品质量证明、验收见证、抽样复验和材料追溯资料',
    nodeRefs: 'R58-R66'
  }
]

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
  if (!node) return []
  return [
    {
      group: node.groupName || '--',
      node: currentNodeLabel.value,
      fileStatus: node.status,
      reviewStatus: node.status === '需补正' ? '退回补正' : node.status,
      files: node.fileCount ?? bindings.value.length,
      warnings: node.status === '需补正' ? 1 : 0,
      updatedAt: props.project?.updatedAt || '--'
    }
  ]
})

const mapContractorFileStatus = (
  fileStatus?: string,
  relationStatus?: string
): Exclude<ContractorFileStatus, '全部'> => {
  if (fileStatus === '已作废' || fileStatus === '已替换') return '已作废'
  if (relationStatus === '已通过') return '已通过'
  if (relationStatus === '需补正') return '需补正'
  if (relationStatus === '已提交') return '审核中'
  return '待提交'
}

const bindingForProjectFile = (file: NodePackagePayload['projectFiles'][number]) =>
  file.primaryBinding ||
  file.bindings?.[0] ||
  bindings.value.find((item) => item.documentId === file.id)

const getRelationNodeText = (binding?: (typeof bindings.value)[number]) => {
  if (!binding) return '未关联审核环节'
  return `${binding.nodeId}. ${binding.requirementName || props.node?.name || '审核环节'}`
}

const normalizeSearchText = (...parts: Array<string | undefined>) => parts.join(' ').toLowerCase()

const pipelineStatusForFile = (file: NodePackagePayload['projectFiles'][number]) => {
  const statuses = [file.currentOcrStatus, file.sliceStatus, file.vectorStatus].filter(Boolean)
  if (statuses.some((status) => String(status).includes('失败'))) return '失败可重试'
  if (file.currentOcrStatus === '排队中') return '排队中'
  if (file.currentOcrStatus && file.currentOcrStatus !== '已识别') return 'OCR 中'
  if (file.sliceStatus && file.sliceStatus !== '已切片') return '切片中'
  if (file.vectorStatus && file.vectorStatus !== '已向量化') return '向量化中'
  if (file.vectorStatus === '已向量化') return '已完成'
  return file.currentOcrStatus || '排队中'
}

const inferMaterialCategory = (text: string) => {
  const normalized = text.toLowerCase()
  return (
    contractorMaterialRequirements.find((item) =>
      item.keywords.some((keyword) => normalized.includes(keyword.toLowerCase()))
    )?.category || '其他资料'
  )
}

const inferNecessity = (category: string): ContractorFileRow['necessity'] => {
  if (['热处理资料', '防腐保温资料', '安全附件与阀门'].includes(category)) return '条件必传'
  if (category === '其他资料') return '可选'
  return '必传'
}

const rectificationIdForBinding = (bindingId?: string) => {
  if (!bindingId) return '--'
  return rectifications.value.find((item) => item.bindingIds?.includes(bindingId))?.id || '--'
}

const contractorFileRows = computed<ContractorFileRow[]>(() => {
  const rows = projectFiles.value.map((file) => {
    const binding = bindingForProjectFile(file)
    const status = mapContractorFileStatus(file.fileStatus, binding?.bindingStatus)
    const materialCategory =
      file.materialCategory ||
      inferMaterialCategory(
        normalizeSearchText(file.fileName, binding?.usage, binding?.requirementName)
      )
    return {
      id: file.id,
      documentId: file.id,
      fileName: file.fileName,
      materialCategory,
      requirementName: binding?.requirementName || '--',
      necessity: inferNecessity(materialCategory),
      usage: binding?.usage || '--',
      version: binding?.versionNo || '--',
      status,
      sourceOrgName: file.sourceOrgName,
      relationNode: getRelationNodeText(binding),
      feedback: binding?.bindingStatus === '需补正' ? rectificationIdForBinding(binding.id) : '--',
      ocr: file.currentOcrStatus,
      processingStatus: pipelineStatusForFile(file),
      uploader: file.uploaderName,
      updatedAt: file.updatedAt
    }
  })
  if (rows.length) return rows
  return bindings.value.map((binding) => ({
    id: binding.id,
    documentId: binding.documentId,
    fileName: binding.fileName,
    materialCategory: inferMaterialCategory(
      normalizeSearchText(binding.fileName, binding.usage, binding.requirementName)
    ),
    requirementName: binding.requirementName || '--',
    necessity: inferNecessity(
      inferMaterialCategory(
        normalizeSearchText(binding.fileName, binding.usage, binding.requirementName)
      )
    ),
    usage: binding.usage,
    version: binding.versionNo,
    status: mapContractorFileStatus('已上传', binding.bindingStatus),
    sourceOrgName: binding.sourceOrgName,
    relationNode: getRelationNodeText(binding),
    feedback: binding.bindingStatus === '需补正' ? rectificationIdForBinding(binding.id) : '--',
    ocr: '--',
    processingStatus: '--',
    uploader: '--',
    updatedAt: binding.boundAt
  }))
})

const contractorMaterialChecklist = computed(() => {
  const groupedRequirements = requirements.value.reduce((groups, requirement) => {
    const category = inferMaterialCategory(requirement.name)
    const values = groups.get(category) || []
    values.push(requirement)
    groups.set(category, values)
    return groups
  }, new Map<string, typeof requirements.value>())
  return contractorMaterialRequirements
    .filter((requirement) => groupedRequirements.has(requirement.category))
    .map((requirement) => {
      const categoryRequirements = groupedRequirements.get(requirement.category) || []
      const files = contractorFileRows.value.filter(
        (file) => file.materialCategory === requirement.category
      )
      const correctionCount = files.filter((file) => file.status === '需补正').length
      const status: ContractorMaterialStatus = correctionCount
        ? '需补正'
        : files.length
          ? '已覆盖'
          : '待上传'
      return {
        ...requirement,
        requiredItems: categoryRequirements.map((item) => item.name).join('、') || '--',
        nodeRefs: categoryRequirements.map((item) => String(item.nodeId)).join('、') || '--',
        uploadedCount: files.length,
        correctionCount,
        status,
        missing:
          files.length && !correctionCount
            ? '已上传资料待监检核验'
            : correctionCount
              ? `${correctionCount} 份资料需按反馈补正`
              : `当前节点仍缺少：${categoryRequirements.map((item) => item.name).join('、')}`
      }
    })
})

const materialGapSummary = computed(() => {
  const pending = contractorMaterialChecklist.value.filter(
    (item) => item.status === '待上传'
  ).length
  const correction = contractorMaterialChecklist.value.filter(
    (item) => item.status === '需补正'
  ).length
  const covered = contractorMaterialChecklist.value.filter(
    (item) => item.status === '已覆盖'
  ).length
  return { pending, correction, covered, total: contractorMaterialChecklist.value.length }
})

const visibleMaterialChecklist = computed(() => {
  return contractorMaterialChecklist.value
})

const contractorFeedbackRows = computed(() => {
  if (rectifications.value.length) {
    return rectifications.value.map((rectification) => {
      const linkedBindings = rectification.bindingIds?.length
        ? bindings.value.filter((binding) => rectification.bindingIds?.includes(binding.id))
        : bindings.value.filter((binding) => binding.bindingStatus === '需补正')
      return {
        id: rectification.id,
        rectificationId: rectification.id,
        node: `${rectification.nodeId}. ${props.node?.name || '审核环节'}`,
        issue: '监检退回补正',
        requirement: rectification.comment || '请按监检意见补充资料。',
        result: rectification.status,
        status: rectification.status === '待反馈' ? '待处理' : rectification.status,
        linkedFiles: linkedBindings.length,
        feedbackAt: rectification.createdAt,
        dueAt: rectification.status === '待反馈' ? '按监检要求' : rectification.feedbackAt || '-'
      }
    })
  }
  return []
})

const contractorStatusCounts = computed<Record<ContractorFileStatus, number>>(() => {
  const counts = contractorStatusOptions.reduce(
    (result, status) => ({ ...result, [status]: 0 }),
    {} as Record<ContractorFileStatus, number>
  )
  contractorFileRows.value.forEach((file) => {
    counts[file.status] += 1
    counts.全部 += 1
  })
  return counts
})

const contractorUsageOptions = computed(() => [
  '全部用途',
  ...Array.from(new Set(contractorFileRows.value.map((file) => file.usage)))
])
const contractorMaterialOptions = computed(() => [
  '全部资料类别',
  ...Array.from(new Set(contractorFileRows.value.map((file) => file.materialCategory)))
])
const contractorMaterialFilter = ref('全部资料类别')

const filteredContractorFileRows = computed(() => {
  const keyword = contractorKeyword.value.trim().toLowerCase()
  const rows = contractorFileRows.value.filter((file) => {
    const matchesStatus =
      contractorStatusFilter.value === '全部' || file.status === contractorStatusFilter.value
    const matchesUsage =
      contractorUsageFilter.value === '全部用途' || file.usage === contractorUsageFilter.value
    const matchesMaterial =
      contractorMaterialFilter.value === '全部资料类别' ||
      file.materialCategory === contractorMaterialFilter.value
    const haystack = [
      file.fileName,
      file.materialCategory,
      file.requirementName,
      file.necessity,
      file.usage,
      file.sourceOrgName,
      file.relationNode,
      file.feedback,
      file.uploader
    ]
      .join(' ')
      .toLowerCase()
    return (
      matchesStatus && matchesUsage && matchesMaterial && (!keyword || haystack.includes(keyword))
    )
  })
  return rows.slice().sort((a, b) => {
    if (contractorSort.value === 'updatedAsc') {
      return Date.parse(a.updatedAt || '') - Date.parse(b.updatedAt || '')
    }
    if (contractorSort.value === 'status') return a.status.localeCompare(b.status, 'zh-Hans-CN')
    if (contractorSort.value === 'version') return b.version.localeCompare(a.version, 'zh-Hans-CN')
    return Date.parse(b.updatedAt || '') - Date.parse(a.updatedAt || '')
  })
})

const contractorTotalPages = computed(() =>
  Math.max(1, Math.ceil(filteredContractorFileRows.value.length / contractorPageSize))
)
const normalizedContractorPage = computed(() =>
  Math.min(contractorPage.value, contractorTotalPages.value)
)
const pagedContractorFileRows = computed(() => {
  const start = (normalizedContractorPage.value - 1) * contractorPageSize
  return filteredContractorFileRows.value.slice(start, start + contractorPageSize)
})

const setContractorStatusFilter = (status: ContractorFileStatus) => {
  contractorStatusFilter.value = status
  contractorPage.value = 1
}

const resetContractorFilePage = () => {
  contractorPage.value = 1
}

const requestUpload = (materialCategory?: string) => {
  if (!props.readOnly) emit('upload', materialCategory)
}

const requestBind = () => {
  if (!props.readOnly) emit('bind')
}

const requestFileView = (file: ContractorFileRow) => {
  emit('file-view', file.documentId)
}

const requestFileBind = (file: ContractorFileRow) => {
  if (!props.readOnly) emit('file-bind', file.documentId)
}

const requestFileSubmit = (file: ContractorFileRow) => {
  if (!props.readOnly && file.status === '待提交') emit('file-submit', file.documentId)
}

const requestFileDelete = (file: ContractorFileRow) => {
  if (!props.readOnly && file.status === '待提交') emit('file-delete', file.documentId)
}

const requestRectify = (rectificationId?: string) => {
  if (!props.readOnly) emit('rectify', rectificationId)
}

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
    value.includes('合格') ||
    value.includes('完成')
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
    value.includes('生成') ||
    value.includes('中')
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
          <div>
            <h2>一、项目文件库 / 施工资料台账</h2>
            <div class="sub">上传、资料分类、提交和可选环节关联统一在项目文件列表中处理。</div>
          </div>
          <div class="file-library-head-actions">
            <span class="pill blue"
              >{{ filteredContractorFileRows.length }} /
              {{ contractorFileRows.length }} 个文件</span
            >
            <span
              class="pill red"
              v-if="materialGapSummary.pending || materialGapSummary.correction"
            >
              {{ materialGapSummary.pending }} 类待上传 ·
              {{ materialGapSummary.correction }} 类需补正
            </span>
          </div>
        </div>
        <div class="card-body">
          <div class="material-checklist">
            <div class="material-checklist-head">
              <div>
                <h4>标准资料上传</h4>
                <p> 按业务规则中的标准资料类别对项目文件库进行归类，节点关联可后续补充。 </p>
              </div>
              <span class="pill blue">
                {{ materialGapSummary.covered }} / {{ materialGapSummary.total }} 类已有资料
              </span>
            </div>
            <div class="table-scroll">
              <table class="table compact material-gap-table">
                <colgroup>
                  <col class="material-gap-seq-col" />
                  <col class="material-gap-category-col" />
                  <col class="material-gap-action-col" />
                  <col class="material-gap-required-col" />
                  <col class="material-gap-uploaded-col" />
                  <col class="material-gap-missing-col" />
                  <col class="material-gap-status-col" />
                  <col class="material-gap-rule-col" />
                </colgroup>
                <thead>
                  <tr>
                    <th>序号</th>
                    <th>资料类别</th>
                    <th>操作</th>
                    <th>标准要求</th>
                    <th>已上传</th>
                    <th>缺口/待核验</th>
                    <th>状态</th>
                    <th>关联规则</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="(item, index) in visibleMaterialChecklist"
                    :key="item.category"
                    :class="{ selected: item.status === '需补正' || item.status === '待上传' }"
                  >
                    <td>{{ index + 1 }}</td>
                    <td>{{ item.category }}</td>
                    <td>
                      <button
                        type="button"
                        class="action-text action-button"
                        :disabled="readOnly"
                        @click="requestUpload(item.category)"
                      >
                        上传资料
                      </button>
                    </td>
                    <td>{{ item.requiredItems }}</td>
                    <td>{{ item.uploadedCount }} 份</td>
                    <td>{{ item.missing }}</td>
                    <td>
                      <span :class="['pill', getPillClass(item.status)]">{{ item.status }}</span>
                    </td>
                    <td>{{ item.nodeRefs }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <div class="file-library-tools">
            <div class="status-filter-row">
              <button
                v-for="status in contractorStatusOptions"
                :key="status"
                type="button"
                :class="['status-filter', { active: contractorStatusFilter === status }]"
                @click="setContractorStatusFilter(status)"
              >
                {{ status }} {{ contractorStatusCounts[status] }}
              </button>
            </div>
            <div class="filter-row">
              <input
                v-model="contractorKeyword"
                class="filter-input"
                type="search"
                placeholder="搜索文件名、资料类别、资料项、来源单位、审核环节或反馈编号"
                @input="resetContractorFilePage"
              />
              <select
                v-model="contractorMaterialFilter"
                class="filter-select"
                @change="resetContractorFilePage"
              >
                <option
                  v-for="material in contractorMaterialOptions"
                  :key="material"
                  :value="material"
                >
                  {{ material }}
                </option>
              </select>
              <select
                v-model="contractorUsageFilter"
                class="filter-select"
                @change="resetContractorFilePage"
              >
                <option v-for="usage in contractorUsageOptions" :key="usage" :value="usage">
                  {{ usage }}
                </option>
              </select>
              <select
                v-model="contractorSort"
                class="filter-select"
                @change="resetContractorFilePage"
              >
                <option value="updatedDesc">更新时间从新到旧</option>
                <option value="updatedAsc">更新时间从旧到新</option>
                <option value="status">按状态排序</option>
                <option value="version">按版本排序</option>
              </select>
            </div>
          </div>

          <div class="table-scroll">
            <table class="table contractor-files-table">
              <thead>
                <tr>
                  <th>序号</th>
                  <th>文件名</th>
                  <th>资料类别</th>
                  <th>资料项</th>
                  <th>必要性</th>
                  <th>文件用途</th>
                  <th>来源单位</th>
                  <th>状态</th>
                  <th>处理状态</th>
                  <th>版本</th>
                  <th>关联审核环节</th>
                  <th>关联反馈</th>
                  <th>上传人</th>
                  <th>更新时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="(file, index) in pagedContractorFileRows"
                  :key="file.id"
                  :class="{ selected: index === 0 }"
                >
                  <td>{{ (normalizedContractorPage - 1) * contractorPageSize + index + 1 }}</td>
                  <td>{{ file.fileName }}</td>
                  <td>{{ file.materialCategory }}</td>
                  <td>{{ file.requirementName }}</td>
                  <td>
                    <span :class="['pill', getPillClass(file.necessity)]">{{
                      file.necessity
                    }}</span>
                  </td>
                  <td>{{ file.usage }}</td>
                  <td>{{ file.sourceOrgName }}</td>
                  <td
                    ><span :class="['pill', getPillClass(file.status)]">{{ file.status }}</span></td
                  >
                  <td>
                    <span :class="['pill', getPillClass(file.processingStatus)]">
                      {{ file.processingStatus }}
                    </span>
                  </td>
                  <td>{{ file.version }}</td>
                  <td>{{ file.relationNode }}</td>
                  <td>{{ file.feedback }}</td>
                  <td>{{ file.uploader }}</td>
                  <td>{{ file.updatedAt }}</td>
                  <td>
                    <div class="table-actions">
                      <button
                        type="button"
                        class="action-text action-button"
                        @click="requestFileView(file)"
                      >
                        查看
                      </button>
                      <button
                        type="button"
                        class="action-text action-button"
                        :disabled="readOnly || file.status !== '待提交'"
                        :title="
                          file.status === '待提交'
                            ? '提交当前文件到所选审核环节'
                            : '当前状态不能重复提交'
                        "
                        @click="requestFileSubmit(file)"
                      >
                        提交
                      </button>
                      <button
                        type="button"
                        class="action-text action-button danger-action"
                        :disabled="readOnly || file.status !== '待提交'"
                        :title="
                          file.status === '待提交'
                            ? '删除未提交文件'
                            : '文件已提交审核，不能直接删除'
                        "
                        @click="requestFileDelete(file)"
                      >
                        删除
                      </button>
                      <button
                        type="button"
                        class="action-text action-button"
                        disabled
                        title="文件元数据编辑接口尚未接入"
                      >
                        编辑
                      </button>
                      <button
                        type="button"
                        class="action-text action-button"
                        disabled
                        title="当前版本替换上传接口尚未接入"
                      >
                        替换
                      </button>
                      <button
                        type="button"
                        class="action-text action-button"
                        :disabled="readOnly"
                        @click="requestFileBind(file)"
                      >
                        选择环节
                      </button>
                    </div>
                  </td>
                </tr>
                <tr v-if="!pagedContractorFileRows.length">
                  <td colspan="15">当前筛选条件下暂无文件</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="pagination-row">
            <span>第 {{ normalizedContractorPage }} / {{ contractorTotalPages }} 页</span>
            <div class="pagination-actions">
              <button
                type="button"
                class="action-text action-button"
                :disabled="normalizedContractorPage <= 1"
                @click="contractorPage -= 1"
              >
                上一页
              </button>
              <button
                type="button"
                class="action-text action-button"
                :disabled="normalizedContractorPage >= contractorTotalPages"
                @click="contractorPage += 1"
              >
                下一页
              </button>
            </div>
          </div>
        </div>
      </section>

      <section id="contractor-feedback-list" class="card">
        <div class="card-head">
          <div>
            <h2>二、审核反馈列表</h2>
            <div class="sub"
              >按监检退回补正意见逐项反馈，可上传新文件或关联项目文件库中的已有文件。</div
            >
          </div>
          <span class="pill orange"
            >{{
              contractorFeedbackRows.filter((item) => item.status !== '已关闭').length
            }}
            项待处理</span
          >
        </div>
        <div class="card-body">
          <div class="table-scroll">
            <table class="table contractor-feedback-table">
              <thead>
                <tr>
                  <th>反馈编号</th>
                  <th>问题环节</th>
                  <th>问题说明</th>
                  <th>反馈状态</th>
                  <th>关联文件</th>
                  <th>反馈时间</th>
                  <th>截止要求</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="(feedback, index) in contractorFeedbackRows"
                  :key="feedback.id"
                  :class="{ selected: feedback.status === '待处理' || index === 0 }"
                >
                  <td>{{ feedback.id }}</td>
                  <td>{{ feedback.node }}</td>
                  <td>
                    <strong>{{ feedback.issue }}</strong>
                    <div class="table-note">{{ feedback.requirement }}</div>
                  </td>
                  <td
                    ><span :class="['pill', getPillClass(feedback.status)]">{{
                      feedback.status
                    }}</span></td
                  >
                  <td>{{ feedback.linkedFiles }} 个</td>
                  <td>{{ feedback.feedbackAt }}</td>
                  <td>{{ feedback.dueAt }}</td>
                  <td>
                    <div class="table-actions">
                      <button
                        type="button"
                        class="action-text action-button"
                        :disabled="readOnly"
                        @click="requestUpload()"
                      >
                        上传补正
                      </button>
                      <button
                        type="button"
                        class="action-text action-button"
                        :disabled="readOnly"
                        @click="requestBind"
                      >
                        关联文件
                      </button>
                      <button
                        type="button"
                        class="action-text action-button"
                        :disabled="readOnly"
                        @click="requestRectify(feedback.rectificationId)"
                      >
                        提交反馈
                      </button>
                    </div>
                  </td>
                </tr>
                <tr v-if="!contractorFeedbackRows.length">
                  <td colspan="8">暂无审核反馈</td>
                </tr>
              </tbody>
            </table>
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
                new Set(ndtRecords.map((item) => item.nodeId)).size
              }}</div></div
            >
            <div class="metric"
              ><div class="metric-label">业务核验</div
              ><div class="metric-value orange"
                >{{ reviewSteps.filter((item) => getPillClass(item.result) === 'green').length }}/{{
                  reviewSteps.length
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
                  ><th>补正节点</th><td>{{ correctionFeedback?.nodeId ?? '--' }}</td></tr
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
                >{{ reviewSteps.length }} / {{ reviewSteps.length }}</div
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
  font-size: 14px;
  font-weight: 600;
  line-height: 1.7;
  color: #344054;
}

.sub {
  margin-top: 6px;
  font-size: 14px;
  font-weight: 600;
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
  font-size: 13px;
  font-weight: 600;
  color: var(--muted);
}

.metric-value {
  margin-top: 8px;
  font-size: 24px;
  font-weight: 600;
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

.table {
  width: 100%;
  font-size: 14px;
  border-collapse: collapse;
  table-layout: fixed;
}

.table-scroll {
  width: 100%;
  overflow-x: auto;
}

.contractor-feedback-table {
  min-width: 1120px;
}

.material-gap-table {
  min-width: 1280px;
}

.material-gap-seq-col {
  width: 64px;
}

.material-gap-category-col {
  width: 150px;
}

.material-gap-action-col {
  width: 112px;
}

.material-gap-required-col {
  width: 260px;
}

.material-gap-uploaded-col {
  width: 100px;
}

.material-gap-missing-col {
  width: 300px;
}

.material-gap-status-col {
  width: 112px;
}

.material-gap-rule-col {
  width: 180px;
}

.contractor-files-table {
  min-width: 1540px;
}

.contractor-files-table th:last-child,
.contractor-files-table td:last-child {
  position: sticky;
  right: 0;
  z-index: 1;
  width: 180px;
  background: #fff;
  box-shadow: -6px 0 10px rgb(15 23 42 / 6%);
}

.file-library-head-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  justify-content: flex-end;
}

.inline-upload-button {
  min-height: 32px;
  padding: 0 14px;
  font-size: 14px;
  font-weight: 600;
  color: #fff;
  cursor: pointer;
  background: var(--blue);
  border: 1px solid var(--blue);
  border-radius: 5px;
}

.inline-upload-button:hover:not(:disabled) {
  background: var(--blue-2);
  border-color: var(--blue-2);
}

.inline-upload-button:disabled {
  color: var(--muted);
  cursor: not-allowed;
  background: #f8fafc;
  border-color: var(--line);
}

.contractor-files-table th:last-child {
  z-index: 2;
  background: var(--head);
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
  font-weight: 600;
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

.table-note {
  margin-top: 4px;
  overflow: hidden;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.5;
  color: var(--muted);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pill {
  display: inline-flex;
  min-height: 24px;
  padding: 3px 8px;
  font-size: 13px;
  font-weight: 600;
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
  font-weight: 600;
  color: #fff;
  background: var(--blue);
  border-radius: 50%;
  place-items: center;
}

.step-title {
  font-weight: 600;
}

.step-desc {
  margin-top: 6px;
  font-size: 14px;
  line-height: 1.6;
  color: #344054;
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

.upload-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(320px, 0.75fr);
  gap: 12px;
  align-items: stretch;
}

.upload-box {
  display: grid;
  min-height: 128px;
  padding: 22px;
  font-size: 18px;
  font-weight: 600;
  color: #37506f;
  text-align: center;
  cursor: pointer;
  background: #f8fbff;
  border: 1px dashed #9db8df;
  border-radius: 6px;
  place-items: center;
}

.upload-box small {
  display: block;
  margin-top: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--muted);
}

.upload-box:hover:not(:disabled) {
  color: var(--blue-2);
  background: #f3f8ff;
  border-color: var(--blue);
}

.upload-box:disabled {
  color: var(--muted);
  cursor: not-allowed;
  background: #f8fafc;
  border-color: var(--line);
}

.upload-meta {
  height: 100%;
}

.file-library-tools {
  display: grid;
  gap: 10px;
  margin-bottom: 12px;
}

.material-checklist {
  display: grid;
  gap: 10px;
  padding: 12px;
  margin-bottom: 14px;
  background: #fbfdff;
  border: 1px solid var(--line-soft);
  border-radius: 6px;
}

.material-checklist-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: start;
}

.status-filter-row,
.filter-row,
.table-actions,
.pagination-row,
.pagination-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.filter-row {
  justify-content: space-between;
}

.filter-input,
.filter-select {
  min-height: 34px;
  padding: 0 10px;
  font-size: 14px;
  font-weight: 600;
  color: #26364e;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 5px;
}

.filter-input {
  flex: 1 1 320px;
  min-width: 240px;
}

.filter-select {
  flex: 0 1 210px;
}

.status-filter {
  min-height: 32px;
  padding: 0 10px;
  font-size: 13px;
  font-weight: 600;
  color: #485a73;
  cursor: pointer;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 5px;
}

.status-filter.active {
  color: var(--blue-2);
  background: var(--blue-soft);
  border-color: #bcd4ff;
}

.pagination-row {
  justify-content: space-between;
  margin-top: 12px;
  font-size: 13px;
  font-weight: 600;
  color: var(--muted);
}

.textarea-like {
  min-height: 128px;
  padding: 11px 12px;
  font-weight: 600;
  line-height: 1.7;
  color: #26364e;
  background: #fff;
  border: 1px solid #cbd8ea;
  border-radius: 5px;
}

.action-text {
  display: inline-flex;
  min-height: 24px;
  padding: 0 6px;
  font-weight: 600;
  color: var(--blue-2);
  border-radius: 5px;
  transition:
    color 0.18s ease,
    background-color 0.18s ease;
  align-items: center;
}

.action-button {
  cursor: pointer;
  background: transparent;
  border: 0;
}

.action-button:disabled {
  color: var(--muted);
  cursor: not-allowed;
  background: transparent;
}

.danger-action:not(:disabled) {
  color: #dc2626;
}

.action-button:not(:disabled):hover,
.action-text:not(.action-button):hover {
  color: var(--blue);
  background: var(--blue-soft);
}

.danger-action:not(:disabled):hover {
  color: #b91c1c;
  background: #fee2e2;
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
  font-size: 14px;
  font-weight: 600;
  line-height: 1.6;
  color: #344054;
  grid-template-columns: 14px minmax(0, 1fr);
  gap: 10px;
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
