import type {
  AiReviewRun,
  DocumentAsset,
  DocumentVersion,
  EvidenceLink,
  ExtractedField,
  MessageItem,
  NdtFeedback,
  NdtFilm,
  NdtReport,
  NodeDocumentRequirement,
  NodeFileBinding,
  Project,
  ProjectTreeNode,
  ArchiveItem,
  ReportVersion,
  ReviewOpinion,
  RoleCode,
  TodoItem
} from '../../src/types/aicheck'

export const projectId = 'P-2026-HDCP-001'

export const projects: Project[] = [
  {
    id: projectId,
    code: projectId,
    name: '华东成品油管道改造工程',
    type: '工业管道改造',
    region: '华东',
    ownerOrgName: '华东管网建设公司',
    contractorOrgName: '中石化安装有限公司',
    ndtOrgName: '华测检测有限公司',
    inspectionOrgName: '省特检院一部',
    status: '监检审查中',
    todoCount: 12,
    messageCount: 7,
    currentNodeId: 24,
    updatedAt: '2026-06-26 09:30:00',
    actions: ['project:view', 'file:upload', 'file:bind', 'review:save', 'ai:recheck']
  },
  {
    id: 'P-2026-GDLNG-002',
    code: 'P-2026-GDLNG-002',
    name: '广东 LNG 支线改造工程',
    type: '燃气管道扩建',
    region: '华南',
    ownerOrgName: '南方能源管网公司',
    contractorOrgName: '粤海安装工程有限公司',
    ndtOrgName: '粤检无损检测',
    inspectionOrgName: '省特检院三部',
    status: '退回补正中',
    todoCount: 9,
    messageCount: 4,
    currentNodeId: 16,
    updatedAt: '2026-06-26 11:10:00',
    actions: ['project:view', 'rectification:submit']
  },
  {
    id: 'P-2026-SXCHEM-003',
    code: 'P-2026-SXCHEM-003',
    name: '山西化工园区蒸汽管道工程',
    type: '蒸汽管道新建',
    region: '华北',
    ownerOrgName: '晋北化工园区管委会',
    contractorOrgName: '山西建工管道分公司',
    ndtOrgName: '中科检测',
    inspectionOrgName: '省特检院二部',
    status: 'AI 预审中',
    todoCount: 6,
    messageCount: 2,
    currentNodeId: 59,
    updatedAt: '2026-06-25 17:45:00',
    actions: ['project:view']
  },
  {
    id: 'P-2026-HZCHEM-004',
    code: 'P-2026-HZCHEM-004',
    name: '杭州精细化工蒸汽外管工程',
    type: '蒸汽管道改造',
    region: '华东',
    ownerOrgName: '钱塘化工园区建设公司',
    contractorOrgName: '浙江省工业设备安装集团',
    ndtOrgName: '浙检无损检测',
    inspectionOrgName: '省特检院一部',
    status: '资料提交中',
    todoCount: 5,
    messageCount: 3,
    currentNodeId: 12,
    updatedAt: '2026-06-26 08:20:00',
    actions: ['project:view', 'file:upload', 'file:bind']
  },
  {
    id: 'P-2026-BJHEAT-005',
    code: 'P-2026-BJHEAT-005',
    name: '北京城市热网支线更新工程',
    type: '热力管道更新',
    region: '华北',
    ownerOrgName: '北方热力集团',
    contractorOrgName: '北京城建安装公司',
    ndtOrgName: '华北无损检测中心',
    inspectionOrgName: '市特检院管道室',
    status: '报告生成/复核中',
    todoCount: 3,
    messageCount: 5,
    currentNodeId: 62,
    updatedAt: '2026-06-26 12:05:00',
    actions: ['project:view', 'report:view']
  },
  {
    id: 'P-2026-SZLNG-006',
    code: 'P-2026-SZLNG-006',
    name: '深圳 LNG 应急调峰站联络线',
    type: '燃气管道新建',
    region: '华南',
    ownerOrgName: '鹏城能源建设公司',
    contractorOrgName: '深圳燃气工程有限公司',
    ndtOrgName: '南检无损检测',
    inspectionOrgName: '省特检院四部',
    status: '草稿/立项中',
    todoCount: 2,
    messageCount: 1,
    currentNodeId: 1,
    updatedAt: '2026-06-24 16:30:00',
    actions: ['project:view', 'project:authorize-member']
  },
  {
    id: 'P-2025-CQARCH-007',
    code: 'P-2025-CQARCH-007',
    name: '重庆老厂酸碱管线整改工程',
    type: '工业管道整改',
    region: '西南',
    ownerOrgName: '渝江化工资产公司',
    contractorOrgName: '重庆工业设备安装公司',
    ndtOrgName: '西南无损检测',
    inspectionOrgName: '市特检院二部',
    status: '已归档',
    todoCount: 0,
    messageCount: 2,
    currentNodeId: 68,
    updatedAt: '2026-06-18 15:40:00',
    actions: ['project:view', 'archive:view', 'archive:download']
  },
  {
    id: 'P-2025-NJARCH-018',
    code: 'P-2025-NJARCH-018',
    name: '南京老厂区管廊改造工程',
    type: '综合管廊改造',
    region: '华东',
    ownerOrgName: '南京工业资产运营公司',
    contractorOrgName: '江北设备安装有限公司',
    ndtOrgName: '金陵检测',
    inspectionOrgName: '省特检院一部',
    status: '已归档',
    todoCount: 0,
    messageCount: 1,
    currentNodeId: 68,
    updatedAt: '2026-06-20 15:00:00',
    actions: ['project:view']
  }
]

