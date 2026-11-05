/** 使用帮助的内容结构（2026-11-04）。
 *
 * 每个角色一份：几件常办的事，每件事一张真实截图（编号圈和步骤对应）、
 * 两三步操作、一个「带我去」——关掉帮助、跳到页面上那一块并高亮。
 *
 * 写内容时照抄界面上的按钮和标题文字；施工方、无损检测、建设方三份不出现
 * 「AI」「人工智能」（见 utils/reviewerWording.ts 的约定）。 */

export type GuideRole = 'inspection' | 'contractor' | 'ndt' | 'owner' | 'admin'

/** 页面上一块区域：元素上写着 data-guide="<target>"。 */
export type GuideSpot = {
  target: string
  /** 「带我去」按钮上的字：照着要去的那一块的标题写，例如「去「待提交」」「打开「规则升级」页」 */
  label?: string
  /** 高亮时旁边那句话 */
  hint: string
  /** 不写就留在当前页面（工作台类角色就一个页面） */
  path?: string
  /** 这块现在没显示时说什么，例如「目前没有被退回的资料」 */
  emptyHint?: string
}

/** 截图上的编号圈，位置按截图宽高的百分比。 */
export type GuideMarker = { n: number; x: number; y: number }

export type GuideImage = {
  src: string
  alt: string
  device: 'phone' | 'desktop'
  markers?: GuideMarker[]
}

export type GuideTask = {
  id: string
  title: string
  /** 一句话说这件事是干什么的 */
  summary: string
  /** 第 n 步对应截图上的编号 n */
  steps: string[]
  image?: GuideImage
  jump?: GuideSpot
}

export type RoleGuide = {
  role: GuideRole
  roleLabel: string
  intro: string
  /** 「开始引导」依次高亮的几块，都在这个角色的首页上 */
  tour: GuideSpot[]
  tasks: GuideTask[]
  faq: Array<{ q: string; a: string }>
}
