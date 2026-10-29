/** Counts describe stored records, not an assumed one-vector-per-chunk completion rate. */
export const indexRecordCount = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null

export const indexCountScale = (
  libraries: ReadonlyArray<{ chunkCount?: unknown; vectorCount?: unknown }>
) =>
  Math.max(
    1,
    ...libraries.flatMap((row) => [
      indexRecordCount(row.chunkCount) ?? 0,
      indexRecordCount(row.vectorCount) ?? 0
    ])
  )

export const indexCountWidth = (value: unknown, scale: number) => {
  const count = indexRecordCount(value)
  return count === null ? null : Math.min(100, (count / Math.max(1, scale)) * 100)
}
