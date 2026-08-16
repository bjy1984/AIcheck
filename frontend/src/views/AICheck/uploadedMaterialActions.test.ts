/**
 * 传完要看得见，看得见还要能预览、替换、删除。
 *
 * ## 来源（施工方反馈）
 *
 * 「上传提示成功之后，看不到已上传的资料，应该可以在线预览、替换和删除。」
 *
 * 实测：点「上传资料」→ toast 说成功 → 那一行毫无变化。用户只看到一句
 * 转瞬即逝的提示，回到表格什么都没变，于是以为没传上去、**再传一遍**。
 * 线上确实有同一份「产品质量证明part1.pdf」重复上传的记录。
 *
 * 预览和删除本来就有（在下方台账里），缺的是：
 * ① 分类表看不到该类别已传几份；② 替换整个不存在——上传永远新建文档。
 *
 * ## 为什么替换不能用「删掉重传」凑合
 *
 * 删掉重传会换一个新的 documentId：节点挂接断了、审查意见里引用的证据
 * 指向一份不存在的资料、监检看到的是「原来那份没了，多了一份陌生的」。
 * 所以替换是**在原文档上加版本**，历史留痕、引用不断。
 *
 * ## 一条硬约束
 *
 * 已提交的资料不许直接替换——那份文件此刻可能正被监检看着。
 * 要改走补正流程，留下痕迹。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const sections = readFileSync(
  fileURLToPath(new URL('./components/WorkbenchRoleStaticSections.vue', import.meta.url)),
  'utf8'
)
const workbench = readFileSync(fileURLToPath(new URL('./Workbench.vue', import.meta.url)), 'utf8')

// ① 分类表要显示已传份数，并能点开看是哪几份
assert.ok(/const categoryFileCount/.test(sections), '分类表要能算出该类别已传几份')
assert.ok(/const focusCategoryFiles/.test(sections), '点份数要能定位到那几份文件')
assert.ok(/label="已上传" width="96"/.test(sections), '分类表要有「已上传」列')
assert.ok(/v-if="categoryFileCount\(row\.category\)"/.test(sections), '0 份不做成可点——点开是空的')

// ② 替换：按钮、权限、提示
assert.ok(/const canReplaceContractorFile/.test(sections), '要判断这份能不能替换')
assert.ok(/\['未关联', '待提交'\]\.includes\(file\.status\)/.test(sections), '只有未提交的才能替换')
assert.ok(/补正流程/.test(sections), '不能替换时要说清楚该走哪条路')
assert.ok(/>\s*替换\s*</.test(sections), '台账要有替换按钮')
assert.ok(/width="290" fixed="right"/.test(sections), '多一个按钮就要放宽列宽——挤掉的按钮等于没有')

// ③ 替换走的是「加版本」，不是新建
assert.ok(/replaceDocumentId/.test(workbench), '上传时要带上替换目标')
assert.ok(
  /uploadDrawerReplaceTarget\.value = null/.test(workbench),
  '普通上传要清掉替换目标——不清会让新文件悄悄覆盖旧资料'
)
assert.ok(/替换资料时只能选择一个文件/.test(workbench), '替换是一对一的，多选会被静默丢弃')
assert.ok(
  /替换资料：\$\{uploadDrawerReplaceTarget\.fileName\}/.test(workbench),
  '抽屉标题要写明在替换哪一份，否则和普通上传长得一样'
)

// ④ 每个版本要显示自己的文件名。
// 替换之后文档名不变（标识要稳），但界面上只看到原来那个名字，
// 用户无从确认换进去的是哪个文件——**换对了没有，是替换这个动作的全部意义**。
const dialog = readFileSync(
  fileURLToPath(new URL('./components/FileDetailDialog.vue', import.meta.url)),
  'utf8'
)
assert.ok(
  /\{\{ row\.fileName \|\| document\.fileName \}\}/.test(dialog),
  '历史版本要显示每版各自的文件名，取不到再退回文档名'
)
