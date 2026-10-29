import type { Ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  bindDocumentsToNodeApi,
  bindInspectionDocumentsApi,
  completeDocumentUploadSessionApi,
  createDocumentUploadSessionApi,
  createInspectionAttachmentUploadSessionApi,
  submitInspectionDocumentBindingsApi
} from '@/api/aicheck'
import type { UploadSessionPayload, UploadSessionCompletePayload } from '@/api/aicheck'
import type { Project, UploadCompletionPresentation } from '@/types/aicheck'
import type { NdtAtomicMaterial } from '@/utils/ndtAtomicMaterials'
import { getAicheckErrorMessage } from '@/utils/aicheckError'
import {
  buildCorrectionUploadBindingPayload,
  type ContractorCorrectionTarget
} from './contractorCorrectionUpload'

type UploadContext = {
  activeProjectId: Ref<string>
  activeNodeId: Ref<number>
  currentProject: Ref<Project | undefined>
  actionLoading: Ref<boolean>
  uploadDrawerError: Ref<string>
  uploadDrawerReplaceTarget: Ref<{ documentId: string; fileName: string } | null>
  uploadDrawerMaterialCategory: Ref<string>
  uploadDrawerAtomicMaterial: Ref<NdtAtomicMaterial | undefined>
  uploadDrawerMode: Ref<'project' | 'inspection'>
  uploadDrawerRectificationTarget: Ref<ContractorCorrectionTarget | undefined>
  uploadDrawerVisible: Ref<boolean>
  correctionPreferredBindingIds: Ref<string[]>
  activeRectificationId: Ref<string>
  rectificationDialogMode: Ref<'view' | 'submit'>
  rectificationDialogVisible: Ref<boolean>
  bindDialogDocumentId: Ref<string>
  bindDialogError: Ref<string>
  bindDialogVisible: Ref<boolean>
  ensureWritableProject: () => boolean
  inferUploadFileType: (file: File) => string
  showUploadDrawerError: (fallback: string, error?: unknown) => void
  uploadFileToSignedUrl: (
    target: UploadSessionPayload['uploadUrls'][number],
    file: File
  ) => Promise<void>
  presentUploadCompletion: (payload: UploadSessionCompletePayload) => UploadCompletionPresentation
  loadProjectBundle: () => Promise<unknown>
  loadNodePackage: (nodeId: number) => Promise<unknown>
  loadSubmissionHistory: () => Promise<unknown>
}

