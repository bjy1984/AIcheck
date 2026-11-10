/**
 * 核查结论表里「结论」一列的单元格，认出结论词就画成彩色胶囊（符合=绿、证据不足=琥珀、不符合=红）。
 * 一屏表格扫一眼就知道哪几项有问题；原来全是同样粗细的黑字。
 *
 * 只认「单元格以结论词开头，后面没有别的字、或紧跟标点/括号」：`证据不足（施工期只录在…）`
 * 画成胶囊加一行灰字；`符合要求`、`符合性检查` 这种以结论词为前缀的普通词不动。
 */
export type VerdictTone = 'success' | 'danger' | 'warning' | 'info'

export type VerdictInfo = { verdict: string; tone: VerdictTone; rest: string }

// 顺序要紧：「不符合」「未通过」必须排在「符合」「通过」前面，否则前缀会先匹配上后者
const VERDICTS: ReadonlyArray<readonly [string, VerdictTone]> = [
  ['不符合', 'danger'],
  ['未通过', 'danger'],
  ['证据不足', 'warning'],
  ['需人工确认', 'warning'],
  ['需补正', 'warning'],
  ['不适用', 'info'],
  ['符合', 'success'],
  ['通过', 'success']
]

const BOUNDARY = /^[\s（(:：，,;；—-]/

export const verdictOf = (text: string): VerdictInfo | null => {
  const value = String(text || '').trim()
  for (const [word, tone] of VERDICTS) {
    if (!value.startsWith(word)) continue
    const rest = value.slice(word.length)
    if (rest && !BOUNDARY.test(rest)) return null
    return { verdict: word, tone, rest: rest.replace(/^[\s:：，,;；—-]+/, '').trim() }
  }
  return null
}

/** 表头里写着「结论」或「判定」的列才按结论列处理，别的列里出现「符合」不画。 */
export const isVerdictColumn = (headerText: string) => /结论|判定/.test(headerText)
