/**
 * 使用帮助（2026-11-04）：「带我去」和「开始引导」靠页面上的 data-guide 锚点找位置。
 *
 * **锚点写了而元素没有，跳过去只会说「这一块现在没有显示」**——那不是没内容，是代码坏了。
 * 所以这里核对：内容里引用的每个锚点都真的写在某个页面组件里；截图文件都在；
 * 编号圈不比步骤多；施工方、无损检测、建设方的说明里不出现「AI」「人工智能」。
 */
import assert from 'node:assert/strict'
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { GUIDE_ROLES, guideForRole, hasUserGuide } from './guideContent'

const here = fileURLToPath(new URL('.', import.meta.url))
const viewsRoot = join(here, '..')

const vueSources: string[] = []
const walk = (dir: string) => {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) walk(full)
    else if (name.endsWith('.vue')) vueSources.push(readFileSync(full, 'utf8'))
  }
}
walk(viewsRoot)
const allVue = vueSources.join('\n')

const anchorExists = (target: string) => allVue.includes(`data-guide="${target}"`)

for (const role of GUIDE_ROLES) {
  const guide = guideForRole(role)
  assert.equal(guide.role, role)
  assert.ok(guide.tasks.length >= 3, `${role}：至少要有三件常办的事`)
  assert.ok(guide.tour.length >= 3, `${role}：「开始引导」至少讲三块`)

  const spots = [...guide.tour, ...guide.tasks.flatMap((task) => (task.jump ? [task.jump] : []))]
  for (const spot of spots) {
    assert.ok(anchorExists(spot.target), `${role}：页面上找不到 data-guide="${spot.target}"`)
    assert.ok(spot.hint.trim(), `${role}：${spot.target} 缺提示语`)
  }

  const ids = new Set<string>()
  for (const task of guide.tasks) {
    assert.ok(!ids.has(task.id), `${role}：任务 id 重复 ${task.id}`)
    ids.add(task.id)
    assert.ok(task.steps.length >= 1 && task.steps.length <= 4, `${role}/${task.id}：步骤一到四步`)
    // 「带我去」按钮要说清去哪：照着目标那一块的标题写（2026-11-04 用户：「带我去这一块」太晦涩）
    if (task.jump) {
      assert.ok(
        /^(去|打开)/.test(task.jump.label || '') && /「.+」/.test(task.jump.label || ''),
        `${role}/${task.id}：跳转按钮要写成「去「某某」」，不能只写「这一块」`
      )
    }
    if (!task.image) continue
    const fileName = decodeURIComponent(task.image.src.split('/').pop() || '')
    assert.ok(
      existsSync(join(here, 'images', fileName)),
      `${role}/${task.id}：截图 ${fileName} 不存在`
    )
    for (const marker of task.image.markers || []) {
      assert.ok(
        marker.n >= 1 && marker.n <= task.steps.length,
        `${role}/${task.id}：编号圈 ${marker.n} 没有对应的步骤`
      )
      assert.ok(marker.x >= 0 && marker.x <= 100 && marker.y >= 0 && marker.y <= 100)
    }
  }
}

// 对外三个角色：说明里不说「AI」「人工智能」（和 utils/reviewerWording.ts 同一个约定）
for (const role of ['contractor', 'ndt', 'owner'] as const) {
  // 截图地址里有目录名 AICheck，不算界面文字
  const text = JSON.stringify(guideForRole(role), (key, value) => (key === 'src' ? '' : value))
  assert.ok(!/AI|人工智能/.test(text), `${role} 的使用帮助里出现了 AI 字样`)
}

assert.equal(hasUserGuide('contractor'), true)
assert.equal(hasUserGuide('fde'), false, 'FDE 没有使用帮助，菜单里不显示入口')
assert.equal(hasUserGuide(undefined), false)

// 入口：两种页面外壳的账号菜单都有「使用帮助」，帮助和高亮层挂在共用布局上
const workbench = readFileSync(join(viewsRoot, 'Workbench.vue'), 'utf8')
const shell = readFileSync(join(viewsRoot, 'components', 'StaticPageShell.vue'), 'utf8')
const layout = readFileSync(
  join(viewsRoot, '..', '..', 'layout', 'AICheckStaticLayout.vue'),
  'utf8'
)
for (const [name, source] of [
  ['Workbench.vue', workbench],
  ['StaticPageShell.vue', shell]
] as const) {
  assert.ok(/command="help"/.test(source), `${name} 的账号菜单要有「使用帮助」`)
  assert.ok(/openUserGuide\(\)/.test(source), `${name} 要接上 openUserGuide`)
}
assert.ok(/<UserGuideDrawer \/>/.test(layout) && /<GuideSpotlight \/>/.test(layout))

console.log('user guide anchors, images and wording passed')
