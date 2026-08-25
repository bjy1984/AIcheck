const decodeEntities = (value: string) =>
  value
    .replace(/&nbsp;/gi, ' ')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'")
    .replace(/&amp;/gi, '&')

const plainCellText = (value: string) =>
  decodeEntities(
    value
      .replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1>/gi, '')
      .replace(/<br\s*\/?\s*>/gi, ' ')
      .replace(/<[^>]+>/g, '')
  )
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\|/g, '｜')

const htmlTableToMarkdown = (table: string) => {
  const rows = Array.from(table.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi))
    .map((row) =>
      Array.from(row[1].matchAll(/<t[hd]\b[^>]*>([\s\S]*?)<\/t[hd]>/gi)).map((cell) =>
        plainCellText(cell[1])
      )
    )
    .filter((row) => row.length)
  if (!rows.length) return plainCellText(table)
  const width = Math.max(...rows.map((row) => row.length))
  const normalized = rows.map((row) => [
    ...row,
    ...Array.from({ length: width - row.length }, () => '')
  ])
  const header = normalized[0].map((cell, index) => cell || `列${index + 1}`)
  const line = (cells: string[]) => `| ${cells.join(' | ')} |`
  return [line(header), line(header.map(() => '---')), ...normalized.slice(1).map(line)].join('\n')
}

/**
 * 把 MinerU Markdown 中混入的 HTML 表格和相对图片引用转换成安全展示文本。
 *
 * 只接收并返回字符串，因此不会触碰 evidenceLinkId、documentVersionId、pageNo 或 bbox。
 * HTML 永远不会交给 v-html：表格转为 GFM Markdown，其余标签仅保留纯文本。
 */
export const normalizeMineruMarkdownForDisplay = (value: string) =>
  String(value || '')
    .replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1>/gi, '')
    .replace(/<table\b[^>]*>[\s\S]*?<\/table>/gi, (table) => `\n\n${htmlTableToMarkdown(table)}\n\n`)
    .replace(/!\[([^\]]*)\]\((?:\.\/)?images\/[^)]+\)/gi, (_match, alt: string) =>
      alt.trim()
        ? `（${alt.trim()}；OCR图片片段请查看左侧原文预览）`
        : '（OCR图片片段请查看左侧原文预览）'
    )
    .replace(/<br\s*\/?\s*>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