const groupDefinitions: Array<{
  name: string
  nodes: Array<[number, string, ProjectTreeNode['inspectionType']]>
}> = [
  {
    name: '受检单位资质',
    nodes: [
      [1, '设计单位许可资质', 'C'],
      [2, '施工单位许可资质', 'C'],
      [3, '无损检测机构核准资质', 'C']
    ]
  },
  {
    name: '设计文件',
    nodes: [
      [4, '设计文件的批准程序', 'C'],
      [5, '施工图审查手续', 'C'],
      [6, '强度计算书、管道应力分析计算书的审批手续', 'C'],
      [7, '设计变更的书面批准文件', 'C'],
      [8, '设计采用的安全技术规范以及相关标准、压力管道元件的材料标准的版本', 'C'],
      [9, '设计文件上注明的无损检测、防腐、耐压试验和泄漏试验要求', 'C'],
      [10, '采用其他标准时的符合性申明及比照表', '需确认']
    ]
  },
  { name: '施工组织设计', nodes: [[11, '施工组织设计', 'C']] },
  {
    name: '材料',
    nodes: [
      [12, '压力管道元件及安全附件制造单位的许可资质', 'C'],
      [13, '需制造监检或有型式试验要求的压力管道元件的监检证书、型式试验报告', 'C'],
      [14, '不需制造许可、监检、型式试验的管道组成件的出厂检验报告', 'C/B'],
      [15, '境外制造的压力管道元件、安全附件的型式试验证书及制造许可证资质', 'C'],
      [16, '压力管道元件以及安全附件产品质量证明文件', 'C'],
      [17, '压力管道元件以及安全附件产品验收的见证资料、抽样复验', 'C'],
      [18, '材料复验报告、无损检测报告', 'C'],
      [19, '使用境外牌号材料制造的压力管道元件以及安全附件，验证性复验结果', 'C'],
      [20, '新材料制造的压力管道元件以及安全附件的型式试验报告、技术评审、批准手续', 'C'],
      [21, '材料标志移植', 'B'],
      [22, '材料代用', 'C']
    ]
  },
  { name: '阀门', nodes: [[23, '阀门的施工资料和耐压试验记录（报告）', 'C']] },
  {
    name: '焊接（粘接）',
    nodes: [
      [24, '焊工资格证及持证合格项目', 'B'],
      [25, '焊接（粘接）工艺文件', 'C'],
      [26, '焊接材料质量证明文件', 'C'],
      [27, '焊接材料的验收、保管、发放、使用和回收的管理', 'B'],
      [28, '管道组对', 'C'],
      [29, '施焊参数、施焊记录、焊缝标识', 'B'],
      [30, '焊接接头外观质量', 'B'],
      [31, '焊缝返修', 'C']
    ]
  },
  {
    name: '热处理',
    nodes: [
      [32, '焊接接头焊后热处理工艺文件', 'C'],
      [33, '热处理设备用测温记录仪表', 'C'],
      [34, '热处理记录、报告曲线、硬度检测报告', 'C']
    ]
  },
  {
    name: '无损检测',
    nodes: [
      [35, '无损检测机构施工现场质量保证体系的实施', 'B'],
      [36, '无损检测方案', 'C'],
      [37, '检测过程中发现问题的处理', 'C'],
      [38, '无损检测人员资格证、执业注册证及持证合格项目', 'B'],
      [39, '无损检测工艺文件', 'C'],
      [40, '无损检测记录、报告', 'C'],
      [41, '射线检测底片抽查', 'B'],
      [42, '射线检测现场抽查', 'B']
    ]
  },
  {
    name: '防腐、保温',
    nodes: [
      [43, '防腐及保温材料质量证明文件', 'C'],
      [44, '防腐、补口、补伤及保温', 'C'],
      [45, '防腐层电火花检测', 'C'],
      [46, '牺牲阳极、外加电流阴极保护、杂散电流排流装置', 'C'],
      [47, '静电接地', 'C']
    ]
  },
  {
    name: '穿跨越工程',
    nodes: [
      [48, '穿跨越工程的管道结构、焊缝布置', 'C'],
      [49, '穿跨越工程施工', 'C'],
      [50, '套管防腐绝缘', 'C'],
      [51, '绝缘支撑', 'C']
    ]
  },
  { name: '管道现场制作（预制）', nodes: [[52, '管道现场制作（预制）', 'B']] },
  {
    name: '管道安装',
    nodes: [
      [53, '管道布管与连接方式、穿跨越', 'C/B'],
      [54, '补偿装置', 'C/B'],
      [55, '支撑件', 'C/B']
    ]
  },
  {
    name: '安全附件',
    nodes: [
      [56, '安全阀、爆破片和紧急切断阀的安装位置、规格和型号', 'B'],
      [57, '安全阀校验报告', 'C'],
      [58, '紧急切断阀性能测试报告', 'C']
    ]
  },
  {
    name: '耐压试验',
    nodes: [
      [59, '耐压试验方案', 'A'],
      [60, '试验用压力表、试验介质、介质温度、环境温度', 'A'],
      [61, '耐压试验压力、保压时间及结果', 'A'],
      [62, '耐压试验记录（报告）', 'A']
    ]
  },
  {
    name: '耐压试验免除或替代',
    nodes: [
      [63, '管道系统的柔性(应力)分析', 'A'],
      [64, '现场检查替代性试验的过程', 'A'],
      [65, '无损检测报告和底片', 'A']
    ]
  },
  {
    name: '泄漏试验',
    nodes: [
      [66, '试验用压力表、试验介质、介质温度、环境温度、试验压力', 'B'],
      [67, '泄漏试验方法和试验报告', 'C']
    ]
  },
  { name: '吹扫、清洗', nodes: [[68, '吹扫、清洗', 'C']] },
  {
    name: '施工单位质量保证体系实施状况的评价',
    nodes: [[69, '施工单位质量保证体系实施状况的评价', '需确认']]
  }
]

