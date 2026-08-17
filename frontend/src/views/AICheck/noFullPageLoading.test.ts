/**
 * 后台页面不许用整页 loading 遮罩。
 *
 * ## 线上实测（2026-08-16）
 *
 * 从 /admin/overview 切到 /knowledge/overview，页面根容器上的
 * `.el-loading-mask` **挡住整页 605 毫秒**——而这还是在本地网络下。
 * 网络慢的时候这个时间成倍增长，期间连菜单、页签都点不动。
 *
 * 遮罩传达的是「现在不许操作」，但刷新数据这件事**不需要剥夺用户的操作权**。
 * 他可能只是想切到别的页签，或者点开左侧另一个功能——凭什么等你加载完？
 *
 * 改为 shell 顶部一条 2px 细进度条：告诉他「在更新」，但不替他决定「不能动」。
 * 局部遮罩（表格、卡片、抽屉）保留——那是「这块数据在变」，范围诚实。
 *
 * ## 判据
 *
 * 页面**根容器**上不许挂 v-loading。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const PAGES = [
  { file: 'AdminOverview.vue', root: 'admin-page' },
  { file: 'KnowledgeOverview.vue', root: 'knowledge-page' },
  { file: 'GenericReviewWorkbench.vue', root: 'generic-workbench' }
]

for (const { file, root } of PAGES) {
  const sfc = readFileSync(fileURLToPath(new URL(`./${file}`, import.meta.url)), 'utf8')

  // 根容器那一行不能带 v-loading
  const rootLine = sfc.split('\n').find((line) => line.includes(`class="${root}`))
  assert.ok(rootLine, `${file} 找不到根容器 ${root}`)
  assert.ok(!rootLine.includes('v-loading'), `${file} 的根容器仍挂着整页遮罩——网络慢时整页点不动`)

  // 要接上非阻塞的顶部进度条，否则就是「去掉了反馈」而不是「换了反馈」
  assert.ok(
    /:refreshing="loading"/.test(sfc),
    `${file} 去掉遮罩后没有接顶部进度条，用户会不知道数据在刷新`
  )
}

// shell 侧：进度条不能拦点击，否则等于换了个样子的遮罩
const shell = readFileSync(
  fileURLToPath(new URL('./components/StaticPageShell.vue', import.meta.url)),
  'utf8'
)
assert.ok(/refreshing\?: boolean/.test(shell), 'shell 要接收 refreshing')
assert.ok(/class="shell-refreshing"/.test(shell), 'shell 要渲染顶部进度条')
const style = shell.slice(shell.indexOf('.shell-refreshing {'))
assert.ok(/pointer-events: none/.test(style.slice(0, 400)), '进度条不能拦住点击')
assert.ok(/position: fixed/.test(style.slice(0, 400)), '进度条不该占布局高度')
assert.ok(/prefers-reduced-motion/.test(shell), '要尊重系统的减少动效设置')

// 局部 loading 保留——那是诚实的范围提示，不该被一并删掉
const admin = readFileSync(fileURLToPath(new URL('./AdminOverview.vue', import.meta.url)), 'utf8')
assert.ok(
  /v-loading="projectsLoading"/.test(admin),
  '表格级 loading 被误删了：那是「这块数据在变」，范围是诚实的'
)

console.log('No full-page loading contract passed')
