import request from '@/axios'
import type { DocumentAsset } from '@/types/aicheck'

export type ReviewDocument = DocumentAsset & { bodyUploaded?: boolean }
export type ReviewDocumentSelection = {
  versions: Array<{ documentId: string; versionId: string; fileName: string }>
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
