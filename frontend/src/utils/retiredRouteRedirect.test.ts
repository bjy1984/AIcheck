/**
 * 下线一个页面，不等于让老链接失联。
 *
 * ## 背景（2026-08-16）
 *
 * 监检原来有两套并存的界面：/ai-review-b（对话式）和 /workbench/inspection
 * （完整工作台）。同一件事有两个位置、两套状态，用户不知道该信哪个，
 * 问题也要修两遍——本轮就有好几条是「同一条规则写在两处、只改一处」。
 * 按决定合并为一套，保留 /workbench/inspection。
 *
 * **对话式复核没有被删掉**：ConversationalReviewWorkbenchB 仍以 embedded
 * 方式挂在工作台的「AI 审查」区。下线的只是那个并行入口。
 *
 * ## 判据
 *
 * - 老地址要重定向，不能 404。收藏夹、历史待办、别人发来的链接里都存着它，
 *   直接 404 会让人以为功能被删了。
 * - 查询串必须原样带过去。丢了 projectId/nodeId，人落在一个空工作台上，
 *   还得自己重新找一遍项目和节点——**这种「到了但没到」比 404 更耗时间**。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { getRoleDefaultPath, resolveRetiredPath, resolveRoleEntryPath } from './roleAccess'

// 监检默认落地改到工作台
assert.equal(getRoleDefaultPath('inspection'), '/workbench/inspection')

// 老地址翻译：带查询串
// 还要补上 view=ai：工作台默认是资料列表，而从对话页过来的人要的是对话。
// 「到了但没到」比 404 更耗时间——他会以为对话功能真被删了。
assert.equal(
  resolveRetiredPath('/ai-review-b?projectId=P-1&nodeId=2'),
  '/workbench/inspection?projectId=P-1&nodeId=2&view=ai'
)
assert.equal(resolveRetiredPath('/ai-review-b'), '/workbench/inspection?view=ai')
// 已经指定了 view 就尊重原值，不要覆盖用户的选择
assert.equal(resolveRetiredPath('/ai-review-b?view=list'), '/workbench/inspection?view=list')
// 不是退役路径的原样返回 null，不能顺手改写别的地址
assert.equal(resolveRetiredPath('/workbench/inspection'), null)
assert.equal(resolveRetiredPath('/admin/overview'), null)

// 登录后的落地也走同一套翻译
assert.equal(
  resolveRoleEntryPath('inspection', '/ai-review-b?projectId=P-9&nodeId=3'),
  '/workbench/inspection?projectId=P-9&nodeId=3&view=ai'
)

// 路由表里不该再有这条独立路由
const router = readFileSync(fileURLToPath(new URL('../router/index.ts', import.meta.url)), 'utf8')
assert.ok(!/path: '\/ai-review-b'/.test(router), '独立路由应当已下线')

// 守卫里要有重定向，否则直接输老地址会撞 404
const permission = readFileSync(fileURLToPath(new URL('../permission.ts', import.meta.url)), 'utf8')
assert.ok(/resolveRetiredPath\(to\.fullPath\)/.test(permission), '守卫要翻译已下线路径')
assert.ok(/query: to\.query/.test(permission), '重定向要带上查询串')

// 组件仍存在且仍被工作台内嵌——下线的是入口，不是能力
const workbench = readFileSync(
  fileURLToPath(new URL('../views/AICheck/Workbench.vue', import.meta.url)),
  'utf8'
)
assert.ok(
  /<ConversationalReviewWorkbenchB[\s\S]{0,80}embedded/.test(workbench),
  '对话式复核要继续以内嵌方式存在'
)
