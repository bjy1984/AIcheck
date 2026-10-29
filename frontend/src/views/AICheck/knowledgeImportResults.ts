export type ImportSkipped = { fileName: string; reason: string }
export type ImportFileResult = ImportSkipped & { status: '已导入' | '未导入' }

// The import APIs identify skipped uploads by display filename. Require unique names
// within a batch so a partial retry never accidentally resubmits a successful file.
export const hasDuplicateImportNames = <T>(rows: T[], getName: (row: T) => string) => {
  const names = rows.map((row) => getName(row).trim())
  return new Set(names).size !== names.length
}

export const buildImportResults = <T>(
  rows: T[],
  skipped: ImportSkipped[],
  getName: (row: T) => string
): ImportFileResult[] =>
  rows.map((row) => {
    const fileName = getName(row).trim()
    const failure = skipped.find((item) => item.fileName === fileName)
    return {
      fileName,
      status: failure ? '未导入' : '已导入',
      reason: failure?.reason || '已写入，后续处理状态可在任务中心查看。'
    }
  })

export const getImportSkippedFromError = (error: unknown): ImportSkipped[] => {
  const e = error as
    | {
        data?: { skipped?: ImportSkipped[]; data?: { skipped?: ImportSkipped[] } }
        response?: { data?: { data?: { skipped?: ImportSkipped[] } } }
      }
    | undefined
  return e?.response?.data?.data?.skipped || e?.data?.data?.skipped || e?.data?.skipped || []
}
