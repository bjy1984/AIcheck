import type { ReviewDocumentSelection } from '@/api/aicheck/reviewDocuments'

type Version = ReviewDocumentSelection['versions'][number]

export const validDocumentPageRange = (range: Version['pageRange']) =>
  !range ||
  (Number.isSafeInteger(range.start) &&
    Number.isSafeInteger(range.end) &&
    range.start >= 1 &&
    range.end >= range.start)

export const cloneDocumentSelectionVersions = (versions: Version[]) =>
  versions.map((item) => ({
    ...item,
    ...(item.pageRange ? { pageRange: { ...item.pageRange } } : {})
  }))

export const documentSelectionPayload = (selection: ReviewDocumentSelection) => {
  if (selection.versions.some((item) => !validDocumentPageRange(item.pageRange)))
    throw new Error('页码范围无效，请检查起止页码。')
  const ranges = Object.fromEntries(
    selection.versions
      .filter((item) => item.pageRange)
      .map((item) => [item.versionId, { ...item.pageRange! }])
  )
  return {
    ...(selection.handoffSelection
      ? { handoffSelection: JSON.parse(JSON.stringify(selection.handoffSelection)) }
      : {}),
    ...(selection.conditionObjectMapping
      ? { conditionObjectMapping: JSON.parse(JSON.stringify(selection.conditionObjectMapping)) }
      : {}),
    inputDocumentVersionIds: selection.versions.map((item) => item.versionId),
    ...(Object.keys(ranges).length || selection.pageScopeExplicit
      ? { inputDocumentPageRanges: ranges }
      : {})
  }
}

export const documentPageLabel = (version: Version) =>
  version.pageRange ? `第 ${version.pageRange.start}–${version.pageRange.end} 页` : '整份文件'
