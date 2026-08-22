/**
 * 0817 第 2、3 条的前端对接。
 *
 * 后端做完了不等于用户用得上：能力只在接口里、界面上没有入口，
 * 对用户而言等于没做。这份用例守住三件事。
 *
 * ## 一、自动识别的类别要标出「谁定的」
 *
 * 只显示类别的话，**「系统猜的」和「人定的」长得一模一样**，
 * 用户没法判断要不要去核对它——这正是 0817 第 1 条那个坑的形状：
 * 分错了和分对了在界面上没有任何区别。
 *
 * 三种来源必须分得开：
 *   auto     后端按 164 条审查点词典识别的，带 reason
 *   manual   人工改过的
 *   inferred 后端没给、前端按十来个关键词兜底猜的——最不可信
 *
 * 把 inferred 说成「自动识别」是在夸大可信度。
 *
 * ## 二、必须能改
 *
 * 自动分类一定会错。没有纠正出口的自动化，用户错一次就没有办法了。
 *
 * ## 三、一键审查要把「跳过的」列出来
 *
 * 只显示「已发起 N 个」的话，剩下的去哪了没人知道，监检会以为全跑过了
 * ——而那正是这个功能要消灭的状态。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const read = (relative: string) =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8')

const sections = read('./components/WorkbenchRoleStaticSections.vue')
const workbench = read('./Workbench.vue')
/* 一键审查的界面拆在独立组件里：Workbench.vue 有行数棘轮，
   棘轮的用意就是逼新功能不要再往那个大文件里堆。 */
const batchPanel = read('./components/BatchRecheckPanel.vue')
/* 调用逻辑同样抽在 composable 里，理由同上 */
const batchComposable = read('./useBatchRecheck.ts')
const api = read('../../api/aicheck/index.ts')
const types = read('../../types/aicheck.ts')
const adminOverview = read('./AdminOverview.vue')

// ---- 一、类别来源要分得开 ----

assert.match(types, /materialCategorySource\?: 'auto' \| 'manual' \| null/, '契约类型缺少类别来源')
assert.match(types, /autoClassification\?: \{/, '契约类型缺少自动识别结果')

assert.match(
  sections,
  /materialCategorySource: 'auto' \| 'manual' \| 'inferred'/,
  '表格行没有区分类别来源'
)
assert.match(sections, /materialCategoryReason: string/, '没有带上「凭什么这么分」的依据')

/* 后端没给类别时前端兜底猜的，必须标成 inferred。
   标成 auto 是在夸大可信度：后端那份用 164 条审查点词典，
   前端这份只有十来个关键词。 */
assert.match(
  sections,
  /const materialCategorySource: 'auto' \| 'manual' \| 'inferred' = !backendCategory\s*\?\s*'inferred'/,
  '前端兜底猜的被当成了后端自动识别'
)

// 界面上要看得见来源，而且鼠标悬上去能看到依据
assert.match(sections, /class="material-category-source"/, '界面上没有标出类别来源')
assert.match(sections, /row\.materialCategoryReason/, '依据没有展示，用户发现分错了也不知道改什么')
assert.match(sections, /自动识别/, '缺少「自动识别」标记')
assert.match(sections, /推测/, '缺少「推测」标记——兜底猜的必须和自动识别分开')

// 人工定的不加标记：给确定的东西挂个注解只会制造噪音
assert.match(
  sections,
  /v-if="row\.materialCategorySource !== 'manual'"/,
  '人工确认过的类别不该再挂「自动识别」之类的标记'
)

// ---- 二、必须能改 ----

assert.match(api, /updateDocumentMaterialCategoryApi/, '没有纠正类别的接口')
assert.match(
  api,
  /url: `\/api\/projects\/\$\{projectId\}\/documents\/\$\{documentId\}\/material-category`/,
  '纠正接口的地址不对'
)

// ---- 三、一键审查 ----

assert.match(api, /requestAiRecheckBatchApi/, '缺少一键审查接口')
assert.match(workbench, /useBatchRecheck/, '工作台没有接上一键审查')
assert.match(batchComposable, /requestAiRecheckBatchApi/, 'composable 没有真的调接口')
assert.match(workbench, /BatchRecheckPanel/, '工作台没有挂上一键审查面板')
assert.match(batchPanel, /一键审查全部节点/, '界面上没有一键审查入口')

/* 跳过的必须列出来。这是这个功能的要点：
   「漏掉一个也不会有人发现」正是它要解决的问题，
   而只报「已发起 N 个」会把这个问题原样保留下来。 */
assert.match(batchPanel, /result\.skipped/, '跳过的节点没有展示')
assert.match(batchPanel, /item\.message/, '跳过原因没有展示')
assert.match(batchPanel, /result\.batchLimit/, '单次上限没有展示，用户不知道为什么少了')

// 一个都没发起时更要说清楚，否则看起来像「点了没反应」
assert.match(batchComposable, /没有可发起的节点/, '零发起时没有给出解释')
assert.match(batchComposable, /个已跳过，见下方说明/, '提示里没有把跳过数带出来')

/* ---- 自动审核状态 + 合并时间线（0817 第 3 条）----
 *
 * AI 回复和人工回复分在两个列表里的话，监检要自己按时间对一遍，
 * **而人一旦要自己对时间，就一定会对错**——尤其是 AI 跑了几轮、
 * 中间还夹着人工改判的时候。 */
const timeline = read('./components/NodeReviewTimeline.vue')
assert.match(types, /autoReviewStatus\?: \{/, '契约类型缺少自动审核状态')
assert.match(types, /reviewTimeline\?: Array</, '契约类型缺少合并时间线')
assert.match(workbench, /nodeAutoReviewStatus/, '工作台没有显示自动审核状态')
assert.match(workbench, /NodeReviewTimeline/, '工作台没有挂上合并时间线')

/* 状态和时间线拆在同一个组件里：它们是同一件事的两个粒度
   （「现在到哪了」和「怎么走到这的」），分在两处会让人对不上。
   Workbench.vue 有行数棘轮，这也是它必须拆出去的原因。 */
assert.match(timeline, /status\.reason/, '状态没有带理由')
assert.match(timeline, /status\.overriddenAutoConclusion/, '人工改判没有显示它覆盖了哪条 AI 判定')

// 来源要一眼看出来，不能都写成一行「结论：xxx」
assert.match(timeline, /event\.actor === 'human' \? '人工' : 'AI'/, '时间线没有标出是谁说的')
assert.match(timeline, /该结论覆盖了 AI 判定/, '时间线没有显示改判覆盖了哪一条')

/* Element Plus 在这个项目不是全局全量注册；漏导入时页面仍会渲染一部分，
   但控制台会连续报 unresolved component。模板中新用到的每一个 El 组件都必须
   在本页 script setup 显式导入。 */
const template = adminOverview.slice(adminOverview.indexOf('<template>'))
const usedElementComponents = new Set(
  Array.from(template.matchAll(/<\/?(El[A-Z][A-Za-z0-9]*)\b/g), ([, name]) => name)
)
const importedElementComponents = new Set(
  Array.from(
    adminOverview
      .slice(0, adminOverview.indexOf("} from 'element-plus'"))
      .matchAll(/\b(El[A-Z][A-Za-z0-9]*)\b/g),
    ([, name]) => name
  )
)
for (const component of usedElementComponents) {
  assert.ok(
    importedElementComponents.has(component),
    `管理员页缺少 Element Plus 导入：${component}`
  )
}

console.log('Auto classify + batch review wiring contract passed')
