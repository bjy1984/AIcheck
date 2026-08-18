/**
 * 参建单位与成员合并成一棵树；同一角色可以有多个负责人。
 *
 * ## 为什么合并
 *
 * 原先是上下两张表，靠 orgName 这串文字对应——**看不出某个成员属于
 * 哪个参建单位**，要自己拿组织名去另一张表里找。人一多就对不过来。
 *
 * ## 但不平铺成一张
 *
 * 单位有自己的类型和联系人，平铺之后这些要么消失、要么每行重复一遍。
 * 做成树是为了**保留两个层级，只是放进同一个视图**。
 *
 * ## 这次改动弄丢过功能
 *
 * 换布局时把「停用」和「删除」两个按钮一起弄丢了——**功能不会因为
 * 布局变了就该消失，而这种丢失没有任何报错**，只有类型检查偶然发现
 * 两个处理函数没人用了才暴露出来。所以这里逐个钉住。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const read = (relative: string) =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8')

const tree = read('./components/ProjectUnitMemberTree.vue')
const admin = read('./AdminOverview.vue')
const api = read('../../api/aicheck/index.ts')

// ---- 合并 ----

assert.match(admin, /ProjectUnitMemberTree/, '后台没有用合并后的树')
assert.match(admin, /参建单位与成员/, '标题还是分开的两块')

/* 原来的两张表不该再并存——留着的话就成了三个地方管同一批人。 */
assert.ok(
  !/content-position="left">参建单位<\/ElDivider>/.test(admin),
  '旧的参建单位表还在，和树并存'
)
assert.ok(!/content-position="left">成员授权<\/ElDivider>/.test(admin), '旧的成员授权表还在')

// 树要真的分层，不是把单位当成一行普通数据
assert.match(tree, /:tree-props="\{ children: 'children' \}"/, '没有用树结构')
assert.match(tree, /kind: 'unit' \| 'member'/, '没有区分单位行和成员行')

/* 挂不上单位的人必须单独列出来。只按单位分组的话他们会**消失**——
   而组织名写错、单位没登记，恰恰是最该被看到的情况。 */
assert.match(tree, /未归入参建单位/, '对不上单位的成员会消失')
assert.match(tree, /请核对组织名或补登参建单位/, '没说清楚为什么他们在这一组')

// ---- 原有功能一个都不能少 ----

for (const [action, label] of [
  ['edit', '编辑'],
  ['toggle-status', '停用'],
  ['remove', '删除']
] as const) {
  assert.ok(tree.includes(`'${action}'`), `树里没有 ${label} 的出口——换布局把功能弄丢了`)
}
assert.match(admin, /@toggle-status="handleToggleMemberStatus"/, '停用没有接上')
assert.match(admin, /@remove="handleDeleteMember"/, '删除没有接上')

// ---- 同一角色可以有多个负责人 ----

/* 现场本来就有 AB 角和轮班。限成一个的话，那个人休假整条审批就卡住了。
   所以这里没有任何「唯一」的限制，只有一个提示。 */
assert.match(api, /isProjectLeader\?: boolean/, '契约类型缺少项目负责人标记')
assert.match(admin, /handleToggleProjectLeader/, '后台没有切换负责人的入口')
assert.match(tree, /设为负责人/, '树里没有设为负责人的按钮')
assert.match(tree, /取消负责人/, '不能取消负责人')

// 不许出现「只能有一个负责人」这类限制
assert.ok(
  !/已有负责人|只能有一位|唯一负责人/.test(tree + admin),
  '出现了「只能有一个负责人」的限制——现场有 AB 角和轮班'
)

/* 取消最后一位负责人是允许的，但要提示：不提示的话会悄悄失去审批能力，
   等到有人来注册才发现没人能审。 */
assert.match(tree, /leaderCountOfRole/, '没有统计该角色的负责人数量')
assert.match(
  tree,
  /这是该角色最后一位负责人，取消后将没有人能审核注册申请/,
  '取消最后一位负责人时没有提示'
)

console.log('Project unit-member tree contract passed')
