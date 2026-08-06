import type { DocumentAsset } from '@/types/aicheck'

export const NDT_NODE_IDS = [35, 36, 37, 38, 39, 40, 41, 42] as const

export type NdtNodeId = (typeof NDT_NODE_IDS)[number]

export type NdtAtomicMaterial = {
  code: string
  name: string
  group: string
  defaultNodeIds: NdtNodeId[]
}

export type NdtFileApprovalStatus = '草稿' | '待审查' | '需补正' | '已通过'

export const NDT_ATOMIC_MATERIALS: NdtAtomicMaterial[] = [
  {
    code: 'ndt_quality_assurance_manual',
    name: '无损检测单位质量保证手册',
    group: 'R35 质量保证体系',
    defaultNodeIds: [35]
  },
  {
    code: 'ndt_controlled_record_form',
    name: '受控记录表格',
    group: 'R35 质量保证体系',
    defaultNodeIds: [35]
  },
  {
    code: 'ndt_controlled_report_form',
    name: '受控报告表格',
    group: 'R35 质量保证体系',
    defaultNodeIds: [35]
  },
  {
    code: 'ndt_project_personnel_appointment',
    name: '项目人员任命文件',
    group: 'R35 质量保证体系',
    defaultNodeIds: [35]
  },
  {
    code: 'ndt_equipment_calibration_report',
    name: '检测仪器及设备检定报告',
    group: 'R35 质量保证体系',
    defaultNodeIds: [35]
  },
  { code: 'ndt_plan', name: '无损检测方案', group: 'R36 检测方案', defaultNodeIds: [36] },
  {
    code: 'ndt_nonconforming_control_procedure',
    name: '不合格品与不符合项控制程序',
    group: 'R37 问题处理',
    defaultNodeIds: [37]
  },
  {
    code: 'ndt_entrustment',
    name: '无损检测委托单',
    group: 'R37/R42 委托资料',
    defaultNodeIds: [37, 42]
  },
  {
    code: 'ndt_nonconformity_notice',
    name: '不合格品联络单或意见书',
    group: 'R37 问题处理',
    defaultNodeIds: [37]
  },
  {
    code: 'ndt_disposition_feedback',
    name: '不合格品处理反馈见证文件',
    group: 'R37 问题处理',
    defaultNodeIds: [37]
  },
  {
    code: 'ndt_person_roster',
    name: '无损检测人员明细表',
    group: 'R38 人员资格',
    defaultNodeIds: [38]
  },
  {
    code: 'ndt_person_certificate',
    name: '无损检测人员资格证',
    group: 'R38 人员资格',
    defaultNodeIds: [38]
  },
  {
    code: 'ndt_practice_registration_certificate',
    name: '无损检测人员执业注册证',
    group: 'R38 人员资格',
    defaultNodeIds: [38]
  },
  {
    code: 'ndt_employment_contract',
    name: '无损检测人员劳动合同证明',
    group: 'R38 人员资格',
    defaultNodeIds: [38]
  },
  {
    code: 'ndt_procedure',
    name: '单项无损检测工艺文件',
    group: 'R39 工艺文件',
    defaultNodeIds: [39]
  },
  {
    code: 'ndt_operation_instruction',
    name: '无损检测操作指导书',
    group: 'R39 工艺文件',
    defaultNodeIds: [39]
  },
  {
    code: 'ndt_record',
    name: '无损检测记录',
    group: 'R40/R42 记录',
    defaultNodeIds: [40, 42]
  },
  {
    code: 'ndt_report',
    name: '无损检测报告',
    group: 'R40/R41/R42 报告',
    defaultNodeIds: [40, 41, 42]
  },
  {
    code: 'radiographic_film',
    name: '射线检测底片或数字影像',
    group: 'R41/R42 底片',
    defaultNodeIds: [41, 42]
  },
  {
    code: 'ndt_field_spot_check_record',
    name: '射线检测现场抽查记录',
    group: 'R42 现场抽查',
    defaultNodeIds: [42]
  },
  {
    code: 'ndt_outsourcing_contract',
    name: '委托无损检测合同',
    group: 'R42 现场抽查',
    defaultNodeIds: [42]
  }
]

const materialsByCode = new Map(NDT_ATOMIC_MATERIALS.map((material) => [material.code, material]))

export const ndtAtomicMaterialByCode = (code?: string | null) =>
  code ? materialsByCode.get(code) : undefined

export const ndtFileApprovalStatus = (
  file: Pick<DocumentAsset, 'bindings'>
): NdtFileApprovalStatus => {
  const bindings = file.bindings || []
  if (bindings.some((binding) => binding.bindingStatus === '需补正')) return '需补正'
  if (bindings.length && bindings.every((binding) => binding.bindingStatus === '已通过')) {
    return '已通过'
  }
  if (bindings.some((binding) => binding.bindingStatus === '已提交')) return '待审查'
  return '草稿'
}
