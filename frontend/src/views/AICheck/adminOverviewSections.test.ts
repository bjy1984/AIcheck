/**
 * 后台总览：轻量页必须**显式**声明只要核心数据。
 *
 * 线上实测（2026-08-16）：admin 每切一页都在等同一个 /admin/config-overview，
 * 787 KB / 5.0~6.4 秒，其中 ruleVersions 375 KB、materialReviewPoints 118 KB
 * 只有业务规则那几页在用。切页耗时：权限 7.98s、报告模板 6.74s。
 *
 * 第一版改法写反了方向：不需要重数据时什么都不传，后端按默认下发全部，
 * 于是线上一切照旧——788 KB、5.4 秒、请求里连 sections 都没有。
 * **「改了但没生效」在耗时上跟「没改」长得一模一样**，只能靠抓请求参数分辨。
 * 这个测试就是那把尺子。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const sfc = readFileSync(fileURLToPath(new URL('./AdminOverview.vue', import.meta.url)), 'utf8')

const start = sfc.indexOf('const loadData = async ()')
assert.ok(start > 0, '找不到后台数据加载函数')
const fn = sfc.slice(start, sfc.indexOf('const handleIntegrationFilterChange'))

// 两条分支都要传参：轻量页传 core，重页传两节。任一分支传空数组都等于没改。
assert.ok(/needsHeavySections\.value/.test(fn), '要按页签判断是否需要重数据')
assert.ok(/\['ruleVersions', 'materialReviewPoints'\]/.test(fn), '重页要显式要这两节')
assert.ok(/: \['core'\]/.test(fn), "轻量页要显式声明 ['core']，不能什么都不传")
assert.ok(!/heavySections = \[\]/.test(fn), '空数组会让后端按默认下发全部——等于没改')

// 兜底：被省略了却真的要用，必须补拉；否则表格默默变空比慢更糟
assert.ok(/omittedSections/.test(fn), '要读后端的省略声明')
assert.ok(
  /if \(omitted\.length && needsHeavySections\.value\)/.test(fn),
  '省略了而当前页真要用时，必须补拉完整数据'
)

// 判据集中在一处，避免下次加页签时漏掉
const decl = sfc.slice(sfc.indexOf('const needsHeavySections'), start)
for (const tab of ['business-rule', 'material-review-point', 'node-template']) {
  assert.ok(decl.includes(tab), `用到重数据的页签 ${tab} 要列进判据`)
}

// 文件分类提示词继续复用现有编辑抽屉，但必须明确只发送 MinerU Markdown，
// 并隐藏分类任务不使用的 Planner / Critic 字段。
assert.ok(sfc.includes("document-material-classifier"), '缺少文件分类 Prompt Key 的专用编辑状态')
assert.ok(sfc.includes('仅将 MinerU Markdown 正文发送给 Qwen'), '缺少 Markdown-only 输入边界提示')
assert.ok(
  /promptTemplateForm\.promptKey !== 'document-material-classifier'/.test(sfc),
  '文件分类模板必须隐藏不生效的 Planner / Critic 输入框'
)
assert.ok(sfc.includes('categoryDefinitionsJson'), '分类模板提示中缺少 categoryDefinitionsJson 变量')
assert.ok(sfc.includes('ocrMarkdown'), '分类模板提示中缺少 ocrMarkdown 变量')
