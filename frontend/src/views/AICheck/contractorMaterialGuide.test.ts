import assert from 'node:assert/strict'

import {
  CONTRACTOR_MATERIAL_GUIDE_COLUMNS,
  CONTRACTOR_WORKBENCH_SECTION_ORDER
} from './contractorMaterialGuide'

assert.deepEqual(
  CONTRACTOR_MATERIAL_GUIDE_COLUMNS.map((column) => column.key),
  ['category', 'requiredItems', 'uploadHint'],
  '资料分类指引只展示分类、建议资料和上传提示'
)

assert.deepEqual(
  CONTRACTOR_WORKBENCH_SECTION_ORDER,
  ['task-overview', 'file-ledger', 'material-guide'],
  '上传文件列表必须排在资料分类指引前面'
)

console.log('Contractor material guide presentation contract passed')
