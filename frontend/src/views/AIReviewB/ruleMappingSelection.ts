import type { ProjectRule, RuleTrialResult } from '@/api/aicheck/projectRules'
import type { ReviewDocumentSelection } from '@/api/aicheck/reviewDocuments'

export const mappingSelectionFromTrial = (
  rule: ProjectRule,
  result: RuleTrialResult,
  reviewMode: ReviewDocumentSelection['reviewMode'] = 'gap_precheck'
): ReviewDocumentSelection => {
  const snapshot = result.objectMappingSnapshot
  if (
    rule.status !== '已发布' ||
    !snapshot ||
    !result.bindingPlan ||
    !result.sourceSnapshotHash ||
    !result.sourceDocuments?.length ||
    !Number.isSafeInteger(result.ruleRevision)
  )
    throw new Error('请对已发布规则完成对象选择并重新试跑。')
  if (
    !snapshot.selection.confirmedSameObject ||
    result.sourceDocuments.some((item) => !item.documentId || !item.versionId)
  )
    throw new Error('对象选择或固定版本资料不完整，请重新试跑。')
  return JSON.parse(
    JSON.stringify({
      reviewMode,
      ...(result.sourcePageRanges != null ? { pageScopeExplicit: true } : {}),
      versions: result.sourceDocuments,
      conditionObjectMapping: {
        selection: snapshot.selection,
        ruleVersionId: rule.id,
        ruleRevision: result.ruleRevision,
        sourceSnapshotHash: result.sourceSnapshotHash
      }
    })
  )
}