export const treeNodes: ProjectTreeNode[] = groupDefinitions.flatMap((group) =>
  group.nodes.map(([nodeId, name, inspectionType]) => ({
    id: `${projectId}-${nodeId}`,
    projectId,
    nodeId,
    code: String(nodeId).padStart(2, '0'),
    name,
    groupName: group.name,
    inspectionType,
    status:
      nodeId === 16 ? '需补正' : nodeId === 24 ? '待人工确认' : nodeId === 40 ? '待审查' : '待提交',
    fileCount: [16, 24, 40].includes(nodeId) ? 4 : nodeId % 5,
    requiredProgress: { done: [16, 24, 40].includes(nodeId) ? 4 : nodeId % 3, total: 5 },
    actions: ['project:view', 'file:bind']
  }))
)

export const requirements: NodeDocumentRequirement[] = [
  { id: 'REQ-16-01', nodeId: 16, name: '产品质量证明书', requiredType: '必传' },
  { id: 'REQ-16-02', nodeId: 16, name: '材料复验报告', requiredType: '条件必传' },
  { id: 'REQ-24-01', nodeId: 24, name: '焊工资格证', requiredType: '必传' },
  { id: 'REQ-24-02', nodeId: 24, name: '焊工名册', requiredType: '必传' },
  { id: 'REQ-24-03', nodeId: 24, name: '外部查询截图', requiredType: '条件必传' },
  { id: 'REQ-40-01', nodeId: 40, name: '无损检测报告', requiredType: '必传' }
]

