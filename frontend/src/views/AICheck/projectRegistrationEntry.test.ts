import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const read = (relative: string) =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8')

const adminOverview = read('./AdminOverview.vue')
const contracts = (await import('../../types/aicheck')) as Record<string, unknown>

/* 标签在 DOM 中的位置决定抽屉是否可见；仅仅存在同名组件不够。
   管理员从“项目管理”点进来时，组织用户标签页不会渲染。 */
const tabsStart = adminOverview.indexOf('<ElTabs')
const tabsEnd = adminOverview.indexOf('</ElTabs>', tabsStart)
const registrationDrawerStart = adminOverview.indexOf(
  '<ElDrawer',
  adminOverview.indexOf('v-model="projectRegistrationVisible"') - 80
)

assert.ok(tabsStart >= 0 && tabsEnd > tabsStart, '找不到管理员页签容器')
assert.ok(registrationDrawerStart > tabsEnd, '注册链接抽屉必须在所有 ElTabPane 外部')
assert.match(adminOverview, /<ProjectRegistrationPanel/, '管理员端没有挂载注册链接面板')
assert.match(
  adminOverview,
  /v-model="projectRegistrationVisible"/,
  '管理员端注册链接抽屉没有受可见状态控制'
)

/* 项目负责人资格由后端上下文授权。这个状态机同时守住初次打开与授权被收回：
   已经打开的抽屉不能因项目切换或权限刷新而继续保留旧项目。 */
assert.equal(
  typeof contracts.projectRegistrationDrawerStateFor,
  'function',
  '缺少注册链接抽屉的授权状态机'
)
const projectRegistrationDrawerStateFor = contracts.projectRegistrationDrawerStateFor as (
  canManageRegistration: boolean,
  target?: { id: string; name: string }
) => { visible: boolean; target?: { id: string; name: string } }

const authorized = projectRegistrationDrawerStateFor(true, { id: 'P-LEADER', name: '负责人项目' })
assert.deepEqual(authorized, {
  visible: true,
  target: { id: 'P-LEADER', name: '负责人项目' }
})

const revoked = projectRegistrationDrawerStateFor(false, authorized.target)
assert.deepEqual(revoked, { visible: false, target: undefined })
assert.deepEqual(projectRegistrationDrawerStateFor(false, undefined), {
  visible: false,
  target: undefined
})

console.log('project registration entry behavior contract passed')
