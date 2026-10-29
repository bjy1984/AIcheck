import type { NodeFileBinding, RectificationItem } from '@/types/aicheck'

export const correctionSubmissionCandidates = (
  bindings: NodeFileBinding[],
  rectification?: RectificationItem,
  preferredIds: string[] = []
) =>
  bindings.filter(
    (binding) =>
      (!rectification || binding.nodeId === rectification.nodeId) &&
      (preferredIds.includes(binding.id) ||
        rectification?.bindingIds?.includes(binding.id) ||
        binding.bindingStatus === '需补正' ||
        (binding.bindingStatus === '草稿挂载' && binding.usage === '补正附件'))
  )