export const documents: DocumentAsset[] = [
  {
    id: 'DOC-20260625-001',
    projectId,
    fileName: '焊工资格证-王建国.pdf',
    fileType: 'pdf',
    sourceOrgName: '中石化安装有限公司',
    uploaderName: '李工',
    currentVersionId: 'DV-20260625-001-V2',
    fileStatus: '已上传',
    currentOcrStatus: '已识别',
    updatedAt: '2026-06-25 10:30:00',
    actions: ['file:view', 'file:bind', 'file:preview', 'file:download']
  },
  {
    id: 'DOC-20260625-002',
    projectId,
    fileName: '焊工名册.xlsx',
    fileType: 'xlsx',
    sourceOrgName: '中石化安装有限公司',
    uploaderName: '李工',
    currentVersionId: 'DV-20260625-002-V1',
    fileStatus: '已上传',
    currentOcrStatus: '已识别',
    updatedAt: '2026-06-25 10:40:00',
    actions: ['file:view', 'file:bind', 'file:preview', 'file:download']
  },
  {
    id: 'DOC-20260625-003',
    projectId,
    fileName: '钢管质量证明书.pdf',
    fileType: 'pdf',
    sourceOrgName: '中石化安装有限公司',
    uploaderName: '李工',
    currentVersionId: 'DV-20260625-003-V2',
    fileStatus: '已上传',
    currentOcrStatus: '人工修正',
    updatedAt: '2026-06-25 11:20:00',
    actions: ['file:view', 'file:bind', 'file:preview', 'file:download']
  },
  {
    id: 'DOC-20260625-004',
    projectId,
    fileName: 'RT检测报告R2.pdf',
    fileType: 'pdf',
    sourceOrgName: '华测检测有限公司',
    uploaderName: '王工',
    currentVersionId: 'DV-20260625-004-V1',
    fileStatus: '已上传',
    currentOcrStatus: '识别中',
    updatedAt: '2026-06-25 14:10:00',
    actions: ['file:view', 'file:bind', 'file:preview', 'file:download']
  }
]

export const versions: DocumentVersion[] = documents.map((document) => ({
  id: document.currentVersionId,
  documentId: document.id,
  versionNo: document.currentVersionId.endsWith('V2') ? 'V2' : 'V1',
  hash: 'mock-sha256-' + document.id,
  fileSize: 245760,
  uploaderName: document.uploaderName,
  uploadTime: document.updatedAt,
  isCurrent: true
}))

export const bindings: NodeFileBinding[] = [
  {
    id: 'BIND-24-001',
    projectId,
    nodeId: 24,
    requirementId: 'REQ-24-01',
    requirementName: '焊工资格证',
    documentId: 'DOC-20260625-001',
    documentVersionId: 'DV-20260625-001-V2',
    fileName: '焊工资格证-王建国.pdf',
    versionNo: 'V2',
    usage: '原始提交',
    sourceOrgName: '中石化安装有限公司',
    bindingStatus: '已提交',
    boundAt: '2026-06-25 10:45:00',
    actions: ['review:save', 'review:return-correction']
  },
  {
    id: 'BIND-16-001',
    projectId,
    nodeId: 16,
    requirementId: 'REQ-16-01',
    requirementName: '产品质量证明书',
    documentId: 'DOC-20260625-003',
    documentVersionId: 'DV-20260625-003-V2',
    fileName: '钢管质量证明书.pdf',
    versionNo: 'V2',
    usage: '补正附件',
    sourceOrgName: '中石化安装有限公司',
    bindingStatus: '需补正',
    boundAt: '2026-06-25 11:30:00',
    actions: ['rectification:submit']
  },
  {
    id: 'BIND-40-001',
    projectId,
    nodeId: 40,
    requirementId: 'REQ-40-01',
    requirementName: '无损检测报告',
    documentId: 'DOC-20260625-004',
    documentVersionId: 'DV-20260625-004-V1',
    fileName: 'RT检测报告R2.pdf',
    versionNo: 'V1',
    usage: '检测报告',
    sourceOrgName: '华测检测有限公司',
    bindingStatus: '已提交',
    boundAt: '2026-06-25 14:30:00',
    actions: ['ndt:submit']
  }
]

