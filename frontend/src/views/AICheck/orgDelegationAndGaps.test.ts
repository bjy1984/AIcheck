/**
 * 组织权限下放、邀请注册、缺项提示的前端对接（0817 第 2、4、5 条）。
 *
 * ## 邀请页必须免登录
 *
 * 收件人**本来就还没有账号**。被路由守卫弹回登录页的话，
 * 一个专门发给「还没账号的人」的链接却要求先登录，这条路整个走不通。
 *
 * 而且白名单要**前缀匹配**：路径是 /invite/<token>，白名单里写的是 /invite，
 * 用精确匹配的话永远命中不了——白名单加了却不生效，而且不报错。
 *
 * ## 界面上的禁用不是安全措施
 *
 * 改一行请求就绕过去了。真正拦越权的是服务端。这两层的分工要写清楚，
 * 免得后人以为「界面上没有这个选项」就等于管住了。
 *
 * ## 缺项和未通过要显示出来
 *
 * 这两份数据一直都在，但施工方页面从来没显示过——他只能传完等着被退回。
 * **数据有、界面没有，对用户就是没有。**
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const read = (relative: string) =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8')

const router = read('../../router/index.ts')
const constants = read('../../constants/index.ts')
const permission = read('../../permission.ts')
const invitePage = read('../Login/AcceptInvitation.vue')
const delegation = read('./components/OrgDelegationPanel.vue')
const adminOverview = read('./AdminOverview.vue')
const sections = read('./components/WorkbenchRoleStaticSections.vue')

// ---- 邀请页免登录 ----

assert.match(router, /path: '\/invite\/:token'/, '没有邀请注册路由')
/* 用「包含」而不是写死整个数组：以后再加一条免登录路径不该让这条用例红。
   要守的是「这两条在里面」，不是「里面只有这两条」。 */
for (const path of ["'/invite'", "'/join'"]) {
  assert.ok(
    constants.includes('NO_REDIRECT_WHITE_LIST') && constants.includes(path),
    `${path} 不在免登录白名单——收件人会被弹回登录页`
  )
}

/* 白名单必须前缀匹配。/invite/<token> 用精确匹配永远命中不了——
   **白名单加了却不生效，而且不报错**：收件人点开链接被弹回登录页，
   看起来像链接坏了。 */
assert.match(
  permission,
  /to\.path === item \|\| to\.path\.startsWith\(`\$\{item\}\/`\)/,
  '白名单还是精确匹配，邀请链接会被弹回登录页'
)
// 但也不能宽到 /login-anything 都放行
assert.match(permission, /startsWith\(`\$\{item\}\/`\)/, '前缀匹配没带分隔符，会误放行相似路径')

// 角色和组织由邀请写死，页面不提供选择——自选角色的链接是公开提权入口
assert.ok(!/v-model="[^"]*\.role"/.test(invitePage), '注册页让用户自己选角色了，这是提权入口')
assert.match(invitePage, /两次输入的口令不一致/, '没有在提交前校验两次口令')

// ---- 组织负责人 ----

assert.match(adminOverview, /isOrgLeader/, '后台没有设置组织负责人的入口')
assert.match(adminOverview, /OrgDelegationPanel/, '后台没有挂上成员与邀请面板')
assert.match(delegation, /createOrgInvitationApi/, '面板没有生成邀请链接的能力')
assert.match(delegation, /assignOrgMemberRoleApi/, '面板没有调整成员角色的能力')

/* admin / fde 不出现在可选角色里。服务端也会拒，
   但给一个必然失败的选择只是浪费用户一次点击。 */
const roles = delegation.slice(
  delegation.indexOf('ASSIGNABLE_ROLES'),
  delegation.indexOf('const inviteRole')
)
assert.ok(!/'admin'/.test(roles) && !/'fde'/.test(roles), '可选角色里出现了管理员')

// 邀请链接的有效期必须写出来：链接会被转发、被截图
assert.match(delegation, /只能使用一次，有效期至/, '没有说明链接的有效期和单次限制')

/* 前端的禁用不能被当成安全措施——注释里要写清楚这一层的定位，
   免得后人以为界面挡住了就等于管住了。 */
assert.match(delegation, /真正拦住越权的是服务端|真正拦越权的是服务端/, '没有写清楚闸门在服务端')

// ---- 缺项与未通过 ----

assert.match(sections, /missingRequirementNames/, '施工方页面没有缺项提示')
assert.match(sections, /rejectedFileNames/, '施工方页面没有「需补正」提示')
assert.match(
  sections,
  /当前环节还缺 \{\{ missingRequirementNames\.length \}\} 项资料/,
  '缺项没有显示条数'
)

/* 字段名要按契约来。missingRequirements 里那一条叫 name，
   materialTypeName 是资料审查点那边的字段——猜错的代价是列表恒空，
   而且不报错。 */
assert.ok(
  !/item\.materialTypeName/.test(sections),
  '用了 materialTypeName —— 契约里没有这个字段，列表会恒空'
)

/* ---- 项目注册：发链接 → 自选角色 → 负责人审核 ----
 *
 * 上一版邀请把角色写死，理由是「自选角色的链接等于公开提权入口」。
 * **加了审核这一关之后这个理由不成立了**：审核才是闸门，自选只是填表。
 *
 * 但这带来一条新的硬要求：**待审期间绝不能存在可用账号。** */
const joinPage = read('../Login/ProjectRegistration.vue')
const registrationPanel = read('./components/ProjectRegistrationPanel.vue')

assert.match(router, /path: '\/join\/:token'/, '没有项目注册路由')
assert.match(joinPage, /form\.role/, '注册页没有让用户选角色')
assert.match(joinPage, /info\.selectableRoles/, '角色选项没有取自服务端')

/* 提交之后**没有账号**，这一点必须在界面上说清楚。
   不说的话用户会去登录、登不进去，以为注册失败了，然后再填一遍。 */
assert.match(joinPage, /等待项目负责人审核/, '成功页没说要等审核')
assert.match(joinPage, /现在还不能登录/, '没有说清楚现在登不进去')

// 拒绝必须写理由：不写的话申请人只看到「被拒了」，会原样再提一次
assert.match(registrationPanel, /inputErrorMessage: '必须填写理由'/, '拒绝可以不写理由')
assert.match(registrationPanel, /row\.rejectReason/, '拒绝理由没有显示，过后没人说得清为什么')

// 链接的有效期和次数都要写出来——它会被转发、被截图
assert.match(registrationPanel, /有效期至 \{\{ linkExpiresAt \}\}/, '没说链接什么时候作废')
assert.match(registrationPanel, /最多可注册\s*\n?\s*\{\{ linkMaxUses \}\} 人/, '没说链接还能用几次')

assert.match(adminOverview, /ProjectRegistrationPanel/, '后台没有挂上注册审核面板')

console.log('Org delegation + invite + gap hints contract passed')
