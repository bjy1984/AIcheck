export type ContractorMaterialGuideColumn = {
  key: 'category' | 'uploaded' | 'action' | 'requiredItems' | 'uploadHint'
  label: string
  width?: number
  minWidth?: number
}

export const CONTRACTOR_MATERIAL_GUIDE_COLUMNS: ContractorMaterialGuideColumn[] = [
  { key: 'category', label: '资料类别', width: 180 },
  { key: 'requiredItems', label: '建议包含资料', minWidth: 420 },
  { key: 'uploadHint', label: '上传提示', minWidth: 360 }
]

export const CONTRACTOR_WORKBENCH_SECTION_ORDER = [
  'task-overview',
  'file-ledger',
  'material-guide'
] as const