export const evidenceLinks: EvidenceLink[] = [
  {
    id: 'EV-24-001',
    objectType: 'documentVersion',
    objectId: 'DV-20260625-001-V2',
    fileName: '焊工资格证-王建国.pdf',
    pageNo: 1,
    fieldName: '证书编号',
    quotedText: 'TS6J-2024-03158',
    confidence: 0.96
  },
  {
    id: 'EV-24-002',
    objectType: 'knowledgeClause',
    objectId: 'TSG-Z6002-3.2',
    quotedText: '焊工持证项目应覆盖实际焊接方法。',
    confidence: 0.92
  },
  {
    id: 'EV-16-001',
    objectType: 'extractedField',
    objectId: 'FIELD-16-001',
    fileName: '钢管质量证明书.pdf',
    pageNo: 1,
    fieldName: '炉批号',
    quotedText: 'H240315A07',
    confidence: 0.66
  }
]

export const extractedFields: ExtractedField[] = [
  {
    id: 'FIELD-16-001',
    documentVersionId: 'DV-20260625-003-V2',
    fieldName: '炉批号',
    fieldValue: 'H240315A07',
    pageNo: 1,
    confidence: 0.66,
    reviewStatus: '低置信度',
    evidenceLinkId: 'EV-16-001'
  },
  {
    id: 'FIELD-24-001',
    documentVersionId: 'DV-20260625-001-V2',
    fieldName: '证书编号',
    fieldValue: 'TS6J-2024-03158',
    pageNo: 1,
    confidence: 0.96,
    reviewStatus: '已确认',
    evidenceLinkId: 'EV-24-001'
  }
]

export const aiRuns: AiReviewRun[] = [
  {
    id: 'AIRUN-24-20260625-01',
    projectId,
    nodeId: 24,
    subject: '焊工资格证及持证合格项目',
    model: 'LLM-A',
    promptVersion: '24-焊工资格-v1.5',
    ruleVersion: 'Welder-Qualification-B-v2.1',
    status: '完成',
    suggestion: {
      id: 'AIS-24-20260625-01',
      result: '需人工确认',
      opinionDraft:
        '焊工王建国证书编号、有效期和持证项目与焊接工艺要求匹配，建议人工确认外部查询截图来源后通过。',
      confidence: 0.88,
      manualConfirmItems: ['资格网站查询截图来源']
    },
    evidenceLinks,
    finishedAt: '2026-06-25 15:10:00'
  }
]

export const reviewOpinions: ReviewOpinion[] = [
  {
    id: 'OPN-24-001',
    projectId,
    nodeId: 24,
    result: '满足要求',
    opinion: '焊工资格证书真实有效，持证项目和项目焊接作业要求匹配。',
    evidenceLinkIds: ['EV-24-001', 'EV-24-002'],
    reviewerName: '张工',
    createdAt: '2026-06-26 09:12:00'
  }
]

