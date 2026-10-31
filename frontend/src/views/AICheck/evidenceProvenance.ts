// 证据上的「已确认」标签，到底是谁确认的。
//
// 系统在资料上传后会按资料类别自动把它挂到对应节点（material_targeting），挂上去的证据
// 一律记成 manualStatus=confirmed、confirmedByName=「系统自动打靶」——这样正式审查才用得上它们。
// 界面却把这个状态直接写成绿色的「已确认」，于是「品牌推广手册」「焊接工艺卡」这类和本节点没什么关系
// 的文件也一排绿标，标签对监检来说没有任何信息量（生产实测：420 条确认、0 条驳回）。
// 这里按来源分开：人工确认的写「已确认 · 谁」，系统自动挂的写「系统挂接」并提示还没有人核对。
// 后端的 manualStatus 不动：它是正式审查的口径，改了会牵动别的东西。

export type EvidenceStatusSource = {
  manualStatus?: string
  manualStatusLabel?: string
  source?: string
  confirmedByName?: string
}

export const SYSTEM_CONFIRMER = '系统自动打靶'

export const isSystemLinked = (evidence: EvidenceStatusSource) =>
  evidence.manualStatus === 'confirmed' &&
  (evidence.source === 'material_targeting' || evidence.confirmedByName === SYSTEM_CONFIRMER)

export const evidenceStatusView = (
  evidence: EvidenceStatusSource
): { label: string; tagType: 'success' | 'warning' | 'info'; hint: string } => {
  if (evidence.manualStatus !== 'confirmed') {
    return {
      label: evidence.manualStatusLabel || evidence.manualStatus || '候选',
      tagType: 'warning',
      hint: '还没有人工确认，引用前请先核对原文。'
    }
  }
  if (isSystemLinked(evidence)) {
    return {
      label: '系统挂接',
      tagType: 'info',
      hint: '系统按资料类别自动挂到本节点，还没有人工核对。请对照原文确认它和本节点的要求相关。'
    }
  }
  const name = String(evidence.confirmedByName || '').trim()
  return {
    label: name ? `已确认 · ${name}` : '已确认',
    tagType: 'success',
    hint: '已由人工确认。'
  }
}
