import type { RoleCode } from '@/types/aicheck'

export const genericRoleContent = (role?: RoleCode) => {
  const reviewDetails = role === 'inspection' || role === 'admin'
  return {
    reviewDetails,
    intro:
      role === 'contractor'
        ? '查看资料要求与审查意见，按意见准备补充资料。'
        : role === 'owner'
          ? '查看资料提交进度、审查发现与已保存的人工意见。'
          : '核对资料要求、审查发现与引用原文。',
    navigation: [
      { subpage: 'overview', label: '项目总览', hint: '选择项目与查看项目状态' },
      { subpage: 'requirements', label: '资料进度', hint: '各节点的资料要求与提交进度' },
      { subpage: 'findings', label: '审查发现', hint: '查看发现、引用资料与人工意见' },
      ...(reviewDetails
        ? [
            { subpage: 'evidence', label: '引用资料', hint: '查看发现引用的原文' },
            { subpage: 'human', label: '待确认发现', hint: '查看尚未处理的发现' }
          ]
        : [])
    ]
  }
}
