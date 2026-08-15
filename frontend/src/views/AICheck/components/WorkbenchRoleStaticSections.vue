<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import {
  ElButton,
  ElCard,
  ElDescriptions,
  ElDescriptionsItem,
  ElEmpty,
  ElInput,
  ElOption,
  ElPagination,
  ElRadioButton,
  ElRadioGroup,
  ElSelect,
  ElTable,
  ElTableColumn,
  ElTag,
  ElTimeline,
  ElTimelineItem,
  ElTooltip
} from 'element-plus'
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
import AuditStatusTag, { type AuditStatusTone } from './AuditStatusTag.vue'
import AuditSummaryGrid, { type AuditSummaryCard } from './AuditSummaryGrid.vue'
import { documentBindingSummary } from '@/utils/acceptanceFlows'
import { documentBusinessStatus, type DocumentBusinessStatus } from '@/utils/documentPipelineStatus'
import { canRetryDocumentUpload, canSubmitDocumentUpload } from '@/utils/documentUploadActions'

type ReviewChainStep = {
  title: string
  desc: string
  tags: string[]
  result: string
}

type ContractorFileStatus = '全部' | '未关联' | '待提交' | '审核中' | '需补正' | '已通过' | '已作废'
type ContractorSortKey = 'updatedDesc' | 'updatedAsc' | 'status' | 'version'
type ElementTagType = 'primary' | 'success' | 'warning' | 'danger' | 'info'
type ContractorMaterialRequirement = {
  category: string
  requiredItems: string
  keywords: string[]
  uploadHint: string
}
type ContractorFileRow = {
  id: string
  documentId: string
  fileName: string
  materialCategory: string
  requirementName: string
  usage: string
  version: string
  status: Exclude<ContractorFileStatus, '全部'>
  sourceOrgName: string
  relationNode: string
  feedback: string
  ocr: string
  processingStatus: DocumentBusinessStatus
  uploader: string
  updatedAt: string
}

