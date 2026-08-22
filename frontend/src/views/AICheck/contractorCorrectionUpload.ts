export type ContractorCorrectionTarget = {
  rectificationId: string
  nodeId: number
}

export type UploadedCorrectionDocument = {
  documentId: string
  documentVersionId: string
}

export const buildCorrectionUploadBindingPayload = (
  target: ContractorCorrectionTarget,
  documents: readonly UploadedCorrectionDocument[]
) => ({
  nodeId: target.nodeId,
  nodeIds: [target.nodeId],
  bindings: documents.map((item) => ({
    documentId: item.documentId,
    documentVersionId: item.documentVersionId,
    usage: '补正附件' as const
  }))
})