export const reports: ReportVersion[] = [
  {
    id: 'RPT-20260625-001',
    projectId,
    reportNo: 'GDJ-JJ-2026-001',
    versionNo: 'V3',
    title: '华东成品油管道改造工程监督检验报告',
    status: '复核中',
    scope: 'project',
    nodeIds: [16, 24, 40, 59],
    generatedAt: '2026-06-26 09:40:00',
    reviewerName: '张工',
    previewUrl: 'mock://preview/reports/RPT-20260625-001',
    exportUrl: 'mock://download/reports/RPT-20260625-001.pdf',
    actions: ['report:view', 'report:export', 'report:archive']
  },
  {
    id: 'RPT-20250620-018',
    projectId: 'P-2025-NJARCH-018',
    reportNo: 'GDJ-JJ-2025-018',
    versionNo: 'V5',
    title: '南京老厂区管廊改造工程监督检验报告',
    status: '已归档',
    scope: 'project',
    nodeIds: [1, 16, 24, 40, 68],
    generatedAt: '2026-06-20 14:30:00',
    reviewerName: '周工',
    previewUrl: 'mock://preview/reports/RPT-20250620-018',
    exportUrl: 'mock://download/reports/RPT-20250620-018.pdf',
    actions: ['report:view', 'archive:view', 'archive:download']
  },
  {
    id: 'RPT-20260626-005',
    projectId: 'P-2026-BJHEAT-005',
    reportNo: 'GDJ-JJ-2026-005',
    versionNo: 'V1',
    title: '北京城市热网支线更新工程监督检验报告',
    status: '复核中',
    scope: 'project',
    nodeIds: [24, 40, 62],
    generatedAt: '2026-06-26 11:55:00',
    reviewerName: '李工',
    previewUrl: 'mock://preview/reports/RPT-20260626-005',
    exportUrl: 'mock://download/reports/RPT-20260626-005.pdf',
    actions: ['report:view', 'report:export']
  },
  {
    id: 'RPT-20250618-007',
    projectId: 'P-2025-CQARCH-007',
    reportNo: 'GDJ-JJ-2025-007',
    versionNo: 'V4',
    title: '重庆老厂酸碱管线整改工程监督检验报告',
    status: '已归档',
    scope: 'project',
    nodeIds: [16, 24, 40, 68],
    generatedAt: '2026-06-18 14:10:00',
    reviewerName: '陈工',
    previewUrl: 'mock://preview/reports/RPT-20250618-007',
    exportUrl: 'mock://download/reports/RPT-20250618-007.pdf',
    actions: ['report:view', 'archive:view', 'archive:download']
  }
]

export const archiveItems: ArchiveItem[] = [
  {
    id: 'ARCH-RPT-001',
    projectId,
    name: '监督检验报告 GDJ-JJ-2026-001.pdf',
    type: 'report',
    nodeId: 24,
    sourceOrgName: '省特检院一部',
    status: '复核中',
    updatedAt: '2026-06-26 09:40:00',
    downloadUrl: 'mock://download/reports/RPT-20260625-001.pdf'
  },
  {
    id: 'ARCH-EV-024',
    projectId,
    name: '节点 24 证据定位包.zip',
    type: 'evidence',
    nodeId: 24,
    sourceOrgName: '系统生成',
    status: '可下载',
    updatedAt: '2026-06-26 09:42:00',
    downloadUrl: 'mock://download/evidence/P-2026-HDCP-001-node-24.zip'
  },
  {
    id: 'ARCH-DOC-001',
    projectId,
    name: '焊工资格证-王建国.pdf',
    type: 'document',
    nodeId: 24,
    sourceOrgName: '中石化安装有限公司',
    status: '已上传',
    updatedAt: '2026-06-25 10:30:00',
    downloadUrl: 'mock://download/documents/DOC-20260625-001'
  },
  {
    id: 'ARCH-NJ-RPT-018',
    projectId: 'P-2025-NJARCH-018',
    name: '监督检验报告 GDJ-JJ-2025-018.pdf',
    type: 'report',
    nodeId: 68,
    sourceOrgName: '省特检院一部',
    status: '已归档',
    updatedAt: '2026-06-20 15:00:00',
    downloadUrl: 'mock://download/reports/RPT-20250620-018.pdf'
  },
  {
    id: 'ARCH-CQ-RPT-007',
    projectId: 'P-2025-CQARCH-007',
    name: '监督检验报告 GDJ-JJ-2025-007.pdf',
    type: 'report',
    nodeId: 68,
    sourceOrgName: '市特检院二部',
    status: '已归档',
    updatedAt: '2026-06-18 15:40:00',
    downloadUrl: 'mock://download/reports/RPT-20250618-007.pdf'
  },
  {
    id: 'ARCH-CQ-EV-040',
    projectId: 'P-2025-CQARCH-007',
    name: '节点 40 无损检测证据定位包.zip',
    type: 'evidence',
    nodeId: 40,
    sourceOrgName: '系统生成',
    status: '可下载',
    updatedAt: '2026-06-18 15:42:00',
    downloadUrl: 'mock://download/evidence/P-2025-CQARCH-007-node-40.zip'
  }
]

