const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** Replace source tokens once, so translated labels and retained identifiers stay intact. */
export const createTechnicalTextFormatter = (
  labels: Record<string, string>,
  phrases: Record<string, string>,
  resolveLabel: (value: string, fallback: string) => string
) => {
  const replacements = {
    ...Object.fromEntries(
      Object.entries(labels).filter(
        ([token, label]) => token.length >= 4 && label !== token && /[_@.-]|[A-Z]/.test(token)
      )
    ),
    ...phrases
  }
  const alternatives = Object.keys(replacements)
    .sort((a, b) => b.length - a.length)
    .map((token) => {
      const escaped = escapeRegExp(token)
      return /^[a-z0-9_.@-]+$/i.test(token)
        ? `(?<![A-Za-z0-9_.@-])${escaped}(?![A-Za-z0-9_.@-])`
        : escaped
    })
  const pattern = new RegExp(
    [...alternatives, '\\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\\b', '\\b[a-z]+(?:[._-][a-z0-9]+)+\\b'].join(
      '|'
    ),
    'g'
  )
  return (value: unknown, fallback = '-') => {
    const raw = String(value ?? '').trim()
    if (!raw) return fallback
    if (phrases[raw]) return phrases[raw]
    const direct = resolveLabel(raw, raw)
    if (direct !== raw) return direct
    return raw.replace(pattern, (token: string, offset: number) => {
      // Already explained references such as “服务地址（AICHECK_OCR_BASE_URL）”.
      if (
        /[\u3400-\u9fff][（(]$/.test(raw.slice(0, offset)) &&
        /^[）)]/.test(raw.slice(offset + token.length))
      ) {
        return token
      }
      return replacements[token] || resolveLabel(token, token)
    })
  }
}
