/**
 * 后台的**唯一**一棵菜单树。
 *
 * ## 为什么要统一
 *
 * 之前每个后台页面各自维护一份菜单和根名字，实测下来是这样的：
 *
 *     停在 /admin/*        根 = 「后台管理功能」  基础管理 / 规则与业务配置 / 知识与审计
 *     点进 AI 知识库管理    根 = 「AI 知识库管理」 只剩一个「知识库管理」分组
 *     再进知识网络          根 = 「AI 知识库」     又换一套
 *
 * **同一个后台，菜单换了三副面孔**，而且进了知识库之后 admin 那三个分组
 * 整个消失——人回不去，只能靠浏览器后退。菜单是导航，导航自己会跳变的话，
 * 用户就失去了对「我在哪、还能去哪」的判断。
 *
 * 现在只有这一份定义：知识库是后台的一个分组，不是另一棵树。
 * 页面只管传 `activeRoute`，其余都从这里来。
 *
 * ## 改这份文件时注意
 *
 * - `route` 必须是真实存在的路由。写了不存在的路径，点击会静默留在原地
 *   ——这个坑本项目踩过（选择器写了而元素不存在，滚动静默失败）。
 * - 分组的 `meta`（「3 页」）是给人看的计数，**由代码算出来**，
 *   不要手写：手写的数字迟早和 items 对不上，而没人会去核对它。
 */

export type AdminMenuItem = {
  index: string
  label: string
  badge?: string
  tone?: 'blue' | 'green' | 'orange' | 'red'
  route: string
  hint?: string
}

export type AdminMenuSection = {
  title: string
  meta: string
  items: AdminMenuItem[]
}

/** 后台根节点名。三个页面原来写了三个不同的名字。 */
export const ADMIN_MENU_ROOT = '后台管理功能'

/** 左侧栏标题。原来是「后台菜单 / 知识库菜单 / 知识资产」三种。 */
export const ADMIN_MENU_TITLE = '后台菜单'

/* 边界说明。说的是**同一个后台的边界**，不该随页面改口径——
 * 原来是「后台边界·无业务办理」「后台边界·只管理」「知识网络边界·可追溯」，
 * 同一件事三种说法，读的人会以为这几页的权限范围真的不同。 */
export const ADMIN_BOUNDARY_TITLE = '后台边界'
export const ADMIN_BOUNDARY_BADGE = '无业务办理'

const SECTION_DEFS: Array<{ title: string; items: AdminMenuItem[] }> = [
  {
    title: '基础管理',
    items: [
      { index: 'a01', label: '项目管理', badge: '多项目', tone: 'blue', route: '/admin/projects' },
      { index: 'a02', label: '组织用户', route: '/admin/org' },
      {
        index: 'a03',
        label: '权限与节点',
        badge: '动作级',
        tone: 'blue',
        route: '/admin/permission'
      }
    ]
  },
  {
    title: '规则与业务配置',
    items: [
      {
        index: 'a04',
        label: '业务类型管理',
        badge: '复用',
        tone: 'green',
        route: '/admin/business-packs'
      },
      {
        index: 'a05',
        label: 'AI 业务规则与流程',
        badge: '发布',
        tone: 'blue',
        route: '/admin/rules'
      },
      {
        index: 'a06',
        label: '业务资料审查点',
        badge: '打靶',
        tone: 'orange',
        route: '/admin/material-review-points'
      },
      {
        index: 'a07',
        label: 'Prompt 模板管理',
        badge: 'Prompt',
        tone: 'blue',
        route: '/admin/prompt-templates'
      },
      {
        index: 'a08',
        label: '报告模板管理',
        badge: '报告',
        tone: 'green',
        route: '/admin/report-templates'
      },
      {
        index: 'a09',
        label: '细项配置',
        badge: '字段',
        tone: 'orange',
        route: '/admin/fine-config'
      }
    ]
  },
  {
    /* 知识库并进来，不再是另一棵树。
     * 原先点「AI 知识库管理」会把整棵树换掉，admin 的分组全部消失。 */
    title: 'AI 知识库',
    items: [
      {
        index: 'k01',
        label: '知识库总览',
        badge: '运行',
        tone: 'blue',
        route: '/knowledge/overview'
      },
      {
        index: 'k02',
        label: '标准规范库',
        badge: '标准',
        tone: 'green',
        route: '/knowledge/sources'
      },
      {
        index: 'k03',
        label: '项目文件知识库',
        badge: '项目',
        tone: 'blue',
        route: '/knowledge/files'
      },
      {
        index: 'k04',
        label: 'OCR/向量任务中心',
        badge: '任务',
        tone: 'orange',
        route: '/knowledge/tasks'
      },
      {
        index: 'k05',
        label: '监检业务判断规则管理',
        badge: '规则',
        tone: 'blue',
        route: '/knowledge/rules'
      },
      {
        index: 'k06',
        label: '知识检索测试',
        badge: '测试',
        tone: 'blue',
        route: '/knowledge/retrieval'
      },
      {
        index: 'k07',
        label: '知识网络',
        badge: '图谱',
        tone: 'green',
        route: '/knowledge/network'
      },
      {
        index: 'k08',
        label: '推理链路历史日志',
        badge: '日志',
        tone: 'green',
        route: '/knowledge/reasoning'
      },
      {
        index: 'k09',
        label: '多 LLM 反馈对比',
        badge: '评估',
        tone: 'green',
        route: '/knowledge/compare'
      },
      { index: 'k10', label: '知识库配置', badge: '策略', tone: 'blue', route: '/knowledge/config' }
    ]
  },
  {
    title: '运行与审计',
    items: [
      {
        index: 'a10',
        label: '联调清单',
        badge: '对账',
        tone: 'orange',
        route: '/admin/integration'
      },
      { index: 'a11', label: '审计日志', badge: '审计', tone: 'blue', route: '/admin/audit' }
    ]
  }
]

/** 分组页数由 items 算出来——手写的数字迟早和实际对不上，而没人会去核对。 */
export const ADMIN_MENU_SECTIONS: AdminMenuSection[] = SECTION_DEFS.map((section) => ({
  title: section.title,
  meta: `${section.items.length} 页`,
  items: section.items
}))

/** 当前路径属于哪个菜单项。用于高亮，取最长匹配以免 /admin 命中所有子页。 */
export const findAdminMenuItem = (path: string): AdminMenuItem | undefined => {
  const clean = String(path || '').split(/[?#]/, 1)[0]
  let best: AdminMenuItem | undefined
  for (const section of ADMIN_MENU_SECTIONS) {
    for (const item of section.items) {
      if (clean === item.route || clean.startsWith(`${item.route}/`)) {
        if (!best || item.route.length > best.route.length) best = item
      }
    }
  }
  return best
}

/** 给 StaticPageShell 的菜单：标出当前项。 */
export const buildAdminMenuSections = (activeRoute: string): AdminMenuSection[] => {
  const active = findAdminMenuItem(activeRoute)
  return ADMIN_MENU_SECTIONS.map((section) => ({
    ...section,
    items: section.items.map((item) => ({
      ...item,
      active: active ? item.index === active.index : false
    }))
  }))
}
