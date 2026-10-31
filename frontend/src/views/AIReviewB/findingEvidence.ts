// 审查事项没有附原文引用时，到底是怎么回事。
//
// 原来一律写「暂未附原文」「这项没有附上原文引用，还需要补充或核对依据」，三种情况混成一句：
//   1. 缺项类发现（「缺少设计特性表」）：缺的东西本来就没有原文可引，依据是该节点的审查要求。
//      生产里节点 12 的三条里有两条是这种，却被写得像是 AI 偷懒没给证据；
//   2. AI 给了引用，但系统逐字核对时在资料里没找到，被整条丢掉了（校验失败码 EVIDENCE_*）——
//      这种要明确告诉监检「别照它的引用采信」；
//   3. AI 没给任何引用的普通结论——暂时不能直接采信。

export type EvidenceGap = '' | 'absence' | 'citation_failed' | 'no_citation'

// 校验没通过的引用：引文在原文里找不到、文件不在本节点、缺元数据、引用格式不对
const CITATION_FAILURE_CODE = /^EVIDENCE_(?:QUOTE_NOT_VERBATIM|FILE_|METADATA_|REF_INVALID)/

// 缺项类说法。只用来改措辞，不改任何判定，所以宁可宽松。
const ABSENCE_WORDING =
  /缺少|缺失|缺乏|未提供|未见|未上传|没有提供|不齐全|无法(?:核实|核查|核对|比对|完成)/

const failureCodes = (finding: Record<string, unknown>): string[] => {
  const codes: string[] = []
  for (const claim of Array.isArray(finding.unsupportedClaims) ? finding.unsupportedClaims : []) {
    if (typeof claim === 'string') codes.push(claim)
  }
  for (const failure of Array.isArray(finding.validationFailures)
    ? finding.validationFailures
    : []) {
    const code = (failure as { code?: unknown } | null)?.code
    if (typeof code === 'string') codes.push(code)
  }
  return codes
}

export const evidenceGapOf = (finding: Record<string, unknown>): EvidenceGap => {
  if (Array.isArray(finding.evidenceRefs) && finding.evidenceRefs.length) return ''
  if (failureCodes(finding).some((code) => CITATION_FAILURE_CODE.test(code)))
    return 'citation_failed'
  const text = `${finding.title ?? ''}${finding.description ?? ''}`
  return ABSENCE_WORDING.test(text) ? 'absence' : 'no_citation'
}

export const evidenceGapSummary: Record<Exclude<EvidenceGap, ''>, string> = {
  absence: '（缺项，没有对应原文）',
  citation_failed: '（引用未通过核对）',
  no_citation: '（暂未附原文）'
}

export const evidenceGapNotice: Record<Exclude<EvidenceGap, ''>, string> = {
  absence:
    '这是缺项类的发现：缺的资料本来就没有原文可引，依据是该节点的审查要求（见下方规则依据）。请对照「本节点所需资料」确认是不是真的缺；如果资料其实已经上传，说明 AI 没找到，请到资料里补挂或核对。',
  citation_failed:
    'AI 给出了原文引用，但系统逐字核对时没能在资料里找到，所以没有附上。不要照它的引用采信，请自己到资料里核对。',
  no_citation: 'AI 没有给出可核对的原文引用，这条判断暂时不能直接采信，请到资料里自己核对。'
}
