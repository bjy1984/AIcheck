/** 每个角色都有的几块：当前项目、账号菜单（2026-11-12）。
 * 单独一个文件：guideContent 和 guideContentStaff 都要用，放在任一边会循环引用。 */
import type { GuideSpot, GuideTask } from './guideTypes'

/* —— 每个角色都有的：切换项目、账号（2026-11-12 用户：新手引导每个角色都要、尽量全面） —— */

/** 引导第一步：当前项目 */
export const PROJECT_SPOT: GuideSpot = {
  target: 'topbar-project',
  hint: '左上角是你现在所在的项目。参加了好几个项目时，点项目名切换。'
}

/** 引导最后一步：账号菜单，以后忘了怎么用回这里 */
export const ACCOUNT_SPOT: GuideSpot = {
  target: 'topbar-user',
  hint: '右上角是你的账号。「使用帮助」随时能再看这份说明和引导，「修改密码」「退出登录」也在这里。'
}

export const ACCOUNT_TASK: GuideTask = {
  id: 'account',
  title: '修改密码、退出登录',
  summary: '账号相关的都在右上角。',
  steps: [
    '点右上角你的名字，打开账号菜单。',
    '「修改密码」：输入现在的密码和新密码（至少 6 位），点「保存新密码」。',
    '「退出登录」：在公用电脑上用完记得退出。',
    '忘了密码登不进来：请项目负责人或管理员帮你重置。'
  ],
  jump: { label: '去「账号菜单」', target: 'topbar-user', hint: '点你的名字打开账号菜单。' }
}

export const SWITCH_PROJECT_TASK: GuideTask = {
  id: 'switch-project',
  title: '切换项目',
  summary: '参加了好几个项目时，在左上角切换。',
  steps: [
    '点左上角的项目名，下拉里列出你参加的全部项目。',
    '选一个就切过去，页面上的资料、待办都换成那个项目的。',
    '列表里没有你要的项目：向那个项目的负责人要邀请链接，提交申请、审核通过后就会出现。'
  ],
  jump: { label: '去「当前项目」', target: 'topbar-project', hint: '点项目名可以切换项目。' }
}
