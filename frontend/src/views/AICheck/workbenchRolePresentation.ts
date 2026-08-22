import type { RoleCode } from '@/types/aicheck'

export type WorkbenchRolePresentation = {
  showBreadcrumb: boolean
  intro: string
}

export const workbenchRolePresentation = (role: RoleCode): WorkbenchRolePresentation =>
  role === 'contractor'
    ? {
        showBreadcrumb: false,
        intro: '统一上传项目资料并提交，根据监检意见补充完善相关资料。'
      }
    : {
        showBreadcrumb: true,
        intro: ''
      }
