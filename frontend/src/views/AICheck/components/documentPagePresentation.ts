import type { OcrStructuredView } from '@/api/aicheck'

const kinds: Record<string, string> = {
  pqr: '焊接工艺评定报告',
  pwps: '预焊接工艺规程',
  wps: '焊接工艺规程／工艺卡',
  welding_record: '焊接记录',
  rt_report: '射线检测报告',
  ut_report: '超声检测报告'
}
export type DocumentPageRow = { pageNo: number; label: string; identified: boolean }
export function documentPageRows(
  view: OcrStructuredView | undefined,
  versionId: string | undefined
): DocumentPageRow[] {
  if (
    !versionId ||
    view?.documentVersionId !== versionId ||
    !Array.isArray(view.pageClassifications)
  )
    return []
  const pages = new Map<number, NonNullable<OcrStructuredView['pageClassifications']>>()
  for (const row of view.pageClassifications) {
    if (!row || !Number.isInteger(row.pageNo) || row.pageNo < 1) continue
    pages.set(row.pageNo, [...(pages.get(row.pageNo) || []), row])
  }
  return [...pages]
    .sort(([a], [b]) => a - b)
    .map(([pageNo, matches]) => {
      const row = matches[0]
      const identified =
        matches.length === 1 &&
        row.status === 'identified' &&
        Object.prototype.hasOwnProperty.call(kinds, row.documentKind || '')
      return {
        pageNo,
        identified,
        label: identified
          ? kinds[row.documentKind!]
          : matches.length > 1 || row.status === 'ambiguous'
            ? '有多种资料标题，需要确认'
            : '还没确认这页是什么资料'
      }
    })
}