const props = defineProps<{
  role: RoleCode
  /** 从待办跳过来时要定位的节点。改变即触发一次定位。 */
  focusNode?: { id: number; name: string } | null
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
  'file-retry-upload': [documentId: string]
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

/* 待办跳转要**真的**把人带到那儿。
 *
 * 线上实测：点「去该节点处理」，提示弹出「已定位到待办对应的节点」，
 * 而页面首屏一字未变——施工方这个视图是文件库，压根不渲染节点包，
 * 后台把节点数据取回来了，用户看不见任何变化。
 * **系统声称做了一件它没做的事**，比什么都不做更糟：用户会以为自己看漏了。
 *
 * 施工方这边能按「审核环节」过滤，所以定位＝把节点名填进搜索框并滚过去；
 * 做不到的情况由调用方如实降级措辞，不再说「已定位」。
 */
const focusContractorNode = async (node: { id: number; name: string }) => {
  contractorStatusFilter.value = '全部'
  contractorUsageFilter.value = '全部用途'
  contractorKeyword.value = String(node.name || '').trim()
  contractorPage.value = 1
  await nextTick()
  document
    .querySelector('#contractor-file-list')
    ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  return contractorKeyword.value.length > 0
}

defineExpose({ focusContractorNode })

const contractorStatusFilter = ref<ContractorFileStatus>('全部')
const contractorUsageFilter = ref('全部用途')
const contractorKeyword = ref('')
const contractorSort = ref<ContractorSortKey>('updatedDesc')
const contractorPage = ref(1)
const contractorPageSize = 5

const contractorStatusOptions: ContractorFileStatus[] = [
  '全部',
  '未关联',
  '待提交',
  '审核中',
  '需补正',
  '已通过',
  '已作废'
]

const contractorMaterialRequirements: ContractorMaterialRequirement[] = [
  {
    category: '资质证照',
    requiredItems: '施工单位安装许可证、设计单位许可证或资质、焊工资格证、元件制造许可证及相关证明',
    keywords: ['许可证', '资质', '焊工', '制造许可', '许可资质'],
    uploadHint: '建议上传完整页面，清晰显示单位名称、许可范围、证书编号和有效期。'
  },
  {
    category: '设计资料',
    requiredItems:
      '图纸目录、设计说明、数据表、材料表、布置图、强度或应力计算书、设计变更及审批资料',
    keywords: ['设计', '图纸', '施工图', '说明书', '数据表', '特性表', '材料表', '计算书'],
    uploadHint: '建议按图号和版本归集，并保留图签、签字盖章页以及对应的变更记录。'
  },
  {
    category: '施工方案',
    requiredItems:
      '施工组织设计、进度计划、施工方案及审批、安全与技术交底、试压/泄漏/吹扫清洗专项方案',
    keywords: ['施工方案', '施工组织', '试压方案', '泄漏试验', '吹扫', '清洗方案'],
    uploadHint: '建议将正文、编制审核批准页及建设单位意见作为一套资料上传。'
  },
  {
    category: '材料证明与复验',
    requiredItems:
      '产品质量证明、出厂检验、制造监检或型式试验、到货验收、抽样复验、标志移植、材料代用资料',
    keywords: ['质量证明', '材质', '材料', '复验', '出厂检验', '验收', '标志移植', '材料代用'],
    uploadHint: '建议按材料类别、规格和批号归集；复印件应保留确认章，并能追溯到使用部位。'
  },
  {
    category: '安全附件与阀门',
    requiredItems: '阀门质量证明和试验记录、安全阀/爆破片/紧急切断阀产品资料、安装记录及校验资料',
    keywords: ['安全阀', '爆破片', '紧急切断', '阀门', '校验', '压力试验'],
    uploadHint: '建议资料清晰标注设备编号、规格参数、安装位置、试验或校验结论及签字日期。'
  },
  {
    category: '焊接资料',
    requiredItems:
      'WPS/PQR、焊材质量证明及烘干/领用/退库记录、组对记录、焊接记录、焊缝编号、外观检查、返修资料',
    keywords: ['焊接', '焊材', 'WPS', 'PQR', '焊缝', '返修', '组对'],
    uploadHint: '建议按焊缝编号成套整理，使焊工、工艺、焊材、检验和返修记录能够相互对应。'
  },
  {
    category: '热处理资料',
    requiredItems: '热处理工艺卡、工艺评定、仪表校验资料、热处理曲线、热处理报告、硬度报告',
    keywords: ['热处理', '硬度', '温控', '热电偶', '曲线'],
    uploadHint: '项目涉及热处理时，建议将工艺、设备仪表、过程曲线、结果报告和硬度记录成套上传。'
  },
  {
    category: '防腐保温资料',
    requiredItems: '防腐/保温材料质量证明、施工与验收记录、补口补伤记录、电火花检测、阴极保护资料',
    keywords: ['防腐', '保温', '涂料', '补口', '补伤', '电火花', '阴极保护'],
    uploadHint: '建议按管段或线路归集材料、施工、检测与验收资料，并注明材料批号和施工部位。'
  },
  {
    category: '安装交工资料',
    requiredItems:
      '元件进场检查、预制与安装记录、支吊架、膨胀装置、穿跨越、套管绝缘、单线图、静电接地、交工资料',
    keywords: [
      '交工',
      '安装记录',
      '预制',
      '支吊架',
      '膨胀',
      '穿跨越',
      '套管绝缘',
      '单线图',
      '元件检查',
      '接地'
    ],
    uploadHint: '建议按管线号或单线图整理过程记录，确保记录中的设备、管段和安装位置可对应。'
  },
  {
    category: '试验与吹扫资料',
    requiredItems: '压力表/温度仪表检定校准、耐压试验、泄漏试验、吹扫清洗方案与记录、现场确认资料',
    keywords: ['耐压', '压力表', '泄漏', '吹扫', '清洗', '试验记录', '试验报告'],
    uploadHint: '建议将方案、仪表校准、过程记录、结果签认和现场照片等按同一次试验成套上传。'
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

const ownerMetricCards = computed<AuditSummaryCard[]>(() =>
  visibleMetrics.value.slice(0, 4).map((metric) => ({
    label: metric.label,
    value: metric.value,
    hint: '授权项目只读数据',
    tone: metric.tone || 'blue'
  }))
)

const ownerTimelineItems = [
  {
    timestamp: '06-20',
    title: '首批资料上传',
    description: '施工方完成材料与焊接资料初次提交。',
    type: 'success' as const
  },
  {
    timestamp: '06-23',
    title: '检测资料提交',
    description: '无损检测机构提交检测记录与报告。',
    type: 'success' as const
  },
  {
    timestamp: '06-25',
    title: '监检退回材料补正',
    description: '材料节点存在炉批号差异说明缺失。',
    type: 'danger' as const
  },
  {
    timestamp: '06-30',
    title: '预计报告确认',
    description: '当前报告草稿处于监检复核中。',
    type: 'warning' as const
  }
]

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
  file: NodePackagePayload['projectFiles'][number]
): Exclude<ContractorFileStatus, '全部'> => {
  const fileStatus = file.fileStatus
  if (fileStatus === '已作废' || fileStatus === '已替换') return '已作废'
  return documentBindingSummary(file)
}

const bindingForProjectFile = (file: NodePackagePayload['projectFiles'][number]) =>
  file.primaryBinding ||
  file.bindings?.[0] ||
  bindings.value.find((item) => item.documentId === file.id)

const getRelationNodeText = (fileBindings?: typeof bindings.value) => {
  if (!fileBindings?.length) return '未关联审核环节'
  return fileBindings
    .map(
      (binding) => `${binding.nodeId}. ${binding.requirementName || props.node?.name || '审核环节'}`
    )
    .join('；')
}

const normalizeSearchText = (...parts: Array<string | undefined>) => parts.join(' ').toLowerCase()

const inferMaterialCategory = (text: string) => {
  const normalized = text.toLowerCase()
  return (
    contractorMaterialRequirements.find((item) =>
      item.keywords.some((keyword) => normalized.includes(keyword.toLowerCase()))
    )?.category || '其他资料'
  )
}

const rectificationIdForBinding = (bindingId?: string) => {
  if (!bindingId) return '--'
  return rectifications.value.find((item) => item.bindingIds?.includes(bindingId))?.id || '--'
}

const contractorFileRows = computed<ContractorFileRow[]>(() => {
  const rows = projectFiles.value.map((file) => {
    const binding = bindingForProjectFile(file)
    const status = mapContractorFileStatus(file)
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
      usage: binding?.usage || '--',
      version: binding?.versionNo || '--',
      status,
      sourceOrgName: file.sourceOrgName,
      relationNode: getRelationNodeText(file.bindings),
      feedback: binding?.bindingStatus === '需补正' ? rectificationIdForBinding(binding.id) : '--',
      ocr: file.currentOcrStatus,
      processingStatus: documentBusinessStatus(file),
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
    usage: binding.usage,
    version: binding.versionNo,
    status:
      binding.bindingStatus === '需补正'
        ? '需补正'
        : binding.bindingStatus === '草稿挂载'
          ? '待提交'
          : binding.bindingStatus === '已通过'
            ? '已通过'
            : '审核中',
    sourceOrgName: binding.sourceOrgName,
    relationNode: getRelationNodeText([binding]),
    feedback: binding.bindingStatus === '需补正' ? rectificationIdForBinding(binding.id) : '--',
    ocr: '--',
    processingStatus: '上传中',
    uploader: '--',
    updatedAt: binding.boundAt
  }))
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

const resetContractorFilePage = () => {
  contractorPage.value = 1
}

const getElementTagType = (value?: string): ElementTagType => {
  if (!value) return 'info'
  if (['通过', '满足', '完成', '覆盖', '归档', '成功'].some((keyword) => value.includes(keyword))) {
    return 'success'
  }
  if (['补正', '失败', '禁止', '风险', '作废'].some((keyword) => value.includes(keyword))) {
    return 'danger'
  }
  if (['待', '审核', '处理中', '排队', '上传中'].some((keyword) => value.includes(keyword))) {
    return 'warning'
  }
  return 'primary'
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

const canSubmitContractorFile = (file: ContractorFileRow) =>
  !props.readOnly &&
  canSubmitDocumentUpload(
    ['未关联', '待提交', '需补正'].includes(file.status),
    file.processingStatus
  )

const requestFileSubmit = (file: ContractorFileRow) => {
  if (canSubmitContractorFile(file)) {
    emit('file-submit', file.documentId)
  }
}

const requestFileRetryUpload = (file: ContractorFileRow) => {
  if (!props.readOnly && canRetryDocumentUpload(file.processingStatus)) {
    emit('file-retry-upload', file.documentId)
  }
}

const requestFileDelete = (file: ContractorFileRow) => {
  if (!props.readOnly && ['未关联', '待提交'].includes(file.status)) {
    emit('file-delete', file.documentId)
  }
}

const getContractorSubmitHint = (file: ContractorFileRow) => {
  if (props.readOnly) return '当前项目为只读状态，不能提交文件'
  // 「识别失败」和「上传失败」得分开说：前者重传没用，后者重传才有用。
  if (file.processingStatus === '识别失败')
    return '文件已上传，但 OCR 识别失败，暂不能作为可定位证据提交；请联系管理员重新识别或人工修正。'
  if (file.processingStatus !== '上传成功') return '文件上传处理成功后才可提交'
  if (file.status === '未关联') return '提交到项目资料池，供监检处理（可不关联审核环节）'
  return ['待提交', '需补正'].includes(file.status)
    ? '提交当前文件的全部待提交或待补正挂载'
    : '当前状态不能重复提交'
}

const getContractorDeleteHint = (file: ContractorFileRow) => {
  if (props.readOnly) return '当前项目为只读状态，不能删除文件'
  return ['未关联', '待提交'].includes(file.status)
    ? '删除未提交文件'
    : '文件已提交审核，不能直接删除'
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

const getPillClass = (value?: string): AuditStatusTone => {
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
      <ElCard class="role-section-card contractor-section-card" shadow="never">
        <template #header>
          <div class="card-head">
            <div>
              <h2>一、项目文件库 / 施工资料台账</h2>
            </div>
            <div class="file-library-head-actions">
              <AuditStatusTag tone="blue">
                {{ filteredContractorFileRows.length }} / {{ contractorFileRows.length }} 个文件
              </AuditStatusTag>
            </div>
          </div>
        </template>
        <div class="card-body">
          <div class="material-checklist">
            <div class="material-checklist-head">
              <div>
                <h4>资料分类与上传指引</h4>
                <p>按资料用途选择分类，并参考提示成套上传；分类仅用于资料整理和上传参考。</p>
              </div>
            </div>
            <ElTable
              class="material-gap-table"
              :data="contractorMaterialRequirements"
              row-key="category"
              empty-text="暂无资料分类指引"
            >
              <ElTableColumn type="index" label="序号" width="64" align="center" />
              <ElTableColumn prop="category" label="资料类别" width="150" />
              <ElTableColumn label="操作" width="96">
                <template #default="{ row }">
                  <ElButton
                    link
                    type="primary"
                    :disabled="readOnly"
                    @click="requestUpload(row.category)"
                  >
                    上传资料
                  </ElButton>
                </template>
              </ElTableColumn>
              <ElTableColumn
                prop="requiredItems"
                label="建议包含资料"
                min-width="360"
                show-overflow-tooltip
              />
              <ElTableColumn
                prop="uploadHint"
                label="上传提示"
                min-width="320"
                show-overflow-tooltip
              />
            </ElTable>
          </div>

          <div class="file-library-tools">
            <ElRadioGroup
              v-model="contractorStatusFilter"
              class="status-filter-row"
              aria-label="文件状态筛选"
              @change="resetContractorFilePage"
            >
              <ElRadioButton
                v-for="status in contractorStatusOptions"
                :key="status"
                :value="status"
              >
                {{ status }} {{ contractorStatusCounts[status] }}
              </ElRadioButton>
            </ElRadioGroup>
            <div id="contractor-file-list" class="filter-row">
              <ElInput
                v-model="contractorKeyword"
                class="filter-input"
                clearable
                placeholder="搜索文件名、资料类别、资料项、来源单位、审核环节或反馈编号"
                aria-label="搜索项目文件"
                @update:model-value="resetContractorFilePage"
              />
              <ElSelect
                v-model="contractorMaterialFilter"
                class="filter-select"
                aria-label="资料类别筛选"
                @change="resetContractorFilePage"
              >
                <ElOption
                  v-for="material in contractorMaterialOptions"
                  :key="material"
                  :label="material"
                  :value="material"
                />
              </ElSelect>
              <ElSelect
                v-model="contractorUsageFilter"
                class="filter-select"
                aria-label="文件用途筛选"
                @change="resetContractorFilePage"
              >
                <ElOption
                  v-for="usage in contractorUsageOptions"
                  :key="usage"
                  :label="usage"
                  :value="usage"
                />
              </ElSelect>
              <ElSelect
                v-model="contractorSort"
                class="filter-select"
                aria-label="文件排序方式"
                @change="resetContractorFilePage"
              >
                <ElOption label="更新时间从新到旧" value="updatedDesc" />
                <ElOption label="更新时间从旧到新" value="updatedAsc" />
                <ElOption label="按状态排序" value="status" />
                <ElOption label="按版本排序" value="version" />
              </ElSelect>
            </div>
          </div>

          <ElTable
            class="contractor-files-table"
            :data="pagedContractorFileRows"
            row-key="id"
            empty-text="当前筛选条件下暂无文件"
          >
            <ElTableColumn label="序号" width="64" align="center">
              <template #default="{ $index }">
                {{ (normalizedContractorPage - 1) * contractorPageSize + $index + 1 }}
              </template>
            </ElTableColumn>
            <ElTableColumn prop="fileName" label="文件名" min-width="220" show-overflow-tooltip />
            <ElTableColumn
              prop="materialCategory"
              label="资料类别"
              min-width="130"
              show-overflow-tooltip
            />
            <ElTableColumn prop="uploader" label="上传人" width="112" />
            <ElTableColumn prop="updatedAt" label="更新时间" width="176" />
            <ElTableColumn
              prop="sourceOrgName"
              label="来源单位"
              min-width="150"
              show-overflow-tooltip
            />
            <ElTableColumn label="状态" width="96">
              <template #default="{ row }">
                <ElTag :type="getElementTagType(row.status)" effect="light">
                  {{ row.status }}
                </ElTag>
              </template>
            </ElTableColumn>
            <ElTableColumn label="处理状态" width="116">
              <template #default="{ row }">
                <ElButton
                  v-if="canRetryDocumentUpload(row.processingStatus)"
                  link
                  type="danger"
                  :disabled="readOnly"
                  @click="requestFileRetryUpload(row)"
                >
                  失败重新上传
                </ElButton>
                <ElTag v-else :type="getElementTagType(row.processingStatus)" effect="plain">
                  {{ row.processingStatus }}
                </ElTag>
              </template>
            </ElTableColumn>
            <ElTableColumn prop="version" label="版本" width="86" />
            <ElTableColumn
              prop="relationNode"
              label="关联审核环节"
              min-width="180"
              show-overflow-tooltip
            />
            <ElTableColumn prop="feedback" label="关联反馈" min-width="120" />
            <ElTableColumn
              prop="requirementName"
              label="资料项"
              min-width="180"
              show-overflow-tooltip
            />
            <ElTableColumn prop="usage" label="文件用途" min-width="130" show-overflow-tooltip />
            <ElTableColumn label="操作" width="220" fixed="right">
              <template #default="{ row }">
                <div class="table-actions">
                  <ElButton link type="primary" @click="requestFileView(row)">查看</ElButton>
                  <ElTooltip
                    :content="getContractorSubmitHint(row)"
                    :disabled="canSubmitContractorFile(row)"
                    placement="top"
                    popper-class="audit-action-tooltip-popper"
                  >
                    <span class="table-action-tooltip">
                      <ElButton
                        link
                        type="primary"
                        :disabled="!canSubmitContractorFile(row)"
                        @click="requestFileSubmit(row)"
                      >
                        提交
                      </ElButton>
                    </span>
                  </ElTooltip>
                  <ElTooltip
                    :content="getContractorDeleteHint(row)"
                    :disabled="!readOnly && ['未关联', '待提交'].includes(row.status)"
                    placement="top"
                    popper-class="audit-action-tooltip-popper"
                  >
                    <span class="table-action-tooltip">
                      <ElButton
                        link
                        type="danger"
                        :disabled="readOnly || !['未关联', '待提交'].includes(row.status)"
                        @click="requestFileDelete(row)"
                      >
                        删除
                      </ElButton>
                    </span>
                  </ElTooltip>
                  <ElButton link type="primary" :disabled="readOnly" @click="requestFileBind(row)">
                    选择环节
                  </ElButton>
                </div>
              </template>
            </ElTableColumn>
            <template #empty>
              <ElEmpty :image-size="64" description="当前筛选条件下暂无文件" />
            </template>
          </ElTable>

          <ElPagination
            v-model:current-page="contractorPage"
            class="contractor-pagination"
            :page-size="contractorPageSize"
            :total="filteredContractorFileRows.length"
            layout="total, prev, pager, next"
            background
            small
          />
        </div>
      </ElCard>

      <ElCard
        id="contractor-feedback-list"
        class="role-section-card contractor-section-card"
        shadow="never"
      >
        <template #header>
          <div class="card-head">
            <div>
              <h2>二、审核反馈列表</h2>
              <div class="sub"
                >按监检退回补正意见逐项反馈，可上传新文件或关联项目文件库中的已有文件。</div
              >
            </div>
            <AuditStatusTag
              :tone="
                contractorFeedbackRows.some((item) => item.status !== '已关闭') ? 'orange' : 'green'
              "
            >
              {{ contractorFeedbackRows.filter((item) => item.status !== '已关闭').length }}
              项待处理
            </AuditStatusTag>
          </div>
        </template>
        <div class="card-body">
          <ElTable
            class="contractor-feedback-table"
            :data="contractorFeedbackRows"
            row-key="id"
            empty-text="暂无审核反馈"
          >
            <ElTableColumn prop="id" label="反馈编号" width="160" />
            <ElTableColumn prop="node" label="问题环节" min-width="170" show-overflow-tooltip />
            <ElTableColumn label="问题说明" min-width="300">
              <template #default="{ row }">
                <strong>{{ row.issue }}</strong>
                <div class="table-note">{{ row.requirement }}</div>
              </template>
            </ElTableColumn>
            <ElTableColumn label="反馈状态" width="104">
              <template #default="{ row }">
                <ElTag :type="getElementTagType(row.status)" effect="light">
                  {{ row.status }}
                </ElTag>
              </template>
            </ElTableColumn>
            <ElTableColumn label="关联文件" width="96">
              <template #default="{ row }">{{ row.linkedFiles }} 个</template>
            </ElTableColumn>
            <ElTableColumn prop="feedbackAt" label="反馈时间" width="176" />
            <ElTableColumn prop="dueAt" label="截止要求" width="150" />
            <ElTableColumn label="操作" width="220" fixed="right">
              <template #default="{ row }">
                <div class="table-actions">
                  <ElButton link type="primary" :disabled="readOnly" @click="requestUpload()">
                    上传补正
                  </ElButton>
                  <ElButton link type="primary" :disabled="readOnly" @click="requestBind">
                    关联文件
                  </ElButton>
                  <ElButton
                    link
                    type="primary"
                    :disabled="readOnly"
                    @click="requestRectify(row.rectificationId)"
                  >
                    提交反馈
                  </ElButton>
                </div>
              </template>
            </ElTableColumn>
            <template #empty>
              <ElEmpty :image-size="64" description="暂无审核反馈" />
            </template>
          </ElTable>
        </div>
      </ElCard>
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
                <td><span class="muted-action">查看/替换暂未开放</span></td>
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
              <strong>上传检测报告、底片清单或图像包</strong>
              <span class="sub">上传后选择无损检测节点：40、41、42、65</span>
              <ElButton type="primary" :disabled="readOnly" @click="requestUpload('无损检测资料')">
                选择文件
              </ElButton>
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
      <ElCard class="role-section-card" shadow="never">
        <template #header>
          <div class="card-head">
            <div>
              <h2>一、项目基础信息</h2>
              <div class="sub">集中查看授权项目的核心指标，不提供业务办理入口</div>
            </div>
            <AuditStatusTag tone="green" round>只读模式</AuditStatusTag>
          </div>
        </template>
        <AuditSummaryGrid
          class="owner-summary-grid"
          :cards="ownerMetricCards"
          aria-label="建设单位项目基础指标"
        />
      </ElCard>

      <ElCard class="role-section-card role-section-card--table" shadow="never">
        <template #header>
          <div class="card-head">
            <div>
              <h2>二、节点状态总览</h2>
              <div class="sub">展示授权可见的节点资料摘要，不提供办理入口</div>
            </div>
          </div>
        </template>
        <ElTable :data="ownerNodeRows" row-key="node" empty-text="当前没有可查看的节点">
          <ElTableColumn prop="group" label="业务大类" min-width="132" show-overflow-tooltip />
          <ElTableColumn prop="node" label="检测节点" min-width="190" show-overflow-tooltip />
          <ElTableColumn label="资料状态" width="112">
            <template #default="{ row }">
              <AuditStatusTag :tone="getPillClass(row.fileStatus)" round>
                {{ row.fileStatus }}
              </AuditStatusTag>
            </template>
          </ElTableColumn>
          <ElTableColumn prop="reviewStatus" label="审查状态" width="116" />
          <ElTableColumn prop="files" label="挂载资料数" width="110" align="center" />
          <ElTableColumn prop="warnings" label="异常数量" width="96" align="center" />
          <ElTableColumn
            prop="updatedAt"
            label="最近更新时间"
            min-width="170"
            show-overflow-tooltip
          />
        </ElTable>
      </ElCard>

      <ElCard class="role-section-card role-section-card--table" shadow="never">
        <template #header>
          <div class="card-head">
            <div>
              <h2>三、业务审查链路只读摘要</h2>
              <div class="sub">建设方仅查看状态和摘要，不显示办理按钮</div>
            </div>
          </div>
        </template>
        <ElTable :data="reviewSteps" row-key="title" empty-text="当前没有审查链路记录">
          <ElTableColumn label="检测节点" min-width="176" show-overflow-tooltip>
            <template #default>{{ currentNodeLabel }}</template>
          </ElTableColumn>
          <ElTableColumn prop="title" label="审查对象" min-width="150" show-overflow-tooltip />
          <ElTableColumn prop="desc" label="业务链路摘要" min-width="280" show-overflow-tooltip />
          <ElTableColumn label="建议/状态" width="112">
            <template #default="{ row }">
              <AuditStatusTag :tone="getPillClass(row.result)" round>
                {{ row.result }}
              </AuditStatusTag>
            </template>
          </ElTableColumn>
          <ElTableColumn label="人工确认" min-width="150">
            <template #default="{ row }">
              {{ row.result.includes('需') ? '已退回责任单位' : '待监检确认' }}
            </template>
          </ElTableColumn>
        </ElTable>
      </ElCard>

      <div class="split">
        <ElCard class="role-section-card" shadow="never">
          <template #header>
            <div class="card-head"><h2>四、关键时间线</h2></div>
          </template>
          <ElTimeline class="owner-timeline">
            <ElTimelineItem
              v-for="item in ownerTimelineItems"
              :key="`${item.timestamp}-${item.title}`"
              :timestamp="item.timestamp"
              :type="item.type"
              placement="top"
            >
              <strong>{{ item.title }}</strong>
              <p>{{ item.description }}</p>
            </ElTimelineItem>
          </ElTimeline>
        </ElCard>
        <ElCard class="role-section-card" shadow="never">
          <template #header>
            <div class="card-head"><h2>五、报告与归档状态</h2></div>
          </template>
          <ElDescriptions class="owner-status-descriptions" :column="1" size="small">
            <ElDescriptionsItem label="监检报告">
              <span class="owner-status-row">
                <span>{{ latestReport?.title || '工业管道施工监督检验报告 V0.8' }}</span>
                <AuditStatusTag :tone="getPillClass(latestReport?.status || '复核中')" round>
                  {{ latestReport?.status || '复核中' }}
                </AuditStatusTag>
              </span>
            </ElDescriptionsItem>
            <ElDescriptionsItem label="过程资料包">
              <span class="owner-status-row">
                <span>{{ latestArchive?.name || '待报告确认后生成归档包' }}</span>
                <AuditStatusTag :tone="getPillClass(latestArchive?.status || '待生成')" round>
                  {{ latestArchive?.status || '待生成' }}
                </AuditStatusTag>
              </span>
            </ElDescriptionsItem>
            <ElDescriptionsItem label="最近异常">
              <span class="owner-status-row">
                <span>材料节点需补正、现场抽查照片需补正</span>
                <AuditStatusTag tone="red" round>2 项</AuditStatusTag>
              </span>
            </ElDescriptionsItem>
            <ElDescriptionsItem label="查看权限">
              <span class="owner-status-row">
                <span>仅可查看授权项目资料摘要和报告预览</span>
                <AuditStatusTag tone="green" round>只读</AuditStatusTag>
              </span>
            </ElDescriptionsItem>
          </ElDescriptions>
        </ElCard>
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
                <td><span class="muted-action">证据定位暂未开放</span></td>
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

.role-section-card {
  margin-bottom: 12px;
  border: 0;
  border-radius: 8px;
  box-shadow: 0 8px 20px rgb(15 23 42 / 7%);
}

.role-section-card :deep(.el-card__header) {
  padding: 0;
  border-bottom: 1px solid var(--line-soft);
}

.role-section-card :deep(.el-card__body) {
  padding: 14px 16px;
}

.role-section-card--table :deep(.el-card__body) {
  padding-top: 8px;
}

.contractor-section-card :deep(.el-card__body) {
  padding: 0;
}

.role-section-card .card-head {
  border-bottom: 0;
}

.owner-summary-grid {
  --audit-summary-columns: 3;

  margin-bottom: 0;
}

.owner-timeline {
  padding: 4px 4px 0;
}

.owner-timeline :deep(.el-timeline-item__timestamp) {
  font-size: 12px;
  font-weight: 600;
  color: var(--muted);
}

.owner-timeline strong {
  font-size: 14px;
  color: #27364d;
}

.owner-timeline p {
  margin-top: 4px;
  font-size: 13px;
  font-weight: 500;
  color: var(--muted);
}

.owner-status-descriptions :deep(.el-descriptions__cell) {
  padding-bottom: 12px;
}

.owner-status-descriptions :deep(.el-descriptions__label) {
  width: 84px;
  font-weight: 600;
  color: var(--muted);
}

.owner-status-row {
  display: flex;
  min-width: 0;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
}

.owner-status-row > span:first-child {
  min-width: 0;
  overflow-wrap: anywhere;
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
  width: 100%;
}

.material-gap-table {
  width: 100%;
}

.contractor-files-table {
  width: 100%;
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
  gap: 12px;
  min-height: 128px;
  padding: 22px;
  font-size: 18px;
  font-weight: 600;
  color: #37506f;
  text-align: center;
  background: #f8fbff;
  border: 1px dashed #9db8df;
  border-radius: 6px;
  place-items: center;
}

.upload-box .sub {
  font-size: 14px;
  font-weight: 600;
  color: var(--muted);
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
.table-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.table-action-tooltip {
  display: inline-flex;
}

.table-action-tooltip :deep(.el-button) {
  margin-left: 0;
}

.filter-row {
  justify-content: space-between;
}

.filter-input,
.filter-select {
  min-height: 34px;
}

.filter-input {
  flex: 1 1 320px;
  min-width: 240px;
}

.filter-select {
  flex: 0 1 210px;
}

.status-filter-row :deep(.el-radio-button__inner) {
  min-height: 34px;
  padding: 8px 12px;
  font-size: 13px;
}

.contractor-pagination {
  justify-content: flex-end;
  margin-top: 12px;
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

.muted-action {
  font-size: 13px;
  font-weight: 600;
  color: var(--muted);
}

@media (width <= 900px) {
  .split {
    grid-template-columns: minmax(0, 1fr);
  }

  .role-section-card :deep(.el-card__body) {
    padding: 12px;
  }

  .owner-status-row {
    gap: 6px;
    align-items: flex-start;
    flex-direction: column;
  }
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
