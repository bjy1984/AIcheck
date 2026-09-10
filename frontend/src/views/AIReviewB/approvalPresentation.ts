import type { ReviewApprovalCheck } from '@/types/ai-review-b'
export const approvalLabel = (row: ReviewApprovalCheck): string => {
  const role = /^r11_signature_(编制|审核|审批)(?:_unresolved)?$/.exec(row.code)?.[1]
  if (role) return `${role}签名记录`
  const labels: Record<string, string> = {
    r11_owner_reply: '建设单位批复',
    r11_owner_reply_scope_unresolved: '建设单位批复对应关系',
    r11_owner_approval_before_use: '批复与采用的先后顺序',
    r11_usage_inventory: '采用记录是否齐全且能一一对应',
    r11_approval_scope_incomplete: '本次核对的方案范围',
    r11_signature_source_or_role_ambiguous: '签名记录与签字角色'
  }
  return Object.hasOwn(labels, row.code) ? labels[row.code] : '签批核对事项'
}
export const approvalMessage = (row: ReviewApprovalCheck): string => {
  if (row.result === 'passed') return '这项记录核对一致；签名和批复效力仍需另行确认。'
  if (row.result === 'failed') {
    if (row.code === 'r11_owner_approval_before_use')
      return '记录显示先采用、后批复。请核对这次采用是否对应这份批复，再确认处理。'
    if (/^r11_signature_(编制|审核|审批)$/.test(row.code))
      return '记录明确标为未签名，请核对原文并确认是否需要补签。'
    if (row.code === 'r11_owner_reply')
      return '记录中的建设单位回覆为拒绝，请核对后续是否有新的有效批复。'
  }
  if (row.code === 'r11_usage_inventory')
    return '采用清单或记录还对不上，请检查漏项、重复项及清单来源。'
  if (row.code === 'r11_owner_approval_before_use')
    return '目前无法确认先后顺序，请核对时间精度、对应关系和原文来源。'
  return '这项还不能确定，请核对记录、对应关系和原文来源，不一定是缺文件。'
}
export const approvalStatus = (result?: string) =>
  result === 'passed' ? '记录核对一致' : result === 'failed' ? '发现问题' : '待核对'
