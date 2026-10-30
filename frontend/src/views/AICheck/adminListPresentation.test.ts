import assert from 'node:assert/strict'
import type {
  AdminMaterialReviewPoint,
  AdminOrgUnit,
  AdminUser,
  ReportTemplate
} from '@/api/aicheck'
import {
  filterMaterialPoints,
  filterOrganizations,
  filterAdminUsers,
  adminOrgTypeLabel,
  adminAuditActionLabel,
  adminCodeLabel,
  reportDraftFrom
} from './adminListPresentation'
import { handler, ref, noop, asyncNoop } from './workflowTestHarness'

const point: AdminMaterialReviewPoint = {
  id: 'point',
  businessPackId: 'pack',
  nodeId: 1,
  nodeName: '单位资格',
  reviewContent: '许可证核验',
  materialCategory: '资格',
  materialTypeCode: 'license',
  materialTypeName: '许可证',
  evidenceItems: ['许可范围'],
  responsibleParty: 'inspection',
  requiredType: '必传',
  minConfidence: 0,
  enabled: true,
  updatedAt: ''
}
const points = Array.from({ length: 168 }, (_, i) => ({ ...point, id: `point-${i}` }))
points[167] = {
  ...point,
  id: 'last-page',
  nodeId: 68,
  nodeName: '归档',
  materialTypeCode: 'report',
  materialTypeName: '监检报告',
  reviewContent: '独特末页审查点',
  evidenceItems: ['OCR-unique-evidence'],
  enabled: false
}
const filters = { keyword: '', nodeId: '', materialTypeCode: '', enabled: '' }
assert.equal(filterMaterialPoints(points, filters).length, 168)
assert.deepEqual(
  filterMaterialPoints(points, { ...filters, keyword: '  独特末页 ' })
    .slice(0, 10)
    .map((row) => row.id),
  ['last-page']
)
assert.deepEqual(
  filterMaterialPoints(points, {
    ...filters,
    keyword: 'ocr-UNIQUE',
    nodeId: '68',
    materialTypeCode: 'report',
    enabled: 'false'
  }).map((row) => row.id),
  ['last-page']
)
assert.equal(
  filterMaterialPoints(points, { ...filters, keyword: '独特末页', enabled: 'true' }).length,
  0
)
assert.equal(
  filterMaterialPoints(points, { ...filters, nodeId: '68', materialTypeCode: 'license' }).length,
  0
)
assert.equal(points.length, 168)
assert.equal(points[167].enabled, false)

const orgs: AdminOrgUnit[] = [
  {
    id: 'one',
    name: '华东检测',
    type: 'ndt',
    contactName: '李工',
    contactPhone: '123',
    status: '启用',
    projectCount: 1
  },
  {
    id: 'two',
    name: '华东施工',
    type: 'contractor',
    contactName: '赵工',
    contactPhone: '456',
    status: '停用',
    projectCount: 0
  }
]
assert.equal(filterOrganizations(orgs, { keyword: '无损 李工', type: '', status: '' })[0].id, 'one')
assert.equal(
  filterOrganizations(orgs, { keyword: '华东', type: 'contractor', status: '启用' }).length,
  0
)
const users: AdminUser[] = [
  {
    id: 'u1',
    username: 'Admin',
    name: '管理员',
    orgId: 'one',
    orgName: '华东检测',
    role: 'admin',
    mobile: '123',
    status: '启用',
    lastLoginAt: ''
  },
  {
    id: 'u2',
    username: 'zhao',
    name: '赵工',
    orgId: 'two',
    orgName: '华东施工',
    role: 'contractor',
    mobile: '456',
    status: '停用',
    lastLoginAt: ''
  }
]
const userFilters = { keyword: '', role: '', orgId: '', status: '' }
assert.equal(filterAdminUsers(users, { ...userFilters, keyword: '系统管理员 admin' })[0].id, 'u1')
assert.equal(
  filterAdminUsers(users, { ...userFilters, orgId: 'two', role: 'contractor', status: '停用' })[0]
    .id,
  'u2'
)
assert.equal(
  filterAdminUsers(users, { ...userFilters, orgId: 'one', role: 'contractor' }).length,
  0
)
assert.equal(adminOrgTypeLabel('ndt'), '无损检测单位')
assert.equal(adminOrgTypeLabel('new-type'), 'new-type')
assert.equal(adminCodeLabel('archive-package'), '归档包')
assert.equal(adminCodeLabel('Authentication'), '账号登录')
assert.equal(adminCodeLabel('new-code'), 'new-code')

