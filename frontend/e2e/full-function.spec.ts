/**
 * 全功能验收 · 页面层（用例编号与 docs/testing/全功能测试用例.md 的 UI-xx 对应）。
 *
 * 接口层的 129 条用例在 backend/scripts/full_function_check 里跑；这里只测接口测不到的：
 * 登录落点、各角色页面骨架、帮助面板和跳转、菜单可见性、对外角色措辞、手机宽度、控制台报错。
 *
 * 前置：演示后端在 8000（launch.json 的 aicheck-demo-api），本文件会自己起 vite（4000）。
 *   cd frontend && pnpm exec playwright test e2e/full-function.spec.ts
 * 账号口令：AICHECK_E2E_PASSWORD；不设就读后端演示账号的共用口令（只对本机演示后端有效）。
 *
 * 选择器只用 data-guide 锚点和看得见的文字——data-guide 由帮助面板依赖、有单测守着，
 * 比 class 名稳得多（2026-09 那批 smoke 就是死在 class 改名上）。
 */
import { readFileSync } from 'node:fs'
import { expect, test, type Page } from '@playwright/test'

type Role = 'inspection' | 'contractor' | 'ndt' | 'owner' | 'admin'

const HOME: Record<Role, string> = {
  inspection: '/workbench/inspection',
  contractor: '/workbench/contractor',
  ndt: '/workbench/ndt',
  owner: '/workbench/owner',
  admin: '/admin/overview'
}
const OUTSIDE: Role[] = ['contractor', 'ndt', 'owner']

const demoPassword = (() => {
  let cached = ''
  return () => {
    if (process.env.AICHECK_E2E_PASSWORD) return process.env.AICHECK_E2E_PASSWORD
    if (!cached) {
      const source = readFileSync(
        new URL('../../backend/libs/security/auth.py', import.meta.url),
        'utf8'
      )
      const matched = source.match(/SHARED_TEST_PASSWORD\s*=\s*"([^"]+)"/)
      if (!matched) throw new Error('读不到演示口令；请设置 AICHECK_E2E_PASSWORD')
      cached = matched[1]
    }
    return cached
  }
})()

/** 收集页面报错和失败的接口请求，用例结束时断言为空。 */
const watchErrors = (page: Page) => {
  const problems: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') problems.push(`console: ${message.text().slice(0, 200)}`)
  })
  page.on('pageerror', (error) => problems.push(`pageerror: ${error.message.slice(0, 200)}`))
  page.on('response', (response) => {
    const url = response.url()
    if (url.includes('/api/') && response.status() >= 400) {
      problems.push(`HTTP ${response.status()} ${new URL(url).pathname}`)
    }
  })
  return problems
}

