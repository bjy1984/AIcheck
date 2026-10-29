import type {
  AdminMaterialReviewPoint,
  AdminOrgUnit,
  AdminUser,
  ReportTemplate
} from '@/api/aicheck'
import { getAicheckRoleLabel } from '@/utils/roleAccess'

export const adminOrgTypeLabels: Record<string, string> = {
  inspection: '监检机构',
  supervision: '监理单位',
  contractor: '施工方',
  ndt: '无损检测单位',
  owner: '建设方',
  admin: '平台管理',
  fde: 'FDE 技术支持'
}

export const adminAuditTypeLabels: Record<string, string> = {
  Authentication: '账号登录',
  ReviewOpinion: '审查意见',
  AdminConfig: '后台配置',
  AdminConfigExport: '配置导出',
  PromptTemplate: 'Prompt 模板',
  ReportTemplate: '报告模板',
  ProjectMember: '项目成员',
  RuleTemplate: '业务规则',
  ReportVersion: '报告版本',
  MessageItem: '消息'
}

const technicalLabels: Record<string, string> = {
  ...adminAuditTypeLabels,
  report: '报告',
  'archive-package': '归档包',
  'evidence-package': '证据包',
  'external-query': '外部查询',
  ocr: 'OCR 识别',
  signature: '签名验证',
  archive: '归档',
  none: '无需鉴权',
  token: '令牌',
  compliance_review_agent: '合规审查 Agent'
}

export const adminCodeLabel = (value?: string) => (value ? technicalLabels[value] || value : '—')
export const adminOrgTypeLabel = (value: string) => adminOrgTypeLabels[value] || value

const matchesKeyword = (keyword: string, values: unknown[]) => {
  const haystack = values
    .filter((value) => value != null)
    .join(' ')
    .toLocaleLowerCase()
  return keyword
    .trim()
    .toLocaleLowerCase()
    .split(/\s+/)
    .every((term) => haystack.includes(term))
}

export type MaterialPointFilters = {
  keyword: string
  nodeId: string
  materialTypeCode: string
  enabled: string
}
export type OrganizationFilters = { keyword: string; type: string; status: string }
export type AdminUserFilters = { keyword: string; role: string; orgId: string; status: string }

// config-overview returns complete sections, so callers filter before sorting and paginating.
export const filterMaterialPoints = (
  rows: AdminMaterialReviewPoint[],
  filters: MaterialPointFilters
) =>
  rows.filter(
    (row) =>
      (!filters.nodeId || String(row.nodeId) === filters.nodeId) &&
      (!filters.materialTypeCode || row.materialTypeCode === filters.materialTypeCode) &&
      (!filters.enabled || String(row.enabled) === filters.enabled) &&
      matchesKeyword(filters.keyword, [
        row.id,
        row.ruleId,
        row.nodeName,
        row.reviewContent,
        row.fileContent,
        row.materialTypeName,
        row.materialTypeCode,
        row.evidenceItemText,
        ...(row.evidenceItems || []),
        row.businessModule,
        row.reviewClass
      ])
  )

export const filterOrganizations = (rows: AdminOrgUnit[], filters: OrganizationFilters) =>
  rows.filter(
    (row) =>
      (!filters.type || row.type === filters.type) &&
      (!filters.status || row.status === filters.status) &&
      matchesKeyword(filters.keyword, [
        row.id,
        row.name,
        row.type,
        adminOrgTypeLabel(row.type),
        row.contactName,
        row.contactPhone
      ])
  )

export const filterAdminUsers = (rows: AdminUser[], filters: AdminUserFilters) =>
  rows.filter(
    (row) =>
      (!filters.role || row.role === filters.role) &&
      (!filters.orgId || row.orgId === filters.orgId) &&
      (!filters.status || row.status === filters.status) &&
      matchesKeyword(filters.keyword, [
        row.id,
        row.username,
        row.name,
        row.orgName,
        row.mobile,
        row.role,
        getAicheckRoleLabel(row.role)
      ])
  )

export const reportDraftFrom = (template: ReportTemplate): ReportTemplate => ({
  ...template,
  id: '',
  etag: '',
  version: `${template.version}-draft`,
  status: 'draft',
  exportTypes: [...template.exportTypes],
  sections: template.sections.map((section) => ({ ...section }))
})
