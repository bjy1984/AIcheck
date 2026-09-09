import request from '@/axios'
import type { DocumentAsset } from '@/types/aicheck'

export type ReviewDocument = DocumentAsset & { bodyUploaded?: boolean }
export type ReviewDocumentSelection = {
  versions: Array<{ documentId: string; versionId: string; fileName: string; versionNo?: string }>
  reviewMode: 'formal' | 'gap_precheck'
}

export const listReviewDocuments = (
  projectId: string,
  params: { keyword: string; page: number; pageSize: number }
) =>
  request.get<{ items: ReviewDocument[]; total: number }>({
    url: `/api/projects/${projectId}/documents`,
    params
  })

export const getReviewVersionOriginal = async (
  projectId: string,
  documentId: string,
  versionId: string
) => {
  const response = await request.get<Blob>({
    url: `/api/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(documentId)}/original`,
    params: { versionId, disposition: 'inline' },
    responseType: 'blob'
  })
  if (!(response.data instanceof Blob) || response.data.type.includes('application/json'))
    throw new Error('所选版本原文不可用')
  return response.data
}