const login = async (page: Page, role: Role) => {
  await page.goto('/#/login', { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => {
    localStorage.clear()
    sessionStorage.clear()
  })
  await page.reload({ waitUntil: 'domcontentloaded' })
  const inputs = page.locator('.auth-form .el-input__inner')
  await expect(inputs.first()).toBeVisible({ timeout: 15_000 })
  await inputs.nth(0).fill(role)
  await inputs.nth(1).fill(demoPassword())
  await page.getByRole('button', { name: /^登录$/ }).click()
  await page.waitForURL((url) => url.hash.includes(HOME[role]), { timeout: 20_000 })
  await page.waitForLoadState('networkidle')
}

const guide = (page: Page, target: string) => page.locator(`[data-guide="${target}"]`).first()

const openAccountMenu = async (page: Page) => {
  await guide(page, 'topbar-user').click()
  return page.locator('.el-dropdown-menu:visible').last()
}

test.describe('全功能验收 · 页面', () => {
  test('UI-01 登录页不预填口令', async ({ page }) => {
    await page.goto('/#/login', { waitUntil: 'domcontentloaded' })
    await page.evaluate(() => localStorage.clear())
    await page.reload({ waitUntil: 'domcontentloaded' })
    const inputs = page.locator('.auth-form .el-input__inner')
    await expect(inputs.first()).toBeVisible({ timeout: 15_000 })
    await expect(inputs.nth(0)).toHaveValue('')
    await expect(inputs.nth(1)).toHaveValue('')
    await expect(inputs.nth(1)).toHaveAttribute('type', 'password')
  })

  for (const role of Object.keys(HOME) as Role[]) {
    test(`UI-02/UI-18 ${role} 登录落到自己的工作台且无报错`, async ({ page }) => {
      const problems = watchErrors(page)
      await login(page, role)
      expect(page.url()).toContain(HOME[role])
      await expect(guide(page, 'topbar-user')).toBeVisible()
      expect(problems, problems.join('\n')).toEqual([])
    })
  }

  test('UI-03 监检工作台：项目切换与工位总览', async ({ page }) => {
    await login(page, 'inspection')
    await expect(guide(page, 'topbar-project')).toBeVisible()
    await expect(guide(page, 'inspection-overview')).toBeVisible()
    await expect(guide(page, 'inspection-view-tabs')).toBeVisible()
  })

  test('UI-06 施工方工作台（含手机版）', async ({ page }) => {
    await login(page, 'contractor')
    for (const target of ['contractor-status', 'contractor-pending', 'contractor-upload']) {
      await expect(guide(page, target)).toBeVisible()
    }
    await page.setViewportSize({ width: 375, height: 812 })
    await page.reload({ waitUntil: 'networkidle' })
    await expect(guide(page, 'contractor-pending')).toBeVisible()
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth
    )
    expect(overflow, '375px 宽下不应横向滚动').toBeLessThanOrEqual(1)
  })

  test('UI-07 无损工作台：意见、清单、操作入口', async ({ page }) => {
    await login(page, 'ndt')
    for (const target of ['ndt-feedback', 'ndt-checklist', 'ndt-actions']) {
      await expect(guide(page, target)).toBeVisible()
    }
  })

  test('UI-08 建设方首页（手机版）', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 })
    await login(page, 'owner')
    for (const target of ['owner-progress', 'owner-nodes']) {
      await expect(guide(page, target)).toBeVisible()
    }
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth
    )
    expect(overflow, '375px 宽下不应横向滚动').toBeLessThanOrEqual(1)
  })

  for (const role of OUTSIDE) {
    test(`UI-09 ${role} 页面和帮助里不出现「AI」字样`, async ({ page }) => {
      await login(page, role)
      await page.goto(`/#${HOME[role]}?help=1`, { waitUntil: 'networkidle' })
      await expect(page.locator('.user-guide-drawer .guide')).toBeVisible()
      const text = await page.locator('body').innerText()
      expect(text).not.toMatch(/\bAI\b|人工智能/)
    })
  }

  for (const role of Object.keys(HOME) as Role[]) {
    test(`UI-10 ${role} 的意见反馈按钮可见性`, async ({ page }) => {
      await login(page, role)
      const button = page.getByRole('button', { name: '意见反馈' })
      if (role === 'inspection' || role === 'admin') {
        await expect(button).toBeVisible()
      } else {
        await expect(button).toHaveCount(0)
      }
    })
  }

  for (const role of Object.keys(HOME) as Role[]) {
    test(`UI-11/UI-12 ${role} 打开使用帮助，跳转按钮落到目标位置`, async ({ page }) => {
      await login(page, role)
      const menu = await openAccountMenu(page)
      await menu.getByText('使用帮助', { exact: true }).click()
      const drawer = page.locator('.user-guide-drawer .guide')
      await expect(drawer).toBeVisible()
      await expect(drawer.locator('.guide-task').first()).toBeVisible()
      // 找第一个带跳转按钮的任务：展开它，按钮名必须是「去「…」」或「打开「…」」
      const heads = drawer.locator('.guide-task-head')
      const count = await heads.count()
      for (let index = 0; index < count; index++) {
        await heads.nth(index).click()
        const jump = drawer.locator('.guide-jump:visible')
        if (await jump.count()) {
          await expect(jump.first()).toHaveText(/^(去|打开)「.+」/)
          await jump.first().click()
          await expect(page.locator('.guide-spotlight').first()).toBeVisible({
            timeout: 10_000
          })
          return
        }
      }
      test.info().annotations.push({ type: 'note', description: '该角色帮助里没有跳转按钮' })
    })
  }

  test('UI-14 账号菜单「安装节点审计 skill」只给监检和管理员', async ({ page }) => {
    await login(page, 'inspection')
    let menu = await openAccountMenu(page)
    await menu.getByText('安装节点审计 skill', { exact: true }).click()
    const dialog = page.locator('.skill-install-dialog')
    await expect(dialog).toBeVisible()
    const prompt = dialog.getByRole('textbox', { name: '安装提示词' })
    await expect(prompt).toHaveValue(/install\.md/)
    const first = await prompt.inputValue()
    await dialog.getByRole('button', { name: '重新生成' }).click()
    await expect(prompt).not.toHaveValue(first)

    await login(page, 'contractor')
    menu = await openAccountMenu(page)
    await expect(menu.getByText('安装节点审计 skill', { exact: true })).toHaveCount(0)
  })

  test('UI-16 管理后台各页面能打开', async ({ page }) => {
    const problems = watchErrors(page)
    await login(page, 'admin')
    await expect(guide(page, 'admin-new-project')).toBeVisible()
    for (const [path, target] of [
      ['/admin/org', 'admin-new-org'],
      ['/admin/feedback', 'admin-feedback'],
      ['/admin/rule-updates', 'admin-rule-updates'],
      ['/admin/review-policies', 'admin-review-policies']
    ]) {
      await page.goto(`/#${path}`, { waitUntil: 'networkidle' })
      await expect(guide(page, target), `${path} 缺 ${target}`).toBeVisible()
    }
    for (const path of ['/admin/improvement-tasks', '/admin/audit', '/admin/institutes']) {
      await page.goto(`/#${path}`, { waitUntil: 'networkidle' })
      await expect(page.locator('body')).not.toContainText('404')
    }
    expect(problems, problems.join('\n')).toEqual([])
  })
})
