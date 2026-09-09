import type { RoleCode } from '@/types/aicheck'

export type WorkbenchRolePresentation = {
  showBreadcrumb: boolean
  intro: string
}

const normalizedSubmittedFileCount = (value: number) =>
  Number.isFinite(value) ? Math.max(0, Math.trunc(value)) : 0

export const submittedFileCountLabel = (submittedFileCount: number) =>
  `${normalizedSubmittedFileCount(submittedFileCount)} 个文件`

export const submittedNodeMeta = (inspectionType: string, submittedFileCount: number) =>
  `${inspectionType || '-'} 类 · 已提交 ${submittedFileCountLabel(submittedFileCount)}`

export const projectSubmissionMeta = (nodeCount: number, submittedFileCount: number) =>
  `节点 ${Math.max(0, Math.trunc(nodeCount || 0))} · 提交 ${normalizedSubmittedFileCount(submittedFileCount)}`

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

type InspectionReviewProgressLabel = '未提交' | '待审查' | '未补正' | '已通过'
export const getInspectionReviewProgress = (
  status?: string
): { label: InspectionReviewProgressLabel; rank: number } => {
  if (!status) return { label: '未提交', rank: 3 }
  if (status.includes('通过')) return { label: '已通过', rank: 4 }
  if (status.includes('补正')) return { label: '未补正', rank: 2 }
  if (['待审查', 'AI 预审中', '待人工确认', '复审中', '已提交'].includes(status)) {
    return { label: '待审查', rank: 1 }
  }
  return { label: '未提交', rank: 3 }
}
