export const confidenceRatio = (value?: number | null): number | undefined => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return undefined
  const ratio = value > 1 && value <= 100 ? value / 100 : value
  return Math.min(1, Math.max(0, ratio))
}

export const formatConfidence = (value?: number | null, fallback = '-'): string => {
  const ratio = confidenceRatio(value)
  return ratio === undefined ? fallback : `${Math.round(ratio * 100)}%`
}
