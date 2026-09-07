/**
 * 监检工作台的"改变业务状态"动作：采纳/驳回 AI 建议、确认/不采用证据、退回补正。
 * 从 Workbench.vue 整体搬出（巨石棘轮：单文件不许再长）；逻辑与原来逐字一致，
 * 只把用到的 ref / 函数收进一个 ctx 对象，调用方按名传入。
 */
import type { Ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  adoptAiSuggestionApi,
  confirmNodeEvidenceLinkApi,
  rejectAiSuggestionApi,
  rejectNodeEvidenceLinkApi,
  returnCorrectionApi
} from '@/api/aicheck'
import type { AiReviewRun, EvidenceLink, ProjectTreeNode, ReviewOpinion } from '@/types/aicheck'

import { AI_RESULT_TO_OPINION, EVIDENCE_REJECT_REASONS, pickReason } from './aiFindingFeedback'
import type { WorkbenchAiFinding } from './workbenchReviewPresentation'

export type WorkbenchReviewActionsContext = {
  activeProjectId: Ref<string>
  activeNodeId: Ref<number>
  latestAiRun: Ref<AiReviewRun | undefined>
  latestAiReviewFailed: () => boolean
  reviewResult: Ref<ReviewOpinion['result']>
  reviewOpinion: Ref<string>
  correctionReason: Ref<string>
  selectedReviewEvidenceIds: Ref<string[]>
  draftRequiresEvidenceSelection: Ref<boolean>
  activeSideTab: Ref<string>
  actionLoading: Ref<boolean>
  actionBlocker: Ref<unknown>
  pendingCorrectionFinding: Ref<WorkbenchAiFinding | undefined>
  etag: () => string | undefined
  submittedBindingIds: () => string[]
  evidenceLinkIds: () => string[]
  ensureWritableNode: () => boolean
  confirmIrreversibleAction: (options: {
    title: string
    message: string
    confirmText: string
  }) => Promise<boolean>
  rememberActionBlocker: (title: string, message?: string) => void
  showActionError: (message: string) => void
  loadNodePackage: (nodeId: number, options?: { silent?: boolean }) => Promise<unknown>
  loadProjectBundle: () => Promise<unknown>
  recordAiRunDecision: (accepted: boolean, comment: string) => Promise<unknown>
  findTreeNode: (nodeId: number) => ProjectTreeNode | undefined
  selectNode: (node: ProjectTreeNode) => Promise<unknown>
}

