import type { SupplementRequirementInput } from '@/api/aicheck'
import type { NodeRequirementMatch } from '@/types/aicheck'

export type ReturnableBinding = {
  id: string
  fileName?: string
  bindingStatus: string
  materialTypeName?: string | null
  materialCategory?: string | null
}

export type ReturnCorrectionDraft = {
  mode: 'return_correction' | 'supplement_request'
  reason: string
  selectedBindingIds: string[]
  selectedRequirementIds: string[]
  manualRequirementsText: string
  evidenceLinkIds: string[]
}

/** 缺失资料的可读名称：优先中文名，实在没有才退回原始码。
 *
 * 对话框显示与提交载荷必须用同一套口径——只改显示的那一层，
 * 生成的单子里仍然是码，施工方照样看不懂。
 */
export const requirementDisplayName = (item: NodeRequirementMatch): string => {
  const candidate = item as NodeRequirementMatch & {
    materialTypeName?: string
    reviewContent?: string
  }
  return (
    String(candidate.materialTypeName || '').trim() ||
    String(candidate.reviewContent || '').trim() ||
    String(candidate.name || '').trim() ||
    String(candidate.materialTypeCode || '').trim() ||
    '未命名资料'
  )
}

export const createReturnCorrectionDraft = (
  bindings: ReturnableBinding[],
  missingRequirements: NodeRequirementMatch[],
  defaultOpinion: string
): ReturnCorrectionDraft => ({
  mode: bindings.length ? 'return_correction' : 'supplement_request',
  reason: defaultOpinion.trim(),
  selectedBindingIds: bindings.map((item) => item.id),
  selectedRequirementIds: missingRequirements.map((item) => item.id),
  manualRequirementsText: '',
  evidenceLinkIds: []
})

export const buildReturnCorrectionPayload = (
  draft: ReturnCorrectionDraft,
  bindings: ReturnableBinding[],
  missingRequirements: NodeRequirementMatch[]
) => {
  const reason = draft.reason.trim()
  if (!reason) throw new Error('请填写具体补正原因和处理要求')

  const allowedBindingIds = new Set(bindings.map((item) => item.id))
  const bindingIds = draft.selectedBindingIds.filter((id) => allowedBindingIds.has(id))
  const missingById = new Map(missingRequirements.map((item) => [item.id, item]))
  const supplementRequirements: SupplementRequirementInput[] = draft.selectedRequirementIds
    .map((id) => missingById.get(id))
    .filter((item): item is NodeRequirementMatch => Boolean(item))
    // name 要写**能读懂的名字**，不是资料类型码。
    //
    // 实操验证：生成的补充单里 supplementRequirements[].name 是 null，
    // 只剩 materialTypeCode——施工方打开这张单子，看到的还是 design_license。
    // 界面上刚把码换成中文名，这里不跟上，等于只改了监检自己看的那一屏。
    .map((item) => ({
      id: item.id,
      source: 'system' as const,
      name: requirementDisplayName(item)
    }))
  const manualItems = draft.manualRequirementsText
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean)
    .map((name, index) => ({
      id: `MANUAL-${index + 1}`,
      source: 'manual' as const,
      name
    }))
  supplementRequirements.push(...manualItems)

  if (draft.mode === 'return_correction' && !bindingIds.length) {
    throw new Error('至少选择一份需要退回修改的资料')
  }
  if (draft.mode === 'supplement_request' && !supplementRequirements.length) {
    throw new Error('至少选择或填写一项需要提交的资料')
  }

  return {
    mode: draft.mode,
    reason,
    opinion: reason,
    bindingIds: draft.mode === 'return_correction' ? bindingIds : [],
    evidenceLinkIds: draft.evidenceLinkIds,
    supplementRequirements: draft.mode === 'supplement_request' ? supplementRequirements : []
  }
}

export type ReturnCorrectionRequest = ReturnType<typeof buildReturnCorrectionPayload>
