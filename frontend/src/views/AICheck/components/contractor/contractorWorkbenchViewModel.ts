import type { DocumentAsset, NodePackagePayload } from '@/types/aicheck'
import { documentBindingSummary } from '@/utils/acceptanceFlows'
import { documentBusinessStatus } from '@/utils/documentPipelineStatus'

export type ContractorPrimaryTab = '全部' | '待提交' | '审核中' | '需补正' | '已通过'
export type ContractorStatusCardKey = 'feedback' | 'pending' | 'reviewing'

export type ContractorWorkbenchFile = {
  documentId: string
  status: ContractorPrimaryTab | '未关联' | '已作废'
  updatedAt: string
  processingStatus: '上传中' | '上传成功' | '识别失败' | '失败重新上传'
  source: DocumentAsset
}

export type ContractorWorkbenchModel = {
  summaryCards: Array<{
    key: ContractorStatusCardKey
    label: string
    count: number
    tone: 'orange' | 'blue' | 'green'
  }>
  primaryTabs: Array<{ key: ContractorPrimaryTab; count: number }>
  recentUpload: {
    total: number
    successful: number
    processing: number
    failed: number
  }
  files: ContractorWorkbenchFile[]
}

export type ContractorSummaryTarget = {
  anchor: '#contractor-feedback-list' | '#contractor-file-list'
  tab: '待提交' | '审核中' | null
}

export type ContractorFeedbackSortable = {
  id: string
  status: string
  createdAt: string
}

export const sortContractorFeedback = <T extends ContractorFeedbackSortable>(
  items: readonly T[]
): T[] => {
  const rank = (status: string) => {
    if (status === '待反馈') return 0
    if (status === '已重新提交') return 1
    if (status === '已关闭') return 3
    return 2
  }
  return [...items].sort((left, right) => {
    const rankDifference = rank(left.status) - rank(right.status)
    if (rankDifference) return rankDifference
    return right.createdAt.localeCompare(left.createdAt)
  })
}

export const resolveContractorSummaryTarget = (
  key: ContractorStatusCardKey
): ContractorSummaryTarget => {
  if (key === 'feedback') {
    return { anchor: '#contractor-feedback-list', tab: null }
  }
  return {
    anchor: '#contractor-file-list',
    tab: key === 'pending' ? '待提交' : '审核中'
  }
}

export const buildContractorWorkbenchModel = (
  packageData: Pick<NodePackagePayload, 'projectFiles' | 'rectifications'>
): ContractorWorkbenchModel => {
  const files = packageData.projectFiles
    .map<ContractorWorkbenchFile>((file) => ({
      documentId: file.id,
      status:
        file.fileStatus === '已作废' || file.fileStatus === '已替换'
          ? '已作废'
          : documentBindingSummary(file),
      updatedAt: file.updatedAt,
      processingStatus: documentBusinessStatus(file),
      source: file
    }))
    .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt))

  const statusCount = (status: ContractorWorkbenchFile['status']) =>
    files.filter((file) => file.status === status).length
  const recentFiles = files.slice(0, 8)

  return {
    summaryCards: [
      {
        key: 'feedback',
        label: '待处理意见',
        count: packageData.rectifications.filter((item) => item.status === '待反馈').length,
        tone: 'orange'
      },
      {
        key: 'pending',
        label: '待提交',
        count: statusCount('待提交'),
        tone: 'orange'
      },
      {
        key: 'reviewing',
        label: '审核中',
        count: statusCount('审核中'),
        tone: 'green'
      }
    ],
    primaryTabs: (['全部', '待提交', '审核中', '需补正', '已通过'] as const).map((key) => ({
      key,
      count: key === '全部' ? files.length : statusCount(key)
    })),
    recentUpload: {
      total: recentFiles.length,
      successful: recentFiles.filter((file) => file.processingStatus === '上传成功').length,
      processing: recentFiles.filter((file) => file.processingStatus === '上传中').length,
      failed: recentFiles.filter((file) =>
        ['识别失败', '失败重新上传'].includes(file.processingStatus)
      ).length
    },
    files
  }
}