export const ndtFilms: NdtFilm[] = [
  {
    id: 'FILM-RT-001',
    projectId,
    filmNo: 'RT-R2-018-01',
    weldNo: 'W-24-RT-018',
    pipelineNo: 'PL-HD-02',
    method: 'RT',
    testDate: '2026-06-25',
    evaluationLevel: 'II',
    status: '待提交',
    actions: ['ndt:submit']
  },
  {
    id: 'FILM-UT-001',
    projectId,
    filmNo: 'UT-U1-006-01',
    weldNo: 'W-40-UT-006',
    pipelineNo: 'PL-HD-04',
    method: 'UT',
    testDate: '2026-06-25',
    evaluationLevel: 'I',
    status: '待审查',
    actions: ['ndt:submit']
  },
  {
    id: 'FILM-RT-002',
    projectId,
    filmNo: 'RT-R2-020-01',
    weldNo: 'W-41-RT-020',
    pipelineNo: 'PL-HD-04',
    method: 'RT',
    testDate: '2026-06-26',
    defectCode: '气孔待复核',
    status: '需补正',
    actions: ['rectification:submit']
  }
]

export const ndtReports: NdtReport[] = [
  {
    id: 'NDT-RPT-001',
    projectId,
    reportNo: 'RT-R2-20260625',
    method: 'RT',
    fileId: 'DOC-20260625-004',
    relatedFilmIds: ['FILM-RT-001'],
    status: '待提交',
    conclusion: 'RT II 级合格，需提交原始底片包。',
    uploadedAt: '2026-06-25 14:30:00',
    actions: ['ndt:submit']
  },
  {
    id: 'NDT-RPT-002',
    projectId,
    reportNo: 'UT-U1-20260625',
    method: 'UT',
    fileId: 'DOC-20260625-004',
    relatedFilmIds: ['FILM-UT-001'],
    status: '待审查',
    conclusion: 'UT I 级合格，等待监检确认。',
    uploadedAt: '2026-06-25 15:20:00',
    actions: ['ndt:submit']
  }
]

export const ndtFeedback: NdtFeedback[] = [
  {
    id: 'NDT-FB-001',
    projectId,
    nodeId: 40,
    title: 'RT 底片编号需补充原始包索引',
    description: '节点 40 检测报告已收到，需补充底片编号 RT-R2-020-01 对应的原始包索引。',
    status: '待反馈',
    relatedReportIds: ['NDT-RPT-001'],
    relatedFilmIds: ['FILM-RT-002'],
    createdAt: '2026-06-26 09:20:00',
    deadline: '2026-06-27 18:00:00'
  }
]

export const todos: TodoItem[] = [
  {
    id: 'TODO-24-001',
    title: '焊工资格节点待人工确认',
    projectId,
    nodeId: 24,
    targetType: 'node',
    targetId: '24',
    status: '待处理',
    priority: '高',
    deadline: '2026-06-26 18:00:00',
    assigneeName: '张工',
    actions: ['review:save']
  },
  {
    id: 'TODO-16-001',
    title: '材料质量证明文件需补正',
    projectId,
    nodeId: 16,
    targetType: 'rectification',
    targetId: 'REC-16-001',
    status: '待处理',
    priority: '高',
    deadline: '2026-06-28 18:00:00',
    assigneeName: '李工',
    actions: ['rectification:submit']
  },
  {
    id: 'TODO-40-001',
    title: '无损检测底片索引需补正',
    projectId,
    nodeId: 40,
    targetType: 'rectification',
    targetId: 'NDT-FB-001',
    status: '待处理',
    priority: '中',
    deadline: '2026-06-27 18:00:00',
    assigneeName: '王工',
    actions: ['rectification:submit', 'ndt:submit']
  }
]

export const messages: MessageItem[] = [
  {
    id: 'MSG-001',
    title: 'AI 预审完成',
    content: '节点 24 已生成 AI 审查建议，需人工确认。',
    projectId,
    targetType: 'node',
    targetId: '24',
    read: false,
    createdAt: '2026-06-26 09:12:00'
  },
  {
    id: 'MSG-002',
    title: '退回补正提醒',
    content: '节点 16 炉批号差异说明待补正。',
    projectId,
    targetType: 'rectification',
    targetId: 'REC-16-001',
    read: false,
    createdAt: '2026-06-25 18:21:00'
  }
]

export const roleNodeMap: Record<RoleCode, number> = {
  inspection: 24,
  contractor: 16,
  ndt: 40,
  owner: 24,
  admin: 24
}

export const nodeGroups = groupDefinitions.map((group) => ({
  id: group.name,
  name: group.name,
  nodes: treeNodes.filter((node) => node.groupName === group.name)
}))
