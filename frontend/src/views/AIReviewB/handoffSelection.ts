import type { Handoff } from '@/api/aicheck/reviewHandoffs'
import type { ReviewDocumentSelection } from '@/api/aicheck/reviewDocuments'
import { handoffBelongsTo, handoffReviewBlock } from './handoffPresentation'

export function selectionWithHandoff(
  record: Handoff,
  projectId: string,
  runId: string,
  selection: ReviewDocumentSelection | null
): ReviewDocumentSelection {
  if (!handoffBelongsTo(record, projectId, runId) || handoffReviewBlock(record))
    throw new Error('交接来源或接收任务已变化，请重新加载并核验。')
  const latest = record.verifications?.at(-1)
  if (
    record.verification?.status !== 'verified' ||
    !latest ||
    latest.outcome !== 'verified' ||
    record.verification.latestVerificationId !== latest.id
  )
    throw new Error('这份交接还没有有效的人工核验，暂不能用于下次审查。')
  if (
    !record.draft.subject.eventId ||
    !record.draft.evidenceRefs.length ||
    record.validation.evidenceLocationCheck?.status !== 'locations_found'
  )
    throw new Error('请先补齐事件与可定位的原文。工作请求不能直接当作审查证据。')
  const next: ReviewDocumentSelection = selection
    ? JSON.parse(JSON.stringify(selection))
    : { versions: [], reviewMode: 'gap_precheck' }
  const subject = record.draft.subject as typeof record.draft.subject & { eventId: string }
  if (
    next.handoffSelection &&
    (['objectType', 'objectId', 'eventId', 'repairRound'] as const).some(
      (key) => next.handoffSelection!.subject[key] !== subject[key]
    )
  )
    throw new Error('已选交接属于另一个对象或事件，请先移除旧选择。')
  const mapped = next.conditionObjectMapping?.selection.subject
  if (mapped && (mapped.objectType !== subject.objectType || mapped.objectId !== subject.objectId))
    throw new Error('交接对象与已选规则试跑对象不同，请先核对对象。')
  for (const reference of record.draft.evidenceRefs) {
    const versionId = reference.documentVersionId
    const documents =
      record.evidenceDocuments?.filter((item) => item.documentVersionId === versionId) || []
    if (
      !versionId ||
      documents.length !== 1 ||
      !Number.isSafeInteger(reference.pageNo) ||
      reference.pageNo! < 1
    )
      throw new Error('交接原文的固定版本或页码不完整，请重新加载。')
    const existing = next.versions.find((item) => item.versionId === versionId)
    if (existing && existing.documentId !== documents[0].documentId)
      throw new Error('文件身份不一致，请重新选择资料。')
    if (
      existing?.pageRange &&
      (reference.pageNo! < existing.pageRange.start || reference.pageNo! > existing.pageRange.end)
    )
      throw new Error('交接引用不在已选页码范围，请先调整文件页码。')
    if (!existing) {
      if (mapped)
        throw new Error('加入交接原文会改变试跑资料，请先移除对象选择，再用完整资料重新试跑。')
      next.versions.push({
        versionId,
        documentId: documents[0].documentId,
        fileName: documents[0].fileName || versionId
      })
    }
  }
  const items = (next.handoffSelection?.items || []).filter((item) => item.handoffId !== record.id)
  if (items.length >= 20) throw new Error('一次最多选择20份交接，请先移除部分选择。')
  next.handoffSelection = {
    subject: { ...subject },
    confirmedSameObject: true,
    items: [...items, { handoffId: record.id, verificationId: latest.id }]
  }
  return next
}