const production: ReportTemplate = {
  id: 'report-production',
  name: '监检报告',
  version: 'v3',
  status: 'production',
  etag: 'production-etag',
  businessPackId: 'pack',
  businessPackVersion: 'v2',
  updatedAt: '',
  exportTypes: ['report', 'archive-package'],
  sections: [{ code: 'summary', title: '概况', source: 'project' }]
}
const draft = reportDraftFrom(production)
draft.sections[0].title = '修改概况'
draft.exportTypes.push('evidence-package')
assert.equal(production.sections[0].title, '概况')
assert.deepEqual(production.exportTypes, ['report', 'archive-package'])

// Execute the actual drawer/open/save handlers: derived data must go to create,
// never to update or publish, while keeping the original production record intact.
const form: Record<string, unknown> = {}
const mode = ref('view')
const visible = ref(false)
const error = ref('')
const reset = handler('./AdminOverview.vue', 'resetReportTemplateForm', {
  reportTemplateForm: form,
  reportTemplateOperationError: error,
  DEFAULT_PIPELINE_BUSINESS_PACK_ID: 'default',
  defaultReportSections: () => '[]'
})
handler('./AdminOverview.vue', 'openReportTemplateDraft', {
  reportTemplateDialogMode: mode,
  reportTemplateDialogVisible: visible,
  resetReportTemplateForm: reset,
  reportDraftFrom
})(production)
assert.equal(mode.value, 'create')
assert.equal(visible.value, true)
assert.equal(form.id, '')
assert.equal(form.etag, '')
assert.equal(form.status, 'draft')
assert.equal(form.version, 'v3-draft')
const buildPayload = handler('./AdminOverview.vue', 'buildReportTemplatePayload', {
  reportTemplateForm: form,
  ElMessage: { warning: (message: string) => assert.fail(message) },
  DEFAULT_PIPELINE_BUSINESS_PACK_ID: 'default'
})
const createdPayloads: Record<string, unknown>[] = []
await handler('./AdminOverview.vue', 'handleSaveReportTemplate', {
  buildReportTemplatePayload: buildPayload,
  reportTemplateSaving: ref(false),
  reportTemplateOperationError: error,
  reportTemplateDialogMode: mode,
  reportTemplateForm: form,
  createReportTemplateApi: async (payload: Record<string, unknown>) => {
    createdPayloads.push(payload)
    return { data: {} }
  },
  updateReportTemplateApi: () => assert.fail('must not update production'),
  ElMessage: { success: noop },
  reportTemplateDialogVisible: visible,
  loadReportTemplates: asyncNoop,
  loadAuditLogs: asyncNoop,
  getRequestErrorMessage: () => 'unexpected save error',
  buildOperationFailureMessage: () => 'unexpected'
})()
assert.equal(error.value, '')
assert.equal(createdPayloads.length, 1)
assert.equal(createdPayloads[0].status, 'draft')
assert.equal(createdPayloads[0].businessPackId, 'pack')
assert.equal(createdPayloads[0].id, undefined)
assert.equal(visible.value, false)
assert.equal(production.status, 'production')
assert.equal(production.etag, 'production-etag')

// 审计日志动作：接口原文翻成人话，认不出的保持原样
{
  assert.equal(
    adminAuditActionLabel('拒绝 POST /v1/extension-agents/agt_9f8e7d6c/token'),
    '拒绝：浏览器扩展 · 令牌（提交）'
  )
  assert.equal(
    adminAuditActionLabel('拒绝 POST /v1/extension-tasks/claim-next'),
    '拒绝：扩展任务 · 领取下一个任务（提交）'
  )
  assert.equal(adminAuditActionLabel('登录成功'), '登录成功', '不是接口原文就原样返回')
  assert.equal(adminAuditActionLabel(''), '—')
  assert.equal(adminCodeLabel('SecurityEvent'), '安全事件')
}
