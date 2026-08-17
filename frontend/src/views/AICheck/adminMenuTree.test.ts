/**
 * 后台只能有一棵菜单树。
 *
 * ## 线上实测（2026-08-16，admin）
 *
 *     停在 /admin/*       根 = 「后台管理功能」  基础管理 / 规则与业务配置 / 知识与审计
 *     点进 AI 知识库管理   根 = 「AI 知识库管理」 只剩一个「知识库管理」分组
 *     再进知识网络         根 = 「AI 知识库」     又换一套
 *
 * 三个页面各自维护一份菜单和根名字，于是**同一个后台换了三副面孔**；
 * 更糟的是进了知识库之后 admin 那三个分组整个消失——人回不去，
 * 只能靠浏览器后退。
 *
 * 菜单是导航。**导航自己会跳变，用户就失去了「我在哪、还能去哪」的判断。**
 *
 * ## 判据
 *
 * - 三个页面共用同一份定义，谁都不许再写自己的
 * - 分组页数由 items 算出来，不许手写
 * - route 不重复；高亮取最长匹配
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import {
  ADMIN_MENU_ROOT,
  ADMIN_MENU_SECTIONS,
  buildAdminMenuSections,
  findAdminMenuItem
} from './adminMenuTree'

// 分组存在且知识库并入后台，不是另一棵树
const titles = ADMIN_MENU_SECTIONS.map((section) => section.title)
assert.ok(titles.includes('基础管理'))
assert.ok(titles.includes('规则与业务配置'))
assert.ok(titles.includes('AI 知识库'), '知识库要作为后台的一个分组')
assert.ok(titles.includes('运行与审计'))

// 页数由 items 算出——手写的数字迟早和实际对不上，而没人会去核对
for (const section of ADMIN_MENU_SECTIONS) {
  assert.equal(section.meta, `${section.items.length} 页`, `${section.title} 的页数与条目对不上`)
}

// route 不能重复：两个菜单项指向同一页，高亮会同时亮两处
const routes = ADMIN_MENU_SECTIONS.flatMap((section) => section.items.map((item) => item.route))
assert.equal(new Set(routes).size, routes.length, `菜单里有重复路由：${routes.join(', ')}`)

// 高亮取最长匹配，避免 /admin 命中所有子页
assert.equal(findAdminMenuItem('/knowledge/overview')?.label, '知识库总览')
assert.equal(findAdminMenuItem('/knowledge/network')?.label, '知识网络')
assert.equal(findAdminMenuItem('/admin/projects')?.label, '项目管理')
assert.equal(findAdminMenuItem('/admin/prompt-templates')?.label, 'Prompt 模板管理')
// 带查询串也要能认出来
assert.equal(findAdminMenuItem('/knowledge/files?tab=x')?.label, '项目文件知识库')
// 不属于后台的路径不该命中
assert.equal(findAdminMenuItem('/workbench/inspection'), undefined)

// 构建结果里当前项被标出，且只标一个
const built = buildAdminMenuSections('/knowledge/tasks')
const actives = built
  .flatMap((s) => s.items)
  .filter((item) => (item as { active?: boolean }).active)
assert.equal(actives.length, 1, '同一时刻只能有一个菜单项高亮')
assert.equal(actives[0].label, 'OCR/向量任务中心')

/* 三个页面都必须用这份定义——**只改一处等于没改**，
   这个形态在本轮已经出现过四次（自动展开、分数下限、镜像重建、取名优先级）。*/
const pages = ['AdminOverview.vue', 'KnowledgeOverview.vue', 'KnowledgeNetwork.vue']
for (const page of pages) {
  const sfc = readFileSync(fileURLToPath(new URL(`./${page}`, import.meta.url)), 'utf8')
  assert.ok(/from '\.\/adminMenuTree'/.test(sfc), `${page} 没有使用共享菜单树，它会再长出一棵`)
  assert.ok(/:menu-root="ADMIN_MENU_ROOT"/.test(sfc), `${page} 的根名字仍是硬写的`)
  assert.ok(!/const \w*[Mm]enuSections\w*Base = \[/.test(sfc), `${page} 还留着自己的菜单定义`)
}

// 根名字只有一个
assert.equal(ADMIN_MENU_ROOT, '后台管理功能')

console.log('Admin menu tree contract passed')
