/**
 * 只报数不报内容，等于让人凭记忆核对。
 *
 * ## 来源（8767.pdf，NDT 无损检测机构）
 *
 * 1. 概览卡「待提交 / 补正 2」是个死数字，看不到是哪两份；
 * 2. 资料清单里「已上传 2 项」也只是数字，旁边只有「上传文件」——
 *    传完之后没有任何入口确认自己传了什么。
 *
 * 传漏了、传错了、传重了，都要等监检退回来才知道。而数据本来就在手上
 * （atomicProjectFiles），不需要新接口。
 *
 * ## 判据
 *
 * - 「已上传 N 项」可点开，列出该类型的文件；0 项不做成可点——
 *   点开是空的，不如让人一眼看出还没传
 * - 文件行要同时显示上传状态与 OCR 状态：**文件已上传但 OCR 还在排队，
 *   跟文件根本没传上去，处置完全不同**
 * - 摘要卡片只有配了 actionKey 才可点。没有去处的卡片不做成按钮——
 *   点了没反应比不可点更伤
 * - 滚动锚点必须真实存在（本轮已因此静默失败过两次）
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const panel = readFileSync(
  fileURLToPath(new URL('./components/NdtWorkflowPanel.vue', import.meta.url)),
  'utf8'
)
const grid = readFileSync(
  fileURLToPath(new URL('./components/AuditSummaryGrid.vue', import.meta.url)),
  'utf8'
)
const workbench = readFileSync(fileURLToPath(new URL('./Workbench.vue', import.meta.url)), 'utf8')

// 「已上传 N 项」可展开
assert.ok(/const toggleMaterialFiles/.test(panel), '要能展开某个资料类型的已传文件')
assert.ok(/expandedMaterialCodes/.test(panel), '要记住展开了哪些类型')
assert.ok(/v-if="row\.uploadedCount"/.test(panel), '0 项不做成可点——点开是空的')
assert.ok(/class="ndt-uploaded-files"/.test(panel), '要有展开后的文件清单区')

// 文件行同时显示两种状态
assert.ok(
  /\{\{ file\.fileStatus \}\} · OCR \{\{ file\.currentOcrStatus \}\}/.test(panel),
  '上传状态与 OCR 状态是两件事，要分开显示'
)

// 点文件能打开详情
assert.ok(/emit\('viewMaterialFile', file\.id\)/.test(panel), '文件名要能点开详情')
assert.ok(
  /@view-material-file="handleOpenFileDetail"/.test(workbench),
  '事件要接到工作台的文件详情'
)

// 摘要卡片动作：配了才可点
assert.ok(/actionKey\?: string/.test(grid), '卡片动作是可选的')
assert.ok(/v-if="card\.actionKey"/.test(grid), '没有去处的卡片不渲染按钮')
assert.ok(/actionKey: 'ndt-pending'/.test(workbench), '待提交/补正卡要配动作')
assert.ok(
  /\.\.\.\(pendingFileCount \? \{ actionKey: 'ndt-pending'/.test(workbench),
  '数字为 0 时不给入口——点进去什么都没有'
)

// 锚点真实存在
assert.ok(/#ndt-pending-files/.test(workbench), '要滚到待处理清单')
assert.ok(/id="ndt-pending-files"/.test(panel), '锚点元素必须真实存在')
