/**
 * 悬浮助手对话框的版面约定（2026-11-10「看着有点乱、不够清爽」）。
 *
 * 用源码断言而不是挂载组件：这个 SFC 依赖整套 Element Plus 与路由；这些约定也都是写在
 * 模板和样式里的。每一条背后都是在本机浏览器窗格里量到的问题：
 * - 窄屏单列时节点资料栏（一千多像素、和聊天无关）排在对话下面，输入区夹在中间、随内容滚走。
 * - 全局规则在 ≤900px 把所有按钮撑到 44px，桌面鼠标用户的小窗口里输入区占掉一半高度。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const source = readFileSync(
  fileURLToPath(new URL('./ConversationalReviewWorkbenchB.vue', import.meta.url)),
  'utf8'
)

// 1) 节点资料栏只在「窄屏 + 悬浮助手 + 追问助手页签」里折叠；待办与结果页签、宽屏右栏不折
const foldable = /const contextFoldable = computed\(([\s\S]*?)\n\)/.exec(source)?.[1] || ''
assert.ok(foldable.includes('props.embedded'), '只在悬浮助手里折')
assert.ok(foldable.includes('stackedLayout.value'), '只在单列（≤900px）时折；两栏时它本来就是右栏')
assert.ok(foldable.includes("activePane.value === 'assistant'"), '待办与结果页签里不折')
assert.ok(source.includes('const contextFolded = ref(true)'), '默认折叠')
assert.ok(/!contextHidden/.test(source), '内容区要跟着折叠状态隐藏')

// 2) 往折叠区里放东西的两个入口必须先展开，否则用户看到「已填入」却什么也看不到
const focusHuman = source.slice(
  source.indexOf("if (section === 'human')"),
  source.indexOf('workstationToolsRef.value?.focusTool(section)')
)
assert.ok(focusHuman.includes('contextFolded.value = false'), '跳到人工结论前要先展开')
const copyDraft = source.slice(source.indexOf("if (actionKey === 'copy_opinion_draft')"))
assert.ok(
  copyDraft.slice(0, copyDraft.indexOf('}')).includes('contextFolded.value = false'),
  '草稿填进人工意见后要展开它'
)

// 3) 输入区是整个面板的底边，两种版面都要贴着底（2026-11-10 在 900–1280px 之间实测它悬在中间）：
//    - 页宽 901–1279px 是左右两栏：那一行必须撑满面板高度，不能只有内容那么高；
//    - 页宽 ≤900px 是单列：壳和 layout 要能长到撑满面板，输入区排最后。
const widget = readFileSync(
  fileURLToPath(new URL('../AICheck/components/AiAssistantWidget.vue', import.meta.url)),
  'utf8'
)
const twoColumns = /@media \(900px < width < 1280px\) \{([\s\S]*?)\n\}/.exec(widget)?.[1] || ''
assert.ok(twoColumns.includes('grid-template-rows: minmax(0, 1fr)'), '两栏时唯一的一行撑满高度')
assert.ok(twoColumns.includes('align-content: stretch'), '不能再继承 align-content: start')
const stacked = /@media \(width <= 900px\) \{([\s\S]*?)\n\}\n\n@media/.exec(widget)?.[1] || ''
assert.ok(/composer-dock\)\s*\{\s*order:\s*10/.test(stacked), '单列时输入区排最后')
assert.ok(
  /review-b-shell\.is-embedded\)\s*\{[^}]*flex:\s*1 0 auto/.test(stacked),
  '单列时壳要能长到撑满面板，内容短时输入区才贴底'
)
assert.ok(
  /review-b-layout\)\s*\{[^}]*flex:\s*1 0 auto/.test(stacked),
  '单列时 layout 要能长到撑满面板'
)

// 4) 44px 是给手指的：只有精确指针（鼠标）才收回到 32px，触屏不动
assert.ok(
  /@media \(max-width: 900px\) and \(pointer: fine\)/.test(source),
  '紧凑尺寸只给鼠标，触屏保持 44px'
)

// 5) 待办与结果页签去掉的重复内容（2026-11-10「无关干扰信息还是太多」）：
//    - 「按什么规则审」那张卡的两个按钮和工具行里的同名按钮是同一件事；
//    - 快捷操作的三个命令在输入区已经有了；
//    - 没选引用证据时那张卡只是一个 250px 的空状态插画；
//    - 任务名、状态、关联证据在对话框标题、待办页标题和折叠行里都有。
const overview = readFileSync(
  fileURLToPath(new URL('./components/ReviewNodeOverview.vue', import.meta.url)),
  'utf8'
)
assert.ok(!overview.includes('aria-label="规则与协作"'), '规则与协作那张卡已并入「本次资料」')
assert.ok(!overview.includes('<h3>最后，由你确认</h3>'), '最后一张卡缩成一行')
assert.ok(overview.includes('核对并填写人工结论'), '去人工结论的入口要保留')
assert.ok(
  /<section\s+v-if="!props\.embedded"\s+class="side-card quick-actions"/.test(source),
  '快捷操作在悬浮助手里不显示'
)
assert.ok(
  /v-if="!props\.embedded \|\| selectedEvidence\.length"\s+class="side-card evidence-workset"/.test(
    source
  ),
  '没选引用证据时不显示空卡'
)
assert.ok(/<dl v-if="!props\.embedded">/.test(source), '悬浮助手里不重复任务名、状态、关联证据')

// 6) 头部状态标签和同一行的页签+工具条（2026-11-10 按效果图做）：
//    - 头部在外面的 AiAssistantWidget 里，审查面板用 Teleport 把状态标签放进去；挂载点不在就不渲染；
//    - 悬浮助手（工位版）里对话工具条放进页签那一行，别的版面还在原来的头部里；
//    - 页签样式只管页签按钮本身（用 > 限定），不能把同一行的工具条按钮也带成页签样子。
assert.ok(widget.includes('id="ai-assistant-head-status"'), '头部要有状态标签的挂载点')
assert.ok(
  /<Teleport v-if="props\.embedded && headStatusReady" to="#ai-assistant-head-status">/.test(
    source
  ),
  '状态标签 Teleport 到头部，挂载点不存在时不渲染'
)
assert.ok(
  /v-if="!\(workstationMode && props\.embedded\)"/.test(source) &&
    /v-if="workstationMode && props\.embedded"\s+v-show="activePane === 'assistant'"\s+class="nav-memory"/.test(
      source
    ),
  '悬浮助手里工具条在页签那一行，别处仍在头部'
)
assert.ok(
  !/\.workstation-navigation :deep\(\.el-button/.test(
    source.slice(
      source.indexOf('.review-b-shell.is-embedded .workstation-navigation {'),
      source.indexOf('.nav-memory {')
    )
  ),
  '页签样式用 > 限定，不能 :deep 到同一行的工具条按钮'
)

// 7) 用户的提问要和 AI 回答一眼分开：主色实心气泡＋白字（2026-11-10 用户反馈原来的浅蓝灰
//    #eef3fb 和页面底色几乎一个颜色）。白字压主色约 5.3:1。
const userBubble =
  /\.conversation-message\.is-user \.message-body \{([^}]*)\}/.exec(source)?.[1] || ''
assert.ok(userBubble.includes('background: var(--el-color-primary)'), '提问气泡用主色实心')
assert.ok(/color:\s*#fff/.test(userBubble), '提问气泡用白字')

console.log('Assistant dialog layout contract passed')
