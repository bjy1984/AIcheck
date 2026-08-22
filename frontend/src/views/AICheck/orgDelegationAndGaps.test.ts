/**
 * 组织权限下放、邀请注册、缺项提示的前端对接（0817 第 2、4、5 条）。
 *
 * ## 注册页必须免登录
 *
 * 申请人**本来就还没有账号**。被路由守卫弹回登录页的话，
 * 一个专门发给「还没账号的人」的链接却要求先登录，这条路整个走不通。
 *
 * 而且白名单要**前缀匹配**：路径是 /join/<token>，白名单里写的是 /join，
 * 用精确匹配的话永远命中不了——白名单加了却不生效，而且不报错。
 *
 * ## 界面上的禁用不是安全措施
 *
 * 改一行请求就绕过去了。真正拦越权的是服务端。这两层的分工要写清楚，
 * 免得后人以为「界面上没有这个选项」就等于管住了。
 *
 * ## 上传指引不展示节点缺项和补正文件
 *
 * 施工方项目文件库中的分类指引只负责说明资料分类和上传方式；节点缺项与
 * 补正文件有各自的业务入口，不能混在分类指引里成为无上下文的裸列表。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const read = (relative: string) =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8')

const router = read('../../router/index.ts')
const constants = read('../../constants/index.ts')
const permission = read('../../permission.ts')
const api = read('../../api/aicheck/index.ts')
const delegation = read('./components/OrgDelegationPanel.vue')
const adminOverview = read('./AdminOverview.vue')
const sections = read('./components/WorkbenchRoleStaticSections.vue')

// ---- 注册页免登录 ----

/* 用「包含」而不是写死整个数组：以后再加一条免登录路径不该让这条用例红。
   要守的是「这一条在里面」，不是「里面只有这一条」。 */
assert.ok(
  constants.includes('NO_REDIRECT_WHITE_LIST') && constants.includes("'/join'"),
  "'/join' 不在免登录白名单——申请人会被弹回登录页"
)

/* 白名单必须前缀匹配。/join/<token> 用精确匹配永远命中不了——
   **白名单加了却不生效，而且不报错**：申请人点开链接被弹回登录页，
   看起来像链接坏了。 */
assert.match(
  permission,
  /to\.path === item \|\| to\.path\.startsWith\(`\$\{item\}\/`\)/,
  '白名单还是精确匹配，注册链接会被弹回登录页'
)
// 但也不能宽到 /login-anything 都放行
assert.match(permission, /startsWith\(`\$\{item\}\/`\)/, '前缀匹配没带分隔符，会误放行相似路径')

/* 组织邀请那条路已经撤掉：注册统一走「按项目发链接 → 自选角色 → 审核」。
   两套并存的话，一条即时生效、一条要审核，**同一个系统里两种「注册」
   意味着两种安全边界**，而组织邀请是更宽的那条——留着等于给
   「必须审核」留了个绕过口。 */
assert.ok(!router.includes("path: '/invite"), '组织邀请路由还在')
assert.ok(!constants.includes("'/invite'"), '组织邀请还在免登录白名单里')
assert.ok(!api.includes('acceptInvitationApi'), '组织邀请接口还在')
assert.ok(!api.includes('createOrgInvitationApi'), '组织邀请生成接口还在')
assert.ok(!delegation.includes('createOrgInvitationApi'), '组织面板里还留着邀请入口')

// ---- 组织负责人 ----

assert.match(adminOverview, /isOrgLeader/, '后台没有设置组织负责人的入口')
assert.match(adminOverview, /OrgDelegationPanel/, '后台没有挂上成员角色面板')
assert.match(delegation, /assignOrgMemberRoleApi/, '面板没有调整成员角色的能力')

/* admin / fde 不出现在可选角色里。服务端也会拒，
   但给一个必然失败的选择只是浪费用户一次点击。 */
const roles = delegation.slice(
  delegation.indexOf('ASSIGNABLE_ROLES'),
  delegation.indexOf('const inviteRole')
)
assert.ok(!/'admin'/.test(roles) && !/'fde'/.test(roles), '可选角色里出现了管理员')

/* 前端的禁用不能被当成安全措施——注释里要写清楚这一层的定位，
   免得后人以为界面挡住了就等于管住了。 */
assert.match(delegation, /真正拦住越权的是服务端|真正拦越权的是服务端/, '没有写清楚闸门在服务端')

// ---- 上传指引不展示节点缺项和补正文件 ----

assert.ok(!sections.includes('missingRequirementNames'), '上传指引仍在展示当前节点缺项')
assert.ok(!sections.includes('rejectedFileNames'), '上传指引仍在展示需补正文件名')
assert.ok(!sections.includes('当前环节还缺'), '上传指引仍包含缺项提示文案')

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

/* 二维码：收链接的人多半在工地用手机，扫一下比长按 URL 再粘贴实际得多。
   必须**本地生成**——一个「帮你生成二维码」的外部服务，
   等于把注册链接交给了它。 */
assert.match(registrationPanel, /import QRCode from 'qrcode'/, '二维码没有本地生成')
assert.match(registrationPanel, /QRCode\.toDataURL/, '没有生成二维码')
assert.match(registrationPanel, /alt="项目注册链接二维码"/, '二维码没有可访问名称')
// 二维码画不出来不该让人以为整个链接失败了
assert.match(registrationPanel, /qrDataUrl\.value = ''/, '二维码失败时没有降级，会连累链接本身')
// 深色主题下透明底扫不出来
assert.match(registrationPanel, /background: #fff/, '二维码没有白底，深色主题下扫不出来')

console.log('Org delegation + invite + gap hints contract passed')
