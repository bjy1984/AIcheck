import type { DocumentAsset, NodeFileBinding } from '@/types/aicheck'

export type NdtMaterialActionKey = 'register' | 'upload' | 'rectify'
export type NdtMaterialActionRoute =
  | 'register-film'
  | 'upload-report'
  | 'upload-material'
  | 'feedback'

export type DocumentBindingSummary = '未关联' | '待提交' | '需补正' | '审核中' | '已通过'

export type DocumentSubmissionPayload =
  | {
      mode: 'node'
      nodeIds: number[]
      bindingIds: string[]
    }
  | {
      mode: 'project'
      documentIds: string[]
    }

export const resolveNdtMaterialAction = (
  category: string,
  key: NdtMaterialActionKey
): NdtMaterialActionRoute => {
  if (key === 'register' && category === '底片与影像资料') return 'register-film'
  if (key === 'upload' && category === '检测报告') return 'upload-report'
  if (key === 'upload') return 'upload-material'
  return 'feedback'
}

export const submittableDocumentBindings = (file: DocumentAsset): NodeFileBinding[] =>
  (file.bindings || []).filter((item) => ['草稿挂载', '需补正'].includes(item.bindingStatus))

export const isProjectPoolSubmitted = (file: DocumentAsset): boolean =>
  file.poolSubmissionStatus === '已提交'

export const buildDocumentSubmissionPayload = (
  file: DocumentAsset
): DocumentSubmissionPayload | undefined => {
  const bindings = submittableDocumentBindings(file)
  if (bindings.length) {
    return {
      mode: 'node',
      nodeIds: Array.from(new Set(bindings.map((item) => item.nodeId))).sort(
        (left, right) => left - right
      ),
      bindingIds: bindings.map((item) => item.id)
    }
  }
  if (
    !(file.bindings || []).length &&
    !isProjectPoolSubmitted(file) &&
    file.fileStatus === '已上传'
  ) {
    return {
      mode: 'project',
      documentIds: [file.id]
    }
  }
  return undefined
}

export const documentBindingSummary = (file: DocumentAsset): DocumentBindingSummary => {
  const bindings = file.bindings || []
  if (!bindings.length) {
    return isProjectPoolSubmitted(file) ? '审核中' : '未关联'
  }
  if (bindings.some((item) => item.bindingStatus === '需补正')) return '需补正'
  if (bindings.some((item) => item.bindingStatus === '草稿挂载')) return '待提交'
  if (bindings.every((item) => item.bindingStatus === '已通过')) return '已通过'
  return '审核中'
}