export const useWorkbenchReviewActions = (ctx: WorkbenchReviewActionsContext) => {
  const handleAdoptAiSuggestion = async (suggestionId: string) => {
    if (!ctx.ensureWritableNode() || !ctx.latestAiRun.value) return
    if (ctx.latestAiReviewFailed()) {
      ElMessage.warning('本次 AI 复核失败，未生成可采纳的建议。')
      return
    }
    const confirmed = await ctx.confirmIrreversibleAction({
      title: '采纳 AI 建议',
      message: `将以 AI 建议「${ctx.latestAiRun.value.suggestion.result}」生成人工结论草稿。AI 建议不能替代人工判断，请确认已核对证据与条款依据。`,
      confirmText: '确认采纳'
    })
    if (!confirmed) return
    ctx.actionLoading.value = true
    try {
      const aiResult = ctx.latestAiRun.value.suggestion.result
      // AI 建议结论 → 人工结论预填（口径见 aiFindingFeedback.AI_RESULT_TO_OPINION）。
      const normalizedResult = AI_RESULT_TO_OPINION[aiResult]
      const res = await adoptAiSuggestionApi(
        ctx.activeProjectId.value,
        ctx.activeNodeId.value,
        suggestionId,
        {
          result: normalizedResult,
          opinion: ctx.latestAiRun.value.suggestion.opinionDraft,
          evidenceLinkIds: ctx.selectedReviewEvidenceIds.value,
          reason: '采纳 AI 建议作为人工审查草稿。'
        },
        { etag: ctx.etag() }
      )
      if (!res) {
        ctx.showActionError('AI 建议采纳失败，请刷新 AI 建议后重试。')
        return
      }
      ctx.reviewResult.value = res.data.draftOpinion.result
      ctx.reviewOpinion.value = res.data.draftOpinion.opinion
      ctx.selectedReviewEvidenceIds.value = res.data.draftOpinion.evidenceLinkIds || []
      ctx.draftRequiresEvidenceSelection.value = Boolean(
        res.data.draftOpinion.requiresEvidenceSelection
      )
      ctx.activeSideTab.value = 'opinion'
      if (res.data.draftOpinion.requiresEvidenceSelection) {
        ctx.rememberActionBlocker(
          'AI 建议已转为草稿，但仍需选择证据',
          '请选择当前节点 confirmed 证据后再保存正式审查意见。'
        )
        ctx.activeSideTab.value = 'evidence'
        ElMessage.warning('AI 建议已采纳为草稿，但仍需人工选择 confirmed 证据')
      } else {
        ctx.actionBlocker.value = undefined
        ElMessage.success('AI 建议已采纳为审查草稿')
      }
      await ctx.recordAiRunDecision(true, '采纳 AI 建议作为人工审查草稿。')
      await ctx.loadNodePackage(ctx.activeNodeId.value)
    } finally {
      ctx.actionLoading.value = false
    }
  }

  const handleRejectAiSuggestion = async (suggestionId: string) => {
    if (!ctx.ensureWritableNode()) return
    let rejectionReason = ''
    try {
      const prompt = await ElMessageBox.prompt(
        '请说明 AI 建议与人工判断不一致的具体原因。该说明会进入审计日志。',
        '驳回 AI 建议',
        {
          confirmButtonText: '确认驳回',
          cancelButtonText: '取消',
          inputType: 'textarea',
          inputPlaceholder: '填写证据、规则或结论方面的差异',
          inputValidator: (value) =>
            value.trim().length >= 4 ? true : '请至少填写 4 个字符的具体原因'
        }
      )
      rejectionReason = prompt.value.trim()
    } catch {
      return
    }
    ctx.actionLoading.value = true
    try {
      const res = await rejectAiSuggestionApi(
        ctx.activeProjectId.value,
        ctx.activeNodeId.value,
        suggestionId,
        { reason: rejectionReason, manualOpinion: ctx.reviewOpinion.value },
        { etag: ctx.etag() }
      )
      if (!res) {
        ctx.showActionError('AI 建议驳回失败，请刷新 AI 建议后重试。')
        return
      }
      await ctx.recordAiRunDecision(false, rejectionReason)
      ElMessage.success('AI 建议已驳回')
      await ctx.loadNodePackage(ctx.activeNodeId.value)
    } finally {
      ctx.actionLoading.value = false
    }
  }

  const handleConfirmEvidence = async (evidence: EvidenceLink) => {
    if (!ctx.ensureWritableNode()) return
    ctx.actionLoading.value = true
    try {
      const res = await confirmNodeEvidenceLinkApi(
        ctx.activeProjectId.value,
        ctx.activeNodeId.value,
        evidence.id,
        { comment: '监检人员确认采用该证据。' },
        { etag: ctx.etag() }
      )
      if (!res) {
        ctx.showActionError('证据确认失败，请刷新后重试。')
        return
      }
      ElMessage.success('证据已确认')
      await ctx.loadNodePackage(ctx.activeNodeId.value, { silent: true })
    } finally {
      ctx.actionLoading.value = false
    }
  }

  const handleRejectEvidence = async (evidence: EvidenceLink) => {
    if (!ctx.ensureWritableNode()) return
    const reason = await pickReason({
      title: '不采用该证据',
      message: '请选择不采用的原因，会写入该证据的人工备注并用于证据抽取的纠正。',
      reasons: EVIDENCE_REJECT_REASONS,
      allowNote: true,
      confirmText: '确认不采用'
    })
    if (!reason) return
    ctx.actionLoading.value = true
    try {
      const res = await rejectNodeEvidenceLinkApi(
        ctx.activeProjectId.value,
        ctx.activeNodeId.value,
        evidence.id,
        {
          comment: reason.note ? `${reason.label}：${reason.note}` : reason.label,
          reasonCode: reason.code
        },
        { etag: ctx.etag() }
      )
      if (!res) {
        ctx.showActionError('证据不采用失败，请刷新后重试。')
        return
      }
      ElMessage.success('已标记为不采用')
      await ctx.loadNodePackage(ctx.activeNodeId.value, { silent: true })
    } finally {
      ctx.actionLoading.value = false
    }
  }

  /** 「据此退回补正」：把发现填进退回原因，退回时带上 finding id 与建议动作。 */
  const handleReturnCorrectionFromFinding = (finding: WorkbenchAiFinding) => {
    if (!ctx.ensureWritableNode()) return
    ctx.pendingCorrectionFinding.value = finding
    ctx.correctionReason.value =
      `${finding.title}${finding.description ? `：${finding.description}` : ''}`.slice(0, 500)
    ctx.activeSideTab.value = 'opinion'
    ElMessage.info('已按该条发现填入退回原因，请核对后点击「退回补正」')
  }

  const handleReturnCorrection = async () => {
    if (!ctx.ensureWritableNode()) return
    if (!ctx.correctionReason.value.trim()) {
      ElMessage.warning('请填写退回补正原因')
      return
    }
    const submittedBindingIds = ctx.submittedBindingIds()
    if (!submittedBindingIds.length) {
      ElMessage.warning('当前节点没有可退回的已提交资料')
      return
    }
    const confirmed = await ctx.confirmIrreversibleAction({
      title: '退回补正',
      message: `将退回 ${submittedBindingIds.length} 份已提交资料并通知施工方整改，节点状态转为「需补正」。确认退回？`,
      confirmText: '确认退回'
    })
    if (!confirmed) return
    ctx.actionLoading.value = true
    try {
      const pending = ctx.pendingCorrectionFinding.value
      const res = await returnCorrectionApi(
        ctx.activeProjectId.value,
        ctx.activeNodeId.value,
        {
          reason: ctx.correctionReason.value.trim(),
          bindingIds: submittedBindingIds,
          evidenceLinkIds: ctx.evidenceLinkIds(),
          sourceFindingIds: pending ? [pending.id] : undefined,
          suggestedAction: pending?.suggestedAction || undefined
        },
        { etag: ctx.etag() }
      )
      if (!res) {
        ctx.showActionError('退回补正失败，请检查补正原因和节点权限。')
        return
      }
      ElMessage.success('已退回施工方补正')
      ctx.pendingCorrectionFinding.value = undefined
      await ctx.loadProjectBundle()
    } finally {
      ctx.actionLoading.value = false
    }
  }

  /** P9 R4：工程级结果表点"查看节点"→ 切到该节点（与左侧树点选同一路径）。 */
  const handleProjectAnalysisSelectNode = async (nodeId: number) => {
    const node = ctx.findTreeNode(nodeId)
    if (!node) {
      ElMessage.warning(`当前项目树里没有节点 ${nodeId}`)
      return
    }
    await ctx.selectNode(node)
  }

  return {
    handleProjectAnalysisSelectNode,
    handleAdoptAiSuggestion,
    handleRejectAiSuggestion,
    handleConfirmEvidence,
    handleRejectEvidence,
    handleReturnCorrectionFromFinding,
    handleReturnCorrection
  }
}