export const useWorkbenchUploadSession = (ctx: UploadContext) => {
  const {
    activeProjectId,
    activeNodeId,
    currentProject,
    actionLoading,
    uploadDrawerError,
    uploadDrawerReplaceTarget,
    uploadDrawerMaterialCategory,
    uploadDrawerAtomicMaterial,
    uploadDrawerMode,
    uploadDrawerRectificationTarget,
    uploadDrawerVisible,
    correctionPreferredBindingIds,
    activeRectificationId,
    rectificationDialogMode,
    rectificationDialogVisible,
    bindDialogDocumentId,
    bindDialogError,
    bindDialogVisible,
    ensureWritableProject,
    inferUploadFileType,
    showUploadDrawerError,
    uploadFileToSignedUrl,
    presentUploadCompletion,
    loadProjectBundle,
    loadNodePackage,
    loadSubmissionHistory
  } = ctx
  const handleCreateUploadSession = async (files: File[], metadata?: { nodeIds: number[] }) => {
    if (!ensureWritableProject()) return
    if (!files.length) {
      ElMessage.warning('请选择至少一个本地文件')
      return
    }
    const uploadProjectId = activeProjectId.value
    const uploadNodeId = activeNodeId.value
    const uploadEtag = currentProject.value?.etag
    const uploadMode = uploadDrawerMode.value
    const correctionTarget = uploadDrawerRectificationTarget.value
      ? { ...uploadDrawerRectificationTarget.value }
      : undefined
    const isCurrentProject = () => activeProjectId.value === uploadProjectId
    actionLoading.value = true
    uploadDrawerError.value = ''
    let correctionFileUploaded = false
    let uploadedCorrectionDocumentId = ''
    try {
      if (uploadDrawerReplaceTarget.value && files.length !== 1) {
        // 替换是一对一的：选多个文件却只替换一份，剩下的会被静默丢弃。
        showUploadDrawerError('替换资料时只能选择一个文件。')
        return
      }
      const uploadFiles = files.map((file) => ({
        fileName: file.name,
        fileSize: file.size,
        fileType: inferUploadFileType(file),
        ...(uploadDrawerReplaceTarget.value
          ? { replaceDocumentId: uploadDrawerReplaceTarget.value.documentId }
          : {}),
        ...(uploadDrawerMaterialCategory.value
          ? { materialCategory: uploadDrawerMaterialCategory.value }
          : {}),
        ...(uploadDrawerAtomicMaterial.value
          ? {
              materialTypeCode: uploadDrawerAtomicMaterial.value.code,
              materialTypeName: uploadDrawerAtomicMaterial.value.name,
              nodeIds: metadata?.nodeIds || uploadDrawerAtomicMaterial.value.defaultNodeIds
            }
          : {})
      }))
      const res =
        uploadMode === 'inspection'
          ? await createInspectionAttachmentUploadSessionApi(
              uploadProjectId,
              uploadNodeId,
              uploadFiles,
              { etag: uploadEtag }
            )
          : await createDocumentUploadSessionApi(uploadProjectId, uploadFiles, {
              etag: uploadEtag
            })
      if (!res) {
        showUploadDrawerError('上传会话创建失败，请检查文件类型、大小和当前项目权限。')
        return
      }
      if (res.data.uploadUrls.length !== files.length) {
        throw new Error('上传会话返回的文件数量与本地选择不一致，请重新选择文件。')
      }
      await Promise.all(
        files.map((file, index) => uploadFileToSignedUrl(res.data.uploadUrls[index], file))
      )
      const completeRes = await completeDocumentUploadSessionApi(
        uploadProjectId,
        res.data.uploadSessionId,
        res.data.uploadUrls.map((target, index) => ({
          documentVersionId: target.documentVersionId,
          fileSize: files[index]?.size
        })),
        {
          etag: uploadEtag,
          idempotencyKey: `document-upload-complete-${res.data.uploadSessionId}`
        }
      )
      if (!completeRes) {
        throw new Error('上传完成确认失败，请刷新项目文件库后重试。')
      }
      correctionFileUploaded = Boolean(correctionTarget)
      uploadedCorrectionDocumentId = correctionFileUploaded
        ? String(res.data.uploadUrls[0]?.documentId || '')
        : ''
      if (uploadMode === 'inspection') {
        const bindRes = await bindInspectionDocumentsApi(
          uploadProjectId,
          uploadNodeId,
          res.data.uploadUrls.map((target) => ({
            documentId: target.documentId,
            documentVersionId: target.documentVersionId,
            usage: '监检资料'
          })),
          {
            etag: uploadEtag,
            idempotencyKey: `inspection-upload-bind-${res.data.uploadSessionId}`
          }
        )
        const bindingIds = bindRes?.data.affectedIds || []
        if (bindingIds.length !== files.length) {
          throw new Error('监检文件已上传，但未生成完整的节点挂载关系。')
        }
        const submitRes = await submitInspectionDocumentBindingsApi(
          uploadProjectId,
          uploadNodeId,
          {
            bindingIds,
            batchName: `R${String(uploadNodeId).padStart(2, '0')} 监检资料`,
            submitterComment: '监检人员上传并提交现场或评价证据。'
          },
          {
            etag: uploadEtag,
            idempotencyKey: `inspection-upload-submit-${res.data.uploadSessionId}`
          }
        )
        if (!submitRes || submitRes.data.bindingIds?.length !== bindingIds.length) {
          throw new Error('监检文件已挂载，但提交快照未包含全部文件。')
        }
        if (!isCurrentProject() || activeNodeId.value !== uploadNodeId) return
        presentUploadCompletion(completeRes.data)
        uploadDrawerVisible.value = false
        await Promise.all([loadProjectBundle(), loadSubmissionHistory()])
        return
      }
      if (correctionTarget) {
        const target = correctionTarget
        const bindRes = await bindDocumentsToNodeApi(
          uploadProjectId,
          buildCorrectionUploadBindingPayload(target, res.data.uploadUrls),
          { etag: uploadEtag }
        )
        const correctionBindingIds = bindRes?.data.affectedIds || []
        if (correctionBindingIds.length !== files.length) {
          throw new Error('补正资料已上传但尚未关联补正意见，请使用“关联已有文件”继续办理。')
        }
        if (!isCurrentProject()) return
        presentUploadCompletion(completeRes.data)
        uploadDrawerVisible.value = false
        await loadProjectBundle()
        if (!isCurrentProject()) return
        activeNodeId.value = target.nodeId
        await loadNodePackage(target.nodeId)
        if (!isCurrentProject()) return
        correctionPreferredBindingIds.value = correctionBindingIds
        activeRectificationId.value = target.rectificationId
        rectificationDialogMode.value = 'submit'
        rectificationDialogVisible.value = true
        return
      }
      if (!isCurrentProject()) return
      const presentation = presentUploadCompletion(completeRes.data)
      uploadDrawerVisible.value = false
      await loadProjectBundle()
      return presentation
    } catch (error) {
      if (!isCurrentProject()) return
      if (correctionFileUploaded) {
        const message = getAicheckErrorMessage(
          error,
          '补正资料已上传但尚未关联补正意见，请使用“关联已有文件”继续办理。'
        )
        uploadDrawerVisible.value = false
        await loadProjectBundle()
        bindDialogDocumentId.value = uploadedCorrectionDocumentId
        bindDialogError.value = message
        bindDialogVisible.value = true
        ElMessage.warning(message)
      } else {
        showUploadDrawerError('文件上传失败，请检查对象存储、网络连接和当前项目权限。', error)
      }
    } finally {
      actionLoading.value = false
    }
  }

  return { handleCreateUploadSession }
}
