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
assert.ok(foldable.includes('!evidenceWide.value'), '宽屏时它在右栏，不折')
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

// 3) 输入区是整个面板的底边：窄屏要排到最后一个，否则滚过对话它就跟着内容滚走了
assert.ok(
  /@media \(width < 1280px\)\s*\{\s*\.review-b-shell\.is-embedded \.composer-dock\s*\{\s*order:\s*99/.test(
    source
  ),
  '窄屏时输入区排最后'
)

// 4) 44px 是给手指的：只有精确指针（鼠标）才收回到 32px，触屏不动
assert.ok(
  /@media \(max-width: 900px\) and \(pointer: fine\)/.test(source),
  '紧凑尺寸只给鼠标，触屏保持 44px'
)

console.log('Assistant dialog layout contract passed')
