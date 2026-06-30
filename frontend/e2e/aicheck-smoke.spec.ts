import { expect, test, type Page } from '@playwright/test'

type RouteCase = {
  path: string
  title: string
  titleLocator: string
}

const routeCases: RouteCase[] = [
  { path: '/workbench/inspection', title: '监检工作台', titleLocator: '.aicheck-page .page-title' },
  {
    path: '/workbench/contractor',
    title: '施工方工作台',
    titleLocator: '.aicheck-page .page-title'
  },
  {
    path: '/workbench/ndt',
    title: '无损检测工作台',
    titleLocator: '.aicheck-page .page-title'
  },
  { path: '/workbench/owner', title: '建设方工作台', titleLocator: '.aicheck-page .page-title' },
  { path: '/admin/overview', title: '项目与权限配置', titleLocator: '.admin-page .page-title' },
  { path: '/fde/projects', title: '项目审计工作台', titleLocator: '.fde-console .page-title' },
  {
    path: '/knowledge/overview',
    title: 'AI 知识库管理',
    titleLocator: '.knowledge-page .page-title'
  }
]

const adminDeepRouteCases = [
  { path: '/admin/projects', menu: '项目列表', tab: '组织用户' },
  { path: '/admin/org', menu: '组织用户', tab: '组织用户' },
  { path: '/admin/permission', menu: '角色权限配置', tab: '权限与节点' },
  { path: '/admin/rules', menu: '流程状态机', tab: '规则与流程' },
  { path: '/admin/fine-config', menu: '待办规则配置', tab: '细项配置' },
  { path: '/admin/integration', menu: '联调清单', tab: '联调清单' },
  { path: '/admin/audit', menu: '操作日志', tab: '审计日志' }
]

const knowledgeDeepRouteCases = [
  { path: '/knowledge/sources', menu: '标准规范库', tab: '知识源管理' },
  { path: '/knowledge/files', menu: '项目文件知识库', tab: '项目文件库' },
  { path: '/knowledge/tasks', menu: 'OCR/向量任务中心', tab: '任务中心' },
  { path: '/knowledge/rules', menu: '业务规则版本管理', tab: '规则配置' },
  { path: '/knowledge/retrieval', menu: '知识检索测试', tab: '检索测试' },
  { path: '/knowledge/reasoning', menu: '推理链路历史日志', tab: '推理日志' },
  { path: '/knowledge/compare', menu: '多 LLM 反馈对比', tab: '多模型对比' },
  { path: '/knowledge/config', menu: '知识库配置', tab: '配置审计' }
]

const fdeDeepRouteCases = [
  {
    path: '/fde/projects?view=vectorization',
    menu: '资料向量化',
    hint: '向量',
    context: '项目审计工作台',
    title: '项目审计工作台',
    content: '资料索引入库状态'
  },
  {
    path: '/fde/projects?view=pageindex',
    menu: 'PageIndex 溯源',
    hint: 'PI节点',
    context: '项目审计工作台',
    title: '项目审计工作台',
    content: 'PageIndex 路由追踪'
  },
  {
    path: '/fde/projects?view=langgraph',
    menu: 'LangGraph 可视化',
    hint: 'ReviewRun',
    context: '项目审计工作台',
    title: '项目审计工作台',
    content: 'Agent 思考链与工具证据'
  },
  {
    path: '/fde/projects?view=ocr-labeling',
    menu: 'OCR 打标',
    hint: '样本',
    context: '项目审计工作台',
    title: '项目审计工作台',
    content: '标注覆盖率'
  },
  {
    path: '/fde/projects?view=evaluation',
    menu: '准确率评估',
    hint: '阻断',
    context: '项目审计工作台',
    title: '项目审计工作台',
    content: '准确率评估门禁'
  }
]

const accountForPath = (path: string) => {
  if (path.startsWith('/fde')) return 'fde'
  if (path.startsWith('/admin') || path.startsWith('/knowledge')) return 'admin'
  if (path.includes('/workbench/contractor')) return 'contractor'
  if (path.includes('/workbench/ndt')) return 'ndt'
  if (path.includes('/workbench/owner')) return 'owner'
  return 'inspection'
}

const passwordForAccount = (account: string) => {
  const normalized = account.toUpperCase().replace(/-/g, '_')
  return (
    process.env[`AICHECK_E2E_PASSWORD_${normalized}`] ||
    process.env[`AICHECK_BOOTSTRAP_PASSWORD_${normalized}`] ||
    account
  )
}

const clearLoginState = async (page: Page) => {
  await page.evaluate(() => {
    localStorage.clear()
    sessionStorage.clear()
  })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForLoadState('networkidle').catch(() => {})
}

const gotoLoginPage = async (page: Page, redirect?: string) => {
  const target = redirect ? `/#/login?redirect=${encodeURIComponent(redirect)}` : '/#/login'
  await page.goto(target, { waitUntil: 'domcontentloaded' })
  const loginInputs = page.locator('.auth-form .el-input__inner')
  try {
    await expect(loginInputs.first()).toBeVisible({ timeout: 15_000 })
  } catch (error) {
    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(loginInputs.first()).toBeVisible({ timeout: 15_000 })
  }
  return loginInputs
}

const businessError = (code: number, message: string, reason: string) => ({
  code,
  message,
  data: { reason },
  operationId: `E2E-${reason}`,
  serverTime: '2026-06-26 16:30:00'
})

const loginTo = async (page: Page, path: string, account = accountForPath(path)) => {
  await page.goto('/#/login', { waitUntil: 'domcontentloaded' })
  await clearLoginState(page)
  const loginInputs = await gotoLoginPage(page, path)

  await loginInputs.nth(0).fill(account)
  await loginInputs.nth(1).fill(passwordForAccount(account))
  await page.getByRole('button', { name: /^登录$/ }).click()
  await page.waitForURL((url) => url.hash.includes(path))
  await page.waitForLoadState('networkidle')
}

const loginWithoutRedirect = async (page: Page, account: string, expectedPath: string) => {
  const loginInputs = await gotoLoginPage(page)

  await loginInputs.nth(0).fill(account)
  await loginInputs.nth(1).fill(passwordForAccount(account))
  await page.getByRole('button', { name: /^登录$/ }).click()
  await page.waitForURL((url) => url.hash.includes(expectedPath))
  await page.waitForLoadState('networkidle')
}

const expectRouteVisible = async (page: Page, routeCase: RouteCase) => {
  await expect(page.locator(routeCase.titleLocator)).toContainText(routeCase.title)
}

const openRoute = async (page: Page, routeCase: RouteCase) => {
  await loginTo(page, routeCase.path)
  await expectRouteVisible(page, routeCase)
}

const gotoRoute = async (page: Page, routeCase: RouteCase) => {
  await page.goto(`/#${routeCase.path}`)
  await page.waitForURL((url) => url.hash.includes(routeCase.path))
  await page.waitForLoadState('networkidle')
  await expectRouteVisible(page, routeCase)
}

const expectNoPageOverflow = async (page: Page) => {
  await expect
    .poll(
      () =>
        page.evaluate(() => {
          const documentWidth = document.documentElement.scrollWidth
          const bodyWidth = document.body.scrollWidth
          const viewportWidth = document.documentElement.clientWidth
          return Math.max(documentWidth, bodyWidth) > viewportWidth + 1
        }),
      { timeout: 1500 }
    )
    .toBe(false)
}

const expectFdeWorkspaceNotClipped = async (page: Page) => {
  await expect
    .poll(
      () =>
        page.evaluate(() => {
          const viewportWidth = document.documentElement.clientWidth
          const failures: string[] = []
          const center = document.querySelector<HTMLElement>('.center')
          const workbench = document.querySelector<HTMLElement>('.project-audit-workbench')
          const visible = (element: Element) => {
            const rect = element.getBoundingClientRect()
            const style = getComputedStyle(element)
            return (
              rect.width > 1 &&
              rect.height > 1 &&
              style.display !== 'none' &&
              style.visibility !== 'hidden'
            )
          }

          if (center && center.scrollWidth > center.clientWidth + 2) {
            failures.push(`center:${center.scrollWidth}/${center.clientWidth}`)
          }

          if (workbench && workbench.scrollWidth > workbench.clientWidth + 2) {
            failures.push(`workbench:${workbench.scrollWidth}/${workbench.clientWidth}`)
          }

          const compactProjectCard = document.querySelector<HTMLElement>(
            '.fde-console .project-audit-card--compact'
          )
          if (compactProjectCard) {
            const height = Math.round(compactProjectCard.getBoundingClientRect().height)
            if (height > 96) failures.push(`compact-project-card:${height}`)
          }

          const checkedSelectors = [
            '.fde-console .project-audit-card',
            '.fde-console .project-audit-module-bar',
            '.fde-console .workbench-summary-card',
            '.fde-console .audit-step-card',
            '.fde-console .pageindex-trace-card',
            '.fde-console .panel',
            '.fde-console .project-audit-select'
          ]
          const offscreen = checkedSelectors.flatMap((selector) =>
            Array.from(document.querySelectorAll(selector))
              .filter(visible)
              .filter((element) => {
                const rect = element.getBoundingClientRect()
                return rect.left < -2 || rect.right > viewportWidth + 2
              })
              .map((element) => {
                const rect = element.getBoundingClientRect()
                const text = (element.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 32)
                return `${selector}:${Math.round(rect.left)}-${Math.round(rect.right)}:${text}`
              })
          )

          failures.push(...offscreen)
          return failures.join('\n')
        }),
      { timeout: 1500 }
    )
    .toBe('')
}

const waitForFdeProjectAuditReady = async (page: Page) => {
  await expect(page.locator('.fde-console')).toBeVisible({ timeout: 15000 })
  await expect(page.locator('.static-tree-menu .tree-group-wrap').first()).toBeVisible({
    timeout: 15000
  })
  await expect(page.locator('.static-tree-menu .tree-node.active').first()).toBeVisible({
    timeout: 15000
  })
}

const expectFdeProjectTreeUsable = async (page: Page) => {
  await expect
    .poll(
      () =>
        page.evaluate(() => {
          const failures: string[] = []
          const left = document.querySelector<HTMLElement>('.left')
          const tree = document.querySelector<HTMLElement>('.static-tree-menu')
          const activeNode = document.querySelector<HTMLElement>(
            '.static-tree-menu .tree-node.active, .static-tree-menu .tree-node.is-active'
          )
          const visible = (element: Element) => {
            const rect = element.getBoundingClientRect()
            const style = getComputedStyle(element)
            return (
              rect.width > 1 &&
              rect.height > 1 &&
              style.display !== 'none' &&
              style.visibility !== 'hidden'
            )
          }

          if (!left) failures.push('missing-left')
          if (!tree) failures.push('missing-tree')
          if (!activeNode) failures.push('missing-active-node')

          if (left && tree) {
            const leftRect = left.getBoundingClientRect()
            const treeRect = tree.getBoundingClientRect()
            if (treeRect.width < 240) failures.push(`tree-too-narrow:${Math.round(treeRect.width)}`)
            if (tree.scrollWidth > tree.clientWidth + 18) {
              failures.push(`tree-horizontal-scroll:${tree.scrollWidth}/${tree.clientWidth}`)
            }
            const leaking = Array.from(left.querySelectorAll('*'))
              .filter(visible)
              .filter((element) => {
                const rect = element.getBoundingClientRect()
                return rect.left < leftRect.left - 2 || rect.right > leftRect.right + 2
              })
              .map((element) => {
                const text = (element.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 28)
                return `${element.className?.toString?.() || element.tagName}:${text}`
              })
              .slice(0, 6)
            if (leaking.length) failures.push(`left-leak:${leaking.join('|')}`)
          }

          const projectCards = Array.from(document.querySelectorAll('.tree-group-wrap')).filter(
            visible
          )
          if (projectCards.length < 2) failures.push(`project-cards:${projectCards.length}`)
          const tallProjectCards = projectCards
            .map((card) => ({
              text: (card.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 32),
              height: Math.round(card.getBoundingClientRect().height)
            }))
            .filter((card) => card.height > 74)
          if (tallProjectCards.length) {
            failures.push(
              `project-card-tall:${tallProjectCards.map((card) => `${card.text}:${card.height}`).join('|')}`
            )
          }
          const crowdedProjectCards = projectCards
            .map((card) => ({
              text: (card.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 32),
              chipCount: card.querySelectorAll('.tree-chip').length
            }))
            .filter((card) => card.chipCount > 3)
          if (crowdedProjectCards.length) {
            failures.push(
              `project-card-chips:${crowdedProjectCards.map((card) => `${card.text}:${card.chipCount}`).join('|')}`
            )
          }
          const visibleTreeNodes = Array.from(
            document.querySelectorAll<HTMLElement>('.tree-section-menu.is-opened .tree-node')
          ).filter(visible)
          const visibleHints = visibleTreeNodes.filter(
            (node) => node.querySelectorAll('small').length > 0
          )
          const visiblePills = visibleTreeNodes.flatMap((node) =>
            Array.from(node.querySelectorAll<HTMLElement>('.pill')).filter(visible)
          )
          const tallNodes = visibleTreeNodes
            .map((node) => ({
              text: (node.textContent || '').trim().replace(/\s+/g, ' '),
              height: Math.round(node.getBoundingClientRect().height)
            }))
            .filter((node) => node.height > 38)

          if (visibleHints.length) failures.push(`tree-hints:${visibleHints.length}`)
          if (visiblePills.length > 1) failures.push(`tree-pills:${visiblePills.length}`)
          if (tallNodes.length) {
            failures.push(
              `tree-tall:${tallNodes.map((node) => `${node.text}:${node.height}`).join('|')}`
            )
          }

          const openedProjectSections = document.querySelectorAll(
            '.tree-section-menu.is-opened'
          ).length
          if (openedProjectSections > 1) {
            failures.push(`too-many-open-projects:${openedProjectSections}`)
          }

          if (activeNode) {
            const rect = activeNode.getBoundingClientRect()
            if (rect.height < 34 || rect.height > 72) {
              failures.push(`active-height:${Math.round(rect.height)}`)
            }
          }

          return failures.join('\n')
        }),
      { timeout: 1500 }
    )
    .toBe('')
}

const expectFdeTopbarCompact = async (page: Page) => {
  await expect
    .poll(
      () =>
        page.evaluate(() => {
          const failures: string[] = []
          const viewportWidth = document.documentElement.clientWidth
          const statusCount = document.querySelectorAll('.brand .top-status').length
          const search = document.querySelector<HTMLElement>('.global-search')
          const topActions = document.querySelector<HTMLElement>('.top-actions')
          const searchRect = search?.getBoundingClientRect()
          const actionRect = topActions?.getBoundingClientRect()
          const maxSearchWidth = viewportWidth <= 1360 ? 362 : 482

          if (statusCount > 0) failures.push(`status:${statusCount}`)

          if (!searchRect || searchRect.width > maxSearchWidth) {
            failures.push(`search:${Math.round(searchRect?.width || 0)}/${maxSearchWidth}`)
          }

          if (!actionRect) {
            failures.push('actions:missing')
          } else {
            if (actionRect.height > 44) {
              failures.push(`actions-height:${Math.round(actionRect.height)}`)
            }
            if (actionRect.left < -2 || actionRect.right > viewportWidth + 2) {
              failures.push(
                `actions-offscreen:${Math.round(actionRect.left)}-${Math.round(actionRect.right)}`
              )
            }
          }

          const topActionTexts = Array.from(document.querySelectorAll('.top-actions > *'))
            .map((element) => (element.textContent || '').trim().replace(/\s+/g, ' '))
            .join('|')
          if (!topActionTexts.includes('治理摘要') || !topActionTexts.includes('FDE 工程师')) {
            failures.push(`actions-text:${topActionTexts}`)
          }

          return failures.join('\n')
        }),
      { timeout: 1500 }
    )
    .toBe('')
}

const selectProject = async (page: Page, projectName: string) => {
  const select = page.locator('.project-select')
  await expect(select).toBeVisible()
  await page.locator('.el-notification').evaluateAll((elements) => {
    elements.forEach((element) => element.remove())
  })
  await select.click()
  await page
    .locator('.el-select-dropdown:visible .el-select-dropdown__item')
    .filter({ hasText: projectName })
    .click()
  await page.waitForLoadState('networkidle')
  await expect(select).toContainText(projectName)
}

test.describe('AIcheck route smoke', () => {
  test('role accounts land on their default panel without redirect', async ({ page }) => {
    const cases = [
      { account: 'inspection', path: '/workbench/inspection', title: '监检工作台' },
      { account: 'contractor', path: '/workbench/contractor', title: '施工方工作台' },
      { account: 'ndt', path: '/workbench/ndt', title: '无损检测工作台' },
      { account: 'owner', path: '/workbench/owner', title: '建设方工作台' },
      { account: 'admin', path: '/admin/overview', title: '项目与权限配置' },
      { account: 'fde', path: '/fde/projects', title: '项目审计工作台' }
    ]

    for (const routeCase of cases) {
      await page.goto('/#/login')
      await clearLoginState(page)
      await loginWithoutRedirect(page, routeCase.account, routeCase.path)
      await expect(page.getByText(routeCase.title).first()).toBeVisible()
    }
  })

  test('business role falls back when redirect targets admin panel', async ({ page }) => {
    await page.goto(`/#/login?redirect=${encodeURIComponent('/admin/overview')}`)
    const loginInputs = page.locator('.auth-form .el-input__inner')

    await expect(loginInputs.first()).toBeVisible()
    await loginInputs.nth(0).fill('contractor')
    await loginInputs.nth(1).fill(passwordForAccount('contractor'))
    await page.getByRole('button', { name: /^登录$/ }).click()
    await page.waitForURL((url) => url.hash.includes('/workbench/contractor'))
    await expect(page.locator('.aicheck-page .page-title')).toContainText('施工方工作台')
  })

  for (const routeCase of routeCases) {
    test(`${routeCase.path} renders business page`, async ({ page }) => {
      await openRoute(page, routeCase)
      await expectNoPageOverflow(page)
    })
  }

  test('owner workbench keeps write actions unavailable', async ({ page }) => {
    await openRoute(page, routeCases.find((routeCase) => routeCase.path === '/workbench/owner')!)

    await expect(page.getByText('建设方只读视图')).toBeVisible()
    await expect(page.getByRole('button', { name: '上传资料' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'AI 复核' })).toHaveCount(0)
  })

  test('core pages fit a 390px mobile viewport', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 900 })

    for (const routeCase of routeCases.filter((item) =>
      ['/workbench/inspection', '/admin/overview', '/knowledge/overview', '/fde/projects'].includes(
        item.path
      )
    )) {
      await openRoute(page, routeCase)
      await expectNoPageOverflow(page)
    }
  })
})

test.describe('AIcheck deep route menu', () => {
  test('admin subroutes select static menu and matching tab', async ({ page }) => {
    await loginTo(page, adminDeepRouteCases[0].path)

    for (const routeCase of adminDeepRouteCases) {
      await page.goto(`/#${routeCase.path}`)
      await page.waitForURL((url) => url.hash.includes(routeCase.path))
      await page.waitForLoadState('networkidle')
      await expect(page.locator('.admin-page .page-title')).toContainText('项目与权限配置')
      await expect(page.locator('.static-tree-menu .tree-node.active').first()).toContainText(
        routeCase.menu
      )
      await expect(page.getByRole('tab', { name: routeCase.tab })).toHaveAttribute(
        'aria-selected',
        'true'
      )
      await expectNoPageOverflow(page)
    }
  })

  test('knowledge subroutes select static menu and matching tab', async ({ page }) => {
    await loginTo(page, knowledgeDeepRouteCases[0].path)

    for (const routeCase of knowledgeDeepRouteCases) {
      await page.goto(`/#${routeCase.path}`)
      await page.waitForURL((url) => url.hash.includes(routeCase.path))
      await page.waitForLoadState('networkidle')
      await expect(page.locator('.knowledge-page .page-title')).toContainText('AI 知识库管理')
      await expect(page.locator('.static-tree-menu .tree-node.active').first()).toContainText(
        routeCase.menu
      )
      await expect(page.getByRole('tab', { name: routeCase.tab })).toHaveAttribute(
        'aria-selected',
        'true'
      )
      await expectNoPageOverflow(page)
    }
  })

  test('fde subroutes select static menu and route context', async ({ page }) => {
    await loginTo(page, '/fde/projects')
    await waitForFdeProjectAuditReady(page)
    await expect(page.locator('.fde-console')).toContainText('项目审计工作台')

    for (const routeCase of fdeDeepRouteCases) {
      await page.goto(`/#${routeCase.path}`)
      await page.waitForURL((url) => url.hash.includes(routeCase.path))
      await page.waitForLoadState('networkidle')
      await waitForFdeProjectAuditReady(page)
      await expect(page.locator('.fde-console .page-title')).toContainText(routeCase.title)
      const activeTreeItem = page.locator('.static-tree-menu .tree-node.active').first()
      await expect(activeTreeItem).toContainText(routeCase.menu)
      await expect(activeTreeItem).toContainText('当前')
      await expect(page.locator('.project-audit-focus-facts')).toBeVisible()
      await expect(page.locator('.project-audit-focus-facts')).toContainText('当前节点')
      await expect(page.locator('.route-context')).toContainText(routeCase.context)
      if (routeCase.content) {
        await expect(page.locator('.fde-console')).toContainText(routeCase.content)
      }
      await expectFdeProjectTreeUsable(page)
      await expectNoPageOverflow(page)
      await expectFdeWorkspaceNotClipped(page)
    }
  })

  test('fde project audit pages do not clip cards at desktop widths', async ({ page }) => {
    const paths = ['/fde/projects', ...fdeDeepRouteCases.map((routeCase) => routeCase.path)]

    for (const width of [1280, 1024]) {
      await page.setViewportSize({ width, height: 820 })
      await loginTo(page, '/fde/projects')

      for (const path of paths) {
        await page.goto(`/#${path}`)
        await page.waitForURL((url) => url.hash.includes(path))
        await page.waitForLoadState('networkidle')
        await waitForFdeProjectAuditReady(page)
        await expect(page.locator('.fde-console .page-title')).toContainText('项目审计工作台')
        await expectFdeProjectTreeUsable(page)
        await expectNoPageOverflow(page)
        await expectFdeWorkspaceNotClipped(page)
      }
    }
  })

  test('fde topbar keeps actions single-line and search compact', async ({ page }) => {
    for (const width of [1440, 1280, 1024]) {
      await page.setViewportSize({ width, height: 820 })
      await loginTo(page, '/fde/projects')
      await waitForFdeProjectAuditReady(page)
      await expect(page.locator('.fde-console .page-title')).toContainText('项目审计工作台')
      await expectFdeTopbarCompact(page)
      await expectNoPageOverflow(page)
    }
  })

  test('fde mock audit data exposes OCR and agent evidence for UI review', async ({ page }) => {
    await loginTo(page, '/fde/projects')
    await page.goto('/#/fde/projects?projectId=P-2026-GDLNG-002&view=vectorization')
    await page.waitForLoadState('networkidle')
    await waitForFdeProjectAuditReady(page)

    await expectFdeProjectTreeUsable(page)
    await expect(page.locator('.fde-console')).toContainText('管道特性表')
    await expect(page.locator('.fde-console')).toContainText('质量证明书')
    await expect(page.locator('.fde-console')).toContainText('资料解析')
    await expect(page.locator('.fde-console')).toContainText('知识切片')
    await expect(page.locator('.fde-console')).toContainText('向量入库')
    await expect(page.locator('.fde-console')).toContainText('资料知识资产溯源')
    await expect(page.locator('.fde-console')).toContainText('每份资料为什么能进入 Agent 审查')
    await expect(page.locator('.fde-console')).toContainText('资料向量化链路图')
    await expect(page.locator('.fde-console .knowledge-chart-shell canvas').first()).toBeVisible()
    await expect(page.locator('.fde-console')).toContainText('向量条目')
    await expect(page.locator('.fde-console')).toContainText('PageIndex')
    await expect(page.locator('.fde-console')).toContainText('Lineage 来源')
    await expect(page.locator('.fde-console')).toContainText('后端审计投影')

    await page.goto('/#/fde/projects?view=pageindex')
    await page.waitForLoadState('networkidle')
    await waitForFdeProjectAuditReady(page)
    await expect(page.locator('.fde-console')).toContainText('PageIndex 友好判读')
    await expect(page.locator('.fde-console')).toContainText('每次检索为什么这样走')
    await expect(page.locator('.fde-console')).toContainText('PageIndex 检索溯源树')
    await expect(page.locator('.fde-console .knowledge-chart-shell canvas').first()).toBeVisible()
    await expect(page.locator('.fde-console')).toContainText('PageIndex 路由追踪')
    await expect(page.locator('.fde-console')).toContainText('问题分类')
    await expect(page.locator('.fde-console')).toContainText('条款映射')
    await expect(page.locator('.fde-console .pageindex-trace-card').first()).toContainText(
      '检索路由器'
    )
    await expect(page.locator('.fde-console')).toContainText('跨文件一致性与证据回放')
    await expect(page.locator('.fde-console')).toContainText('长文档跨章节检索')

    await page.goto('/#/fde/projects?view=langgraph')
    await page.waitForLoadState('networkidle')
    await waitForFdeProjectAuditReady(page)
    await expect(page.locator('.fde-console')).toContainText('LangGraph 编排图')
    await expect(page.locator('.fde-console')).toContainText('阶段泳道')
    await expect(page.locator('.fde-console')).toContainText('COG 可审计思考摘要')
    await expect(page.locator('.fde-console .langgraph-chart-shell canvas').first()).toBeVisible()
    await expect(page.locator('.fde-console')).toContainText('postgres')
    await expect(page.locator('.fde-console')).toContainText('Agent 思考链与工具证据')
    await expect(page.locator('.fde-console')).toContainText('审查草稿结果')
    await expect(page.locator('.fde-console .audit-step-card').first()).toContainText('证据/依据')
    await page.getByTestId('fde-open-review-detail').click()
    await expect(page.getByTestId('fde-review-drawer')).toBeVisible()
    await expect(page.getByTestId('fde-review-drawer')).toContainText('ReviewRun')
    const reviewDrawer = page.getByRole('dialog', { name: 'Agent 审查编排详情' })
    await expect(reviewDrawer).toContainText('可审计推理摘要')
    await expect(reviewDrawer).toContainText('工具调用')
    await expect(reviewDrawer).toContainText('证据/规则/条款')
    await expect(reviewDrawer.getByRole('button', { name: '记录诊断修正' })).toBeVisible()
    await expect(reviewDrawer.locator('.drawer-step-card').first()).toContainText('证据/依据')
    await reviewDrawer.getByRole('tab', { name: '结果' }).click()
    await expect(reviewDrawer).toContainText('建议动作')
    await expect(reviewDrawer).toContainText('人工确认')
    await page.keyboard.press('Escape')
    await expect(reviewDrawer).toBeHidden()

    await page.goto('/#/fde/projects?view=ocr-labeling')
    await page.waitForLoadState('networkidle')
    await waitForFdeProjectAuditReady(page)
    await expect(page.locator('.fde-console')).toContainText('标注覆盖率')
    await expect(page.locator('.fde-console')).toContainText('seal_text_profile')
    await expect(page.locator('.fde-console')).toContainText('ndt_rt_report_v1')
    await page.getByTestId('fde-open-ocr-detail').first().click()
    await expect(page.getByTestId('fde-ocr-drawer')).toBeVisible()
    await expect(page.getByTestId('fde-ocr-drawer')).toContainText('OCR Job')
    const ocrDrawer = page.getByRole('dialog', { name: 'OCR 任务审计详情' })
    await expect(ocrDrawer).toContainText('候选图')
    await expect(ocrDrawer).toContainText('字段问题')
    await expect(ocrDrawer).toContainText('证据缺口')
    await expect(ocrDrawer).toContainText('引擎')
    await page.keyboard.press('Escape')
    await expect(ocrDrawer).toBeHidden()

    await page.goto('/#/fde/projects?view=evaluation')
    await page.waitForLoadState('networkidle')
    await waitForFdeProjectAuditReady(page)
    await expect(page.locator('.fde-console')).toContainText('准确率评估门禁')
    await expect(page.locator('.fde-console')).toContainText('OCR 100')
    await expect(page.locator('.fde-console')).toContainText('Agent 评分')
    await expectNoPageOverflow(page)
    await expectFdeWorkspaceNotClipped(page)
  })
})

test.describe('AIcheck live business error mapping', () => {
  test('admin publish shows recovery hint and live error code', async ({ page }) => {
    await page.route('**/api/admin/config-overview/publish', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(
          businessError(40904, '配置发布数据版本已变化，请刷新后重试。', 'ETAG_CONFLICT')
        )
      })
    })

    await openRoute(page, routeCases.find((routeCase) => routeCase.path === '/admin/overview')!)
    await page.getByRole('button', { name: '发布配置' }).evaluate((element) => {
      ;(element as HTMLButtonElement).click()
    })

    const issue = page
      .locator('.error-stack .local-error')
      .filter({ hasText: '错误码：ETAG_CONFLICT' })
    await expect(issue).toBeVisible()
    await expect(issue).toContainText('请先刷新最新数据')
  })

  test('knowledge retrieval failure stays local and retryable', async ({ page }) => {
    await page.route('**/api/knowledge/retrieval-test', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(
          businessError(40902, '知识库检索测试已有任务正在运行，请稍后查看进度。', 'TASK_RUNNING')
        )
      })
    })

    await openRoute(page, routeCases.find((routeCase) => routeCase.path === '/knowledge/overview')!)
    await page.getByRole('tab', { name: '检索测试' }).click()
    await page.locator('textarea:visible').first().fill('焊工资格证有效期如何校验？')
    await page.getByRole('button', { name: '运行检索' }).click()

    const issue = page.locator('.local-operation-error').filter({ hasText: '错误码：TASK_RUNNING' })
    await expect(issue).toBeVisible()
    await expect(issue).toContainText('已有任务正在运行')
    await expect(issue.getByRole('button', { name: '重试检索' })).toBeVisible()
  })

  test('workbench ai recheck maps live business error in action toast', async ({ page }) => {
    await page.route('**/api/projects/*/inspection/nodes/*/ai-recheck', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(
          businessError(40902, 'AI 复核已有任务正在运行，请稍后查看进度。', 'TASK_RUNNING')
        )
      })
    })

    await openRoute(
      page,
      routeCases.find((routeCase) => routeCase.path === '/workbench/inspection')!
    )
    await page.getByRole('button', { name: 'AI 复核' }).click()

    const message = page.locator('.el-message').filter({ hasText: '错误码：TASK_RUNNING' })
    await expect(message).toBeVisible()
    await expect(message).toContainText('已有任务正在运行')
  })
})

test.describe('AIcheck business writeback flows', () => {
  test('contractor submits rectification feedback and node enters review', async ({ page }) => {
    await openRoute(
      page,
      routeCases.find((routeCase) => routeCase.path === '/workbench/contractor')!
    )

    await page.getByRole('button', { name: '提交补正' }).click()
    const dialog = page.locator('.el-dialog').filter({ hasText: '补正详情与反馈' })
    await expect(dialog).toBeVisible()
    await dialog.getByLabel('补正反馈说明').fill('E2E 已补充焊工资格证附件，请监检复审。')
    await dialog.getByRole('button', { name: '提交补正反馈' }).click()

    await expect(page.locator('.el-message').filter({ hasText: '补正反馈已提交' })).toBeVisible()
    await expect(page.locator('.node-panel')).toContainText('复审中')
  })

  test('contractor submits node package batch and opens submission snapshot', async ({ page }) => {
    await openRoute(
      page,
      routeCases.find((routeCase) => routeCase.path === '/workbench/contractor')!
    )

    await page.getByRole('button', { name: '提交批次' }).click()
    const dialog = page.locator('.el-dialog').filter({ hasText: '选择本次要提交或撤回的资料项' })
    await expect(dialog).toBeVisible()
    await expect(dialog).toContainText('钢管质量证明书.pdf')

    await dialog.locator('.el-table__body-wrapper .el-checkbox__input').first().click()
    await dialog
      .locator('.el-form-item')
      .filter({ hasText: '提交说明' })
      .locator('textarea')
      .fill('E2E 提交节点资料批次，进入 AI 预审。')
    await dialog.getByRole('button', { name: '提交批次' }).click()

    await expect(
      page.locator('.el-message').filter({ hasText: '节点资料已提交，进入 AI 预审' })
    ).toBeVisible()
    const snapshotDrawer = page.locator('.el-drawer').filter({ hasText: '提交批次详情' })
    await expect(snapshotDrawer).toBeVisible()
    await expect(snapshotDrawer).toContainText('AI 预审中')
    await expect(snapshotDrawer).toContainText('E2E 提交节点资料批次')
  })

  test('contractor submission dialog keeps form and retries after submit failure', async ({
    page
  }) => {
    let submitAttempts = 0
    await page.route('**/api/projects/*/submissions', async (route) => {
      if (route.request().method() === 'POST') {
        submitAttempts += 1
        if (submitAttempts === 1) {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(
              businessError(40904, '节点资料提交数据版本已变化，请刷新后重试。', 'ETAG_CONFLICT')
            )
          })
          return
        }
      }
      await route.fallback()
    })

    await openRoute(
      page,
      routeCases.find((routeCase) => routeCase.path === '/workbench/contractor')!
    )

    const batchName = `E2E 提交失败恢复 ${Date.now()}`
    const comment = 'E2E 首次提交失败后保留弹窗输入，并按原内容重试。'

    await page.getByRole('button', { name: '提交批次' }).click()
    const dialog = page.locator('.el-dialog').filter({ hasText: '选择本次要提交或撤回的资料项' })
    await expect(dialog).toBeVisible()
    await dialog.locator('.el-table__body-wrapper .el-checkbox__input').first().click()
    const batchNameInput = dialog
      .locator('.el-form-item')
      .filter({ hasText: '批次名称' })
      .locator('input')
    const commentInput = dialog
      .locator('.el-form-item')
      .filter({ hasText: '提交说明' })
      .locator('textarea')
    await batchNameInput.fill(batchName)
    await commentInput.fill(comment)
    await dialog.getByRole('button', { name: '提交批次' }).click()

    const issue = dialog.locator('.submission-dialog-error').filter({ hasText: 'ETAG_CONFLICT' })
    await expect(issue).toBeVisible()
    await expect(issue).toContainText('请先刷新最新数据')
    await expect(batchNameInput).toHaveValue(batchName)
    await expect(commentInput).toHaveValue(comment)

    await issue.getByRole('button', { name: '重试提交' }).click()

    const snapshotDrawer = page.locator('.el-drawer').filter({ hasText: '提交批次详情' })
    await expect(snapshotDrawer).toBeVisible()
    await expect(snapshotDrawer).toContainText(batchName)
    await expect(snapshotDrawer).toContainText('AI 预审中')
    expect(submitAttempts).toBeGreaterThanOrEqual(2)

    await page.setViewportSize({ width: 390, height: 900 })
    await expectNoPageOverflow(page)
  })

  test('contractor bind dialog keeps selection and retries after failure', async ({ page }) => {
    let bindAttempts = 0
    await page.route('**/api/projects/*/documents/bindings', async (route) => {
      if (route.request().method() === 'POST') {
        bindAttempts += 1
        if (bindAttempts === 1) {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(
              businessError(40904, '资料挂载数据版本已变化，请刷新后重试。', 'ETAG_CONFLICT')
            )
          })
          return
        }
      }
      await route.fallback()
    })

    await openRoute(
      page,
      routeCases.find((routeCase) => routeCase.path === '/workbench/contractor')!
    )

    await page.getByRole('button', { name: '挂载资料' }).click()
    const bindDialog = page.locator('.el-dialog').filter({ hasText: '挂载资料到节点' })
    await expect(bindDialog).toBeVisible()

    await bindDialog
      .locator('.el-form-item')
      .filter({ hasText: '挂载用途' })
      .locator('.el-select')
      .click()
    await page.getByRole('option', { name: '补正附件' }).click()
    await bindDialog.locator('.target-node-field .el-select').click()
    await page
      .locator('.el-select-dropdown:visible .el-select-dropdown__item')
      .filter({ hasText: '25 ·' })
      .click()
    await bindDialog.getByRole('button', { name: '确认挂载' }).click()

    const issue = bindDialog.locator('.bind-dialog-error').filter({ hasText: 'ETAG_CONFLICT' })
    await expect(issue).toBeVisible()
    await expect(issue).toContainText('请先刷新最新数据')
    await expect(bindDialog).toContainText('补正附件')
    await expect(bindDialog).toContainText('+ 1')

    await issue.getByRole('button', { name: '重试挂载' }).click()

    await expect(bindDialog).toBeHidden()
    await expect(page.locator('.node-panel')).toContainText('部分提交')
    expect(bindAttempts).toBeGreaterThanOrEqual(2)

    await page.setViewportSize({ width: 390, height: 900 })
    await expectNoPageOverflow(page)
  })

  test('contractor upload drawer keeps files and retries after failure', async ({ page }) => {
    let uploadAttempts = 0
    await page.route('**/api/projects/*/documents/upload-session', async (route) => {
      if (route.request().method() === 'POST') {
        uploadAttempts += 1
        if (uploadAttempts === 1) {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(
              businessError(40016, 'E2E-超限文件.pdf 超过 50MB 上传限制。', 'FILE_TOO_LARGE')
            )
          })
          return
        }
      }
      await route.fallback()
    })

    await openRoute(
      page,
      routeCases.find((routeCase) => routeCase.path === '/workbench/contractor')!
    )

    const fileName = `E2E 上传失败恢复 ${Date.now()}.pdf`

    await page.getByRole('button', { name: '上传资料' }).click()
    const drawer = page.locator('.el-drawer').filter({ hasText: '创建上传会话' })
    await expect(drawer).toBeVisible()
    const fileNameInput = drawer.locator('input[aria-label="文件名称"]').first()
    await fileNameInput.fill(fileName)
    await drawer.getByRole('button', { name: '创建并入库' }).click()

    const issue = drawer.locator('.upload-drawer-error').filter({ hasText: 'FILE_TOO_LARGE' })
    await expect(issue).toBeVisible()
    await expect(issue).toContainText('请压缩文件')
    await expect(fileNameInput).toHaveValue(fileName)

    await page.setViewportSize({ width: 390, height: 900 })
    await expectNoPageOverflow(page)

    await issue.getByRole('button', { name: '重试创建' }).click()

    await expect(drawer).toBeHidden()
    await expect(page.locator('.node-panel')).toContainText(fileName)
    expect(uploadAttempts).toBeGreaterThanOrEqual(2)
  })

  test('contractor withdraws submitted item and traces it in submission history', async ({
    page
  }) => {
    await openRoute(
      page,
      routeCases.find((routeCase) => routeCase.path === '/workbench/contractor')!
    )

    const reason = `E2E 撤回原因 ${Date.now()}`

    await page.getByRole('button', { name: '提交批次' }).click()
    const submitDialog = page
      .locator('.el-dialog')
      .filter({ hasText: '选择本次要提交或撤回的资料项' })
    await expect(submitDialog).toBeVisible()
    await submitDialog.locator('.el-table__body-wrapper .el-checkbox__input').first().click()
    await submitDialog
      .locator('.el-form-item')
      .filter({ hasText: '提交说明' })
      .locator('textarea')
      .fill('E2E 提交后立即撤回，验证历史追溯。')
    await submitDialog.getByRole('button', { name: '提交批次' }).click()

    const snapshotDrawer = page.locator('.el-drawer').filter({ hasText: '提交批次详情' })
    await expect(snapshotDrawer).toBeVisible()
    await snapshotDrawer.locator('.el-drawer__close-btn').click()
    await expect(snapshotDrawer).toBeHidden()

    await page.getByRole('button', { name: '撤回未提交' }).click()
    const withdrawDialog = page
      .locator('.el-dialog')
      .filter({ hasText: '选择本次要提交或撤回的资料项' })
    await expect(withdrawDialog).toBeVisible()
    await withdrawDialog.locator('.el-table__body-wrapper .el-checkbox__input').first().click()
    await withdrawDialog
      .locator('.el-form-item')
      .filter({ hasText: '撤回原因' })
      .locator('textarea')
      .fill(reason)
    await withdrawDialog.getByRole('button', { name: '撤回未提交项' }).click()

    await expect(
      page.locator('.el-message').filter({ hasText: '提交项已撤回为草稿挂载' })
    ).toBeVisible()
    const historyDrawer = page.locator('.submission-history-drawer')
    await expect(historyDrawer).toBeVisible()
    await expect(historyDrawer.locator('.submission-history-table')).toContainText('部分提交')
    await expect(historyDrawer.locator('.submission-history-table')).toContainText('撤回 1 项')
    await expect(historyDrawer.locator('.submission-history-table')).toContainText(reason)

    await historyDrawer
      .locator('.submission-history-table')
      .getByRole('button', { name: '详情' })
      .first()
      .click()
    const traceDetailDrawer = page.locator('.el-drawer').filter({ hasText: '提交批次详情' })
    await expect(traceDetailDrawer).toContainText('撤回追溯')
    await expect(traceDetailDrawer).toContainText(reason)

    await page.setViewportSize({ width: 390, height: 900 })
    await expectNoPageOverflow(page)
  })

  test('contractor withdraw dialog keeps reason and retries after failure', async ({ page }) => {
    let withdrawAttempts = 0
    await page.route('**/api/projects/*/submissions/*/withdraw-items', async (route) => {
      if (route.request().method() === 'POST') {
        withdrawAttempts += 1
        if (withdrawAttempts === 1) {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(businessError(40921, '已通过资料不能撤回。', 'WITHDRAW_LOCKED'))
          })
          return
        }
      }
      await route.fallback()
    })

    await openRoute(
      page,
      routeCases.find((routeCase) => routeCase.path === '/workbench/contractor')!
    )

    const reason = `E2E 撤回失败恢复 ${Date.now()}`

    await page.getByRole('button', { name: '提交批次' }).click()
    const submitDialog = page
      .locator('.el-dialog')
      .filter({ hasText: '选择本次要提交或撤回的资料项' })
    await expect(submitDialog).toBeVisible()
    await submitDialog.locator('.el-table__body-wrapper .el-checkbox__input').first().click()
    await submitDialog
      .locator('.el-form-item')
      .filter({ hasText: '提交说明' })
      .locator('textarea')
      .fill('E2E 为撤回失败恢复用例准备提交快照。')
    await submitDialog.getByRole('button', { name: '提交批次' }).click()

    const snapshotDrawer = page.locator('.el-drawer').filter({ hasText: '提交批次详情' })
    await expect(snapshotDrawer).toBeVisible()
    await snapshotDrawer.locator('.el-drawer__close-btn').click()
    await expect(snapshotDrawer).toBeHidden()

    await page.getByRole('button', { name: '撤回未提交' }).click()
    const withdrawDialog = page
      .locator('.el-dialog')
      .filter({ hasText: '选择本次要提交或撤回的资料项' })
    await expect(withdrawDialog).toBeVisible()
    await withdrawDialog.locator('.el-table__body-wrapper .el-checkbox__input').first().click()
    const reasonInput = withdrawDialog
      .locator('.el-form-item')
      .filter({ hasText: '撤回原因' })
      .locator('textarea')
    await reasonInput.fill(reason)
    await withdrawDialog.getByRole('button', { name: '撤回未提交项' }).click()

    const issue = withdrawDialog
      .locator('.submission-dialog-error')
      .filter({ hasText: 'WITHDRAW_LOCKED' })
    await expect(issue).toBeVisible()
    await expect(issue).toContainText('已通过或锁定资料不能撤回')
    await expect(reasonInput).toHaveValue(reason)

    await issue.getByRole('button', { name: '重试撤回' }).click()

    const historyDrawer = page.locator('.submission-history-drawer')
    await expect(historyDrawer).toBeVisible()
    await expect(historyDrawer).toContainText(reason)
    await expect(historyDrawer).toContainText('部分提交')
    expect(withdrawAttempts).toBeGreaterThanOrEqual(2)

    await page.setViewportSize({ width: 390, height: 900 })
    await expectNoPageOverflow(page)
  })

  test('contractor restores cross-node draft from history and submits the scope', async ({
    page
  }) => {
    await openRoute(
      page,
      routeCases.find((routeCase) => routeCase.path === '/workbench/contractor')!
    )

    await page.getByRole('button', { name: '挂载资料' }).click()
    const bindDialog = page.locator('.el-dialog').filter({ hasText: '挂载资料到节点' })
    await expect(bindDialog).toBeVisible()
    await bindDialog.locator('.target-node-field .el-select').click()
    await page
      .locator('.el-select-dropdown:visible .el-select-dropdown__item')
      .filter({ hasText: '25 ·' })
      .click()
    await bindDialog.getByRole('button', { name: '确认挂载' }).click()

    await expect(
      page.locator('.el-message').filter({ hasText: '资料已挂载到 2 个节点' })
    ).toBeVisible()

    const batchName = `E2E 跨节点草稿 ${Date.now()}`
    await page.getByRole('button', { name: '提交批次' }).click()
    const submissionDialog = page.locator('.el-dialog').filter({ hasText: '跨节点提交未勾选资料' })
    await expect(submissionDialog).toBeVisible()
    await submissionDialog
      .locator('.el-form-item')
      .filter({ hasText: '批次名称' })
      .locator('input')
      .fill(batchName)
    await submissionDialog.locator('.submission-node-scope-field .el-select').click()
    await page
      .locator('.el-select-dropdown:visible .el-select-dropdown__item')
      .filter({ hasText: '25 ·' })
      .click()
    await submissionDialog
      .locator('.el-form-item')
      .filter({ hasText: '提交说明' })
      .locator('textarea')
      .fill('E2E 保存跨节点范围草稿，随后从历史恢复并提交。')
    await submissionDialog.getByRole('button', { name: '保存为草稿' }).click()

    const draftDrawer = page.locator('.el-drawer').filter({ hasText: '提交草稿详情' })
    await expect(draftDrawer).toBeVisible()
    await expect(draftDrawer).toContainText(batchName)
    await expect(draftDrawer).toContainText('25')
    await draftDrawer.locator('.el-drawer__close-btn').click()
    await expect(draftDrawer).toBeHidden()

    await page.getByRole('button', { name: '提交历史' }).click()
    const historyDrawer = page.locator('.submission-history-drawer')
    await expect(historyDrawer).toBeVisible()
    await expect(historyDrawer).toContainText(batchName)
    await historyDrawer
      .locator('.submission-draft-table')
      .getByRole('button', { name: '恢复草稿' })
      .first()
      .click()

    await expect(
      page.locator('.el-message').filter({ hasText: '提交草稿已恢复到提交批次弹窗' })
    ).toBeVisible()
    const restoredDialog = page.locator('.el-dialog').filter({ hasText: '跨节点提交未勾选资料' })
    await expect(restoredDialog).toBeVisible()
    await expect(restoredDialog).toContainText('已恢复历史草稿')
    await expect(
      restoredDialog.locator('.el-form-item').filter({ hasText: '批次名称' }).locator('input')
    ).toHaveValue(batchName)
    await restoredDialog.getByRole('button', { name: '提交批次' }).click()

    const snapshotDrawer = page.locator('.el-drawer').filter({ hasText: '提交批次详情' })
    await expect(snapshotDrawer).toBeVisible()
    await expect(snapshotDrawer).toContainText(batchName)
    await expect(snapshotDrawer).toContainText('AI 预审中')
    await expect(snapshotDrawer).toContainText('25')
  })

  test('ndt imports inspection record into the workflow table', async ({ page }) => {
    await openRoute(page, routeCases.find((routeCase) => routeCase.path === '/workbench/ndt')!)

    const recordNo = `REC-E2E-${Date.now()}`
    const panel = page.locator('.ndt-panel')
    const recordForm = panel.locator('.record-form')
    await recordForm
      .locator('.el-form-item')
      .filter({ hasText: '记录编号' })
      .locator('input')
      .fill(recordNo)
    await recordForm
      .locator('.el-form-item')
      .filter({ hasText: '焊口编号' })
      .locator('input')
      .fill('W-E2E-001')
    await recordForm.getByRole('button', { name: '导入检测记录' }).click()

    await expect(
      page.locator('.el-message').filter({ hasText: '已导入 1 条检测记录' })
    ).toBeVisible()
    await expect(panel).toContainText(recordNo)
  })

  test('ndt film form keeps input and retries after failure', async ({ page }) => {
    let filmAttempts = 0
    await page.route('**/api/projects/*/ndt/films', async (route) => {
      if (route.request().method() === 'POST') {
        filmAttempts += 1
        if (filmAttempts === 1) {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(
              businessError(
                40902,
                '新增无损检测底片已有任务正在运行，请稍后查看进度。',
                'TASK_RUNNING'
              )
            )
          })
          return
        }
      }
      await route.fallback()
    })

    await openRoute(page, routeCases.find((routeCase) => routeCase.path === '/workbench/ndt')!)

    const panel = page.locator('.ndt-panel')
    const filmForm = panel.locator('.inline-form')
    const filmNo = `FILM-E2E-${Date.now()}`
    const weldNo = 'W-E2E-FILM-001'
    const filmNoInput = filmForm
      .locator('.el-form-item')
      .filter({ hasText: '底片编号' })
      .locator('input')

    await filmNoInput.fill(filmNo)
    await filmForm
      .locator('.el-form-item')
      .filter({ hasText: '焊口编号' })
      .locator('input')
      .fill(weldNo)
    await filmForm.getByRole('button', { name: '新增底片' }).click()

    const issue = panel.locator('.ndt-film-error').filter({ hasText: 'TASK_RUNNING' })
    await expect(issue).toBeVisible()
    await expect(issue).toContainText('已有任务正在运行')
    await expect(filmNoInput).toHaveValue(filmNo)

    await page.setViewportSize({ width: 390, height: 900 })
    await expectNoPageOverflow(page)

    await issue.getByRole('button', { name: '重试新增底片' }).click()

    await expect(issue).toBeHidden()
    await expect(panel).toContainText(filmNo)
    expect(filmAttempts).toBeGreaterThanOrEqual(2)
  })

  test('ndt record import form keeps input and retries after failure', async ({ page }) => {
    let importAttempts = 0
    await page.route('**/api/projects/*/ndt/records/import', async (route) => {
      if (route.request().method() === 'POST') {
        importAttempts += 1
        if (importAttempts === 1) {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(
              businessError(
                40902,
                '导入无损检测记录已有任务正在运行，请稍后查看进度。',
                'TASK_RUNNING'
              )
            )
          })
          return
        }
      }
      await route.fallback()
    })

    await openRoute(page, routeCases.find((routeCase) => routeCase.path === '/workbench/ndt')!)

    const panel = page.locator('.ndt-panel')
    const recordForm = panel.locator('.record-form')
    const recordNo = `REC-E2E-RETRY-${Date.now()}`
    const recordNoInput = recordForm
      .locator('.el-form-item')
      .filter({ hasText: '记录编号' })
      .locator('input')

    await recordNoInput.fill(recordNo)
    await recordForm
      .locator('.el-form-item')
      .filter({ hasText: '焊口编号' })
      .locator('input')
      .fill('W-E2E-RETRY-001')
    await recordForm.getByRole('button', { name: '导入检测记录' }).click()

    const issue = panel.locator('.ndt-record-import-error').filter({ hasText: 'TASK_RUNNING' })
    await expect(issue).toBeVisible()
    await expect(issue).toContainText('已有任务正在运行')
    await expect(recordNoInput).toHaveValue(recordNo)

    await page.setViewportSize({ width: 390, height: 900 })
    await expectNoPageOverflow(page)

    await issue.getByRole('button', { name: '重试导入记录' }).click()

    await expect(issue).toBeHidden()
    await expect(panel).toContainText(recordNo)
    expect(importAttempts).toBeGreaterThanOrEqual(2)
  })

  test('ndt report upload form keeps input and retries after failure', async ({ page }) => {
    let uploadAttempts = 0
    await page.route('**/api/projects/*/ndt/reports/upload-session', async (route) => {
      if (route.request().method() === 'POST') {
        uploadAttempts += 1
        if (uploadAttempts === 1) {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(
              businessError(
                40042,
                'E2E-NDT-超限报告.pdf 超过 100MB 上传限制。',
                'NDT_FILE_TOO_LARGE'
              )
            )
          })
          return
        }
      }
      await route.fallback()
    })

    await openRoute(page, routeCases.find((routeCase) => routeCase.path === '/workbench/ndt')!)

    const panel = page.locator('.ndt-panel')
    const reportForm = panel.locator('.report-form')
    const actions = panel.locator('.ndt-actions')
    const fileName = `E2E-NDT-上传失败恢复-${Date.now()}.pdf`
    const pendingBeforeText = await actions.innerText()
    const pendingBefore = Number(pendingBeforeText.match(/待提交报告\s+(\d+)/)?.[1] || 0)
    const fileNameInput = reportForm
      .locator('.el-form-item')
      .filter({ hasText: '报告文件名' })
      .locator('input')

    await fileNameInput.fill(fileName)
    await reportForm.getByRole('button', { name: '创建报告上传会话' }).click()

    const issue = panel
      .locator('.ndt-report-upload-error')
      .filter({ hasText: 'NDT_FILE_TOO_LARGE' })
    await expect(issue).toBeVisible()
    await expect(issue).toContainText('请压缩检测资料')
    await expect(fileNameInput).toHaveValue(fileName)

    await page.setViewportSize({ width: 390, height: 900 })
    await expectNoPageOverflow(page)

    await issue.getByRole('button', { name: '重试上传会话' }).click()

    await expect(issue).toBeHidden()
    await expect(actions).toContainText(`待提交报告 ${pendingBefore + 1}`)
    expect(uploadAttempts).toBeGreaterThanOrEqual(2)
  })

  test('ndt submit keeps pending reports and retries after failure', async ({ page }) => {
    let submitAttempts = 0
    await page.route('**/api/projects/*/ndt/submissions', async (route) => {
      if (route.request().method() === 'POST') {
        submitAttempts += 1
        if (submitAttempts === 1) {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(
              businessError(
                40902,
                '提交无损检测资料已有任务正在运行，请稍后查看进度。',
                'TASK_RUNNING'
              )
            )
          })
          return
        }
      }
      await route.fallback()
    })

    await openRoute(page, routeCases.find((routeCase) => routeCase.path === '/workbench/ndt')!)

    const panel = page.locator('.ndt-panel')
    const actions = panel.locator('.ndt-actions')
    await expect(actions).toContainText(/待提交报告 [1-9]/)
    const pendingBeforeText = await actions.innerText()
    const pendingBefore = Number(pendingBeforeText.match(/待提交报告\s+(\d+)/)?.[1] || 0)

    await panel.getByRole('button', { name: '提交检测资料' }).click()

    const issue = panel.locator('.ndt-submit-error').filter({ hasText: 'TASK_RUNNING' })
    await expect(issue).toBeVisible()
    await expect(issue).toContainText('已有任务正在运行')
    await expect(actions).toContainText(`待提交报告 ${pendingBefore}`)

    await page.setViewportSize({ width: 390, height: 900 })
    await expectNoPageOverflow(page)

    await issue.getByRole('button', { name: '重试提交' }).click()

    await expect(issue).toBeHidden()
    await expect(panel).toContainText('待审查')
    expect(submitAttempts).toBeGreaterThanOrEqual(2)
  })

  test('ndt submits inspection reports for review', async ({ page }) => {
    await openRoute(page, routeCases.find((routeCase) => routeCase.path === '/workbench/ndt')!)

    const panel = page.locator('.ndt-panel')
    const reportForm = panel.locator('.report-form')
    const fileName = `E2E-NDT-待提交报告-${Date.now()}.pdf`
    await reportForm
      .locator('.el-form-item')
      .filter({ hasText: '报告文件名' })
      .locator('input')
      .fill(fileName)
    await reportForm.getByRole('button', { name: '创建报告上传会话' }).click()

    await expect(panel.locator('.ndt-actions')).toContainText(/待提交报告 [1-9]/)
    await panel.getByRole('button', { name: '提交检测资料' }).click()

    await expect(panel).toContainText(fileName.replace('.pdf', ''))
    await expect(panel).toContainText('待审查')
  })

  test('ndt rectification form keeps feedback and retries after failure', async ({ page }) => {
    let rectificationAttempts = 0
    await page.route('**/api/projects/*/ndt/rectifications', async (route) => {
      if (route.request().method() === 'POST') {
        rectificationAttempts += 1
        if (rectificationAttempts === 1) {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(
              businessError(
                40902,
                '提交无损检测补正反馈已有任务正在运行，请稍后查看进度。',
                'TASK_RUNNING'
              )
            )
          })
          return
        }
      }
      await route.fallback()
    })

    await openRoute(page, routeCases.find((routeCase) => routeCase.path === '/workbench/ndt')!)

    const panel = page.locator('.ndt-panel')
    const rectifyForm = panel.locator('.rectify-form')
    const description = `E2E NDT 补正失败恢复 ${Date.now()}`
    const descriptionInput = rectifyForm
      .locator('.el-form-item')
      .filter({ hasText: '反馈说明' })
      .locator('textarea')

    await expect(rectifyForm.getByRole('button', { name: '提交补正反馈' })).toBeEnabled()
    await descriptionInput.fill(description)
    await rectifyForm.getByRole('button', { name: '提交补正反馈' }).click()

    const issue = panel.locator('.ndt-rectify-error').filter({ hasText: 'TASK_RUNNING' })
    await expect(issue).toBeVisible()
    await expect(issue).toContainText('已有任务正在运行')
    await expect(descriptionInput).toHaveValue(description)

    await page.setViewportSize({ width: 390, height: 900 })
    await expectNoPageOverflow(page)

    await issue.getByRole('button', { name: '重试补正反馈' }).click()

    await expect(issue).toBeHidden()
    await expect(panel).toContainText('已反馈')
    expect(rectificationAttempts).toBeGreaterThanOrEqual(2)
  })

  test('admin creates todo rule and receives config diff', async ({ page }) => {
    await openRoute(page, routeCases.find((routeCase) => routeCase.path === '/admin/overview')!)

    await page.getByRole('tab', { name: '细项配置' }).click()
    await page
      .locator('.panel')
      .filter({ hasText: '待办规则' })
      .getByRole('button', { name: '新增' })
      .click()

    const ruleName = `E2E 待办规则 ${Date.now()}`
    const drawer = page.locator('.el-drawer').filter({ hasText: '新增待办规则' })
    await expect(drawer).toBeVisible()
    await drawer
      .locator('.el-form-item')
      .filter({ hasText: '规则名称' })
      .locator('input')
      .fill(ruleName)
    await drawer
      .locator('.el-form-item')
      .filter({ hasText: '触发状态' })
      .locator('input')
      .fill('E2E 待处理')
    await drawer
      .locator('.el-form-item')
      .filter({ hasText: '变更原因' })
      .locator('textarea')
      .fill('E2E 新增待办规则，用于集成验收。')
    await drawer.getByRole('button', { name: '新增配置' }).click()

    await expect(page.locator('.el-message').filter({ hasText: '待办规则已新增' })).toBeVisible()
    const diffDialog = page.locator('.el-dialog').filter({ hasText: '配置差异' })
    await expect(diffDialog).toBeVisible()
    await expect(diffDialog).toContainText(ruleName)
  })

  test('admin exports config package and surfaces export task card', async ({ page }) => {
    await openRoute(page, routeCases.find((routeCase) => routeCase.path === '/admin/overview')!)

    await page.getByRole('button', { name: '导出配置包' }).evaluate((element) => {
      ;(element as HTMLButtonElement).click()
    })

    await expect(
      page.locator('.el-message').filter({ hasText: '配置包已生成：后台配置包-all-20260626.zip' })
    ).toBeVisible()
    const configPanel = page.locator('.config-panel')
    await expect(configPanel).toContainText('后台配置包-all-20260626.zip')
    await expect(configPanel).toContainText('可下载')
  })

  test('admin publishes config and reviews linked impact trace', async ({ page }) => {
    await openRoute(page, routeCases.find((routeCase) => routeCase.path === '/admin/overview')!)

    await page.getByRole('button', { name: '发布配置' }).evaluate((element) => {
      ;(element as HTMLButtonElement).click()
    })

    await expect(page.locator('.el-message').filter({ hasText: '配置已发布' })).toBeVisible()
    const configPanel = page.locator('.config-panel')
    await expect(configPanel).toContainText('最近发布：config-v')
    await expect(configPanel).toContainText('在检项目')
    await expect(configPanel).toContainText('推送')
    await expect(configPanel).toContainText('条消息')

    await configPanel.getByRole('button', { name: '查看联动' }).click()
    const traceDialog = page.locator('.el-dialog').filter({ hasText: '发布联动追溯' })
    await expect(traceDialog).toBeVisible()
    await expect(traceDialog).toContainText('工作台消息')
    await expect(traceDialog).toContainText('复核待办')
    await expect(traceDialog).toContainText('权限矩阵已同步到工作台动作权限')
    await expect(traceDialog).toContainText('消息模板已刷新待办通知')
    await expect(traceDialog).toContainText('字段映射阈值变更后需在真实 OCR 样例中复核')
    await page.locator('.el-notification').evaluateAll((elements) => {
      elements.forEach((element) => element.remove())
    })
    await traceDialog.locator('.el-dialog__headerbtn').click()
    await expect(traceDialog).toBeHidden()

    await openRoute(
      page,
      routeCases.find((routeCase) => routeCase.path === '/workbench/inspection')!
    )
    await page.getByRole('button', { name: '消息' }).click()
    const quickDialog = page.locator('.el-dialog').filter({ hasText: '全局入口' })
    await expect(quickDialog).toBeVisible()
    await expect(quickDialog).toContainText('后台配置已发布：config-v')
    await expect(quickDialog).toContainText('发布范围 all')
    await quickDialog.getByRole('tab', { name: /待办/ }).click()
    await expect(quickDialog).toContainText('字段映射配置发布影响')

    await page.setViewportSize({ width: 390, height: 900 })
    await expectNoPageOverflow(page)
  })

  test('admin authorizes a project member and refreshes member table', async ({ page }) => {
    await openRoute(page, routeCases.find((routeCase) => routeCase.path === '/admin/overview')!)

    const projectRow = page.getByRole('row').filter({ hasText: '华东成品油管道改造工程' })
    await projectRow.getByRole('button', { name: '详情' }).click()
    const projectDrawer = page.locator('.el-drawer').filter({ hasText: '项目详情与成员授权' })
    await expect(projectDrawer).toBeVisible()
    await expect(projectDrawer).toContainText('成员授权')

    await projectDrawer.getByRole('button', { name: '新增授权' }).click()
    const memberDialog = page.locator('.el-dialog').filter({ hasText: '项目成员授权' })
    await expect(memberDialog).toBeVisible()
    await memberDialog
      .locator('.el-form-item')
      .filter({ hasText: '角色' })
      .locator('.el-select')
      .click()
    await page.getByRole('option', { name: '管理' }).click()
    await memberDialog
      .locator('.el-form-item')
      .filter({ hasText: '节点范围' })
      .locator('input')
      .fill('16,24,40,59')
    await memberDialog
      .locator('.el-form-item')
      .filter({ hasText: '到期时间' })
      .locator('input')
      .fill('2026-12-31 18:00:00')
    await memberDialog.getByRole('button', { name: '保存' }).click()

    await expect(
      page.locator('.el-message').filter({ hasText: '项目成员授权已保存' })
    ).toBeVisible()
    await expect(projectDrawer).toContainText('5 名成员')
    await expect(projectDrawer).toContainText('系统管理员')
    await expect(projectDrawer).toContainText('管理')
  })

  test('admin creates project through setup wizard and opens project detail', async ({ page }) => {
    await openRoute(page, routeCases.find((routeCase) => routeCase.path === '/admin/overview')!)

    const projectName = `E2E 立项项目 ${Date.now()}`
    const projectCode = `P-E2E-${Date.now()}`
    await page.getByRole('button', { name: '新建项目' }).evaluate((element) => {
      ;(element as HTMLButtonElement).click()
    })

    const wizard = page.locator('.el-dialog').filter({ hasText: '项目立项向导' })
    await expect(wizard).toBeVisible()
    await wizard
      .locator('.el-form-item')
      .filter({ hasText: '项目编号' })
      .locator('input')
      .fill(projectCode)
    await wizard
      .locator('.el-form-item')
      .filter({ hasText: '项目名称' })
      .locator('input')
      .fill(projectName)
    await wizard.getByRole('button', { name: '下一步' }).click()
    await wizard
      .locator('.el-form-item')
      .filter({ hasText: '施工单位' })
      .locator('input')
      .fill('E2E 施工单位')
    await wizard.getByRole('button', { name: '下一步' }).click()
    await expect(wizard).toContainText('立项后将生成 69 个监督检验节点')
    await wizard.getByRole('button', { name: '创建项目' }).click()

    await expect(
      page.locator('.el-message').filter({ hasText: `项目已立项：${projectName}` })
    ).toBeVisible()
    const projectDrawer = page.locator('.el-drawer').filter({ hasText: '项目详情与成员授权' })
    await expect(projectDrawer).toBeVisible()
    await expect(projectDrawer).toContainText(projectCode)
    await expect(projectDrawer).toContainText(projectName)
    await expect(projectDrawer).toContainText('4 名成员')
  })

  test('admin batch authorizes project members with shared node scope', async ({ page }) => {
    await openRoute(page, routeCases.find((routeCase) => routeCase.path === '/admin/overview')!)

    const projectRow = page.getByRole('row').filter({ hasText: '华东成品油管道改造工程' })
    await projectRow.getByRole('button', { name: '详情' }).click()
    const projectDrawer = page.locator('.el-drawer').filter({ hasText: '项目详情与成员授权' })
    await expect(projectDrawer).toBeVisible()

    await projectDrawer.getByRole('button', { name: '批量授权' }).click()
    const batchDialog = page.locator('.el-dialog').filter({ hasText: '批量项目成员授权' })
    await expect(batchDialog).toBeVisible()
    await batchDialog
      .locator('.el-form-item')
      .filter({ hasText: '节点范围' })
      .locator('input')
      .fill('2,3,4')
    await batchDialog.getByRole('button', { name: '保存' }).click()

    await expect(page.locator('.el-message').filter({ hasText: '批量授权完成：' })).toBeVisible()
    await expect(projectDrawer).toContainText('2, 3, 4')
  })

  test('admin updates permission matrix project scope and receives config diff', async ({
    page
  }) => {
    await openRoute(page, routeCases.find((routeCase) => routeCase.path === '/admin/overview')!)

    await page.getByRole('tab', { name: '权限与节点' }).click()
    const permissionPanel = page.locator('.panel').filter({ hasText: '角色权限矩阵' })
    await permissionPanel.getByRole('button', { name: '编辑' }).first().click()

    const drawer = page.locator('.el-drawer').filter({ hasText: '编辑角色权限矩阵' })
    await expect(drawer).toBeVisible()
    const projectScope = `E2E 项目范围 ${Date.now()}`
    await drawer
      .locator('.el-form-item')
      .filter({ hasText: '项目范围' })
      .locator('input')
      .fill(projectScope)
    await drawer
      .locator('.el-form-item')
      .filter({ hasText: '变更原因' })
      .locator('textarea')
      .fill('E2E 更新角色权限矩阵项目范围。')
    await drawer.getByRole('button', { name: '保存配置' }).click()

    await expect(
      page.locator('.el-message').filter({ hasText: '角色权限矩阵已保存' })
    ).toBeVisible()
    const diffDialog = page.locator('.el-dialog').filter({ hasText: '配置差异' })
    await expect(diffDialog).toBeVisible()
    await expect(diffDialog).toContainText(projectScope)
  })

  test('admin updates workflow state machine version and receives config diff', async ({
    page
  }) => {
    await openRoute(page, routeCases.find((routeCase) => routeCase.path === '/admin/overview')!)

    await page.getByRole('tab', { name: '规则与流程' }).click()
    const workflowPanel = page.locator('.panel').filter({ hasText: '流程状态机' })
    await workflowPanel.getByRole('button', { name: '编辑' }).first().click()

    const drawer = page.locator('.el-drawer').filter({ hasText: '编辑流程状态机' })
    await expect(drawer).toBeVisible()
    const workflowVersion = `workflow-e2e-${Date.now()}`
    await drawer
      .locator('.el-form-item')
      .filter({ hasText: '版本' })
      .locator('input')
      .fill(workflowVersion)
    await drawer
      .locator('.el-form-item')
      .filter({ hasText: '变更原因' })
      .locator('textarea')
      .fill('E2E 更新流程状态机版本。')
    await drawer.getByRole('button', { name: '保存配置' }).click()

    await expect(page.locator('.el-message').filter({ hasText: '流程状态机已保存' })).toBeVisible()
    const diffDialog = page.locator('.el-dialog').filter({ hasText: '配置差异' })
    await expect(diffDialog).toBeVisible()
    await expect(diffDialog).toContainText(workflowVersion)
  })

  test('admin creates message template and receives config diff', async ({ page }) => {
    await openRoute(page, routeCases.find((routeCase) => routeCase.path === '/admin/overview')!)

    await page.getByRole('tab', { name: '细项配置' }).click()
    const messagePanel = page.locator('.panel').filter({ hasText: '消息模板' })
    await messagePanel.getByRole('button', { name: '新增' }).click()

    const drawer = page.locator('.el-drawer').filter({ hasText: '新增消息模板' })
    await expect(drawer).toBeVisible()
    const scene = `e2e-message-${Date.now()}`
    const title = `E2E 消息模板 ${Date.now()}`
    await drawer.locator('.el-form-item').filter({ hasText: '场景' }).locator('input').fill(scene)
    await drawer
      .locator('.el-form-item')
      .filter({ hasText: '标题模板' })
      .locator('input')
      .fill(title)
    await drawer
      .locator('.el-form-item')
      .filter({ hasText: '内容模板' })
      .locator('textarea')
      .fill('{{projectName}} 的 E2E 配置消息已生成。')
    await drawer
      .locator('.el-form-item')
      .filter({ hasText: '变更原因' })
      .locator('textarea')
      .fill('E2E 新增消息模板。')
    await drawer.getByRole('button', { name: '新增配置' }).click()

    await expect(page.locator('.el-message').filter({ hasText: '消息模板已新增' })).toBeVisible()
    const diffDialog = page.locator('.el-dialog').filter({ hasText: '配置差异' })
    await expect(diffDialog).toBeVisible()
    await expect(diffDialog).toContainText(scene)
    await expect(diffDialog).toContainText(title)
  })

  test('admin updates tool source endpoint and receives config diff', async ({ page }) => {
    await openRoute(page, routeCases.find((routeCase) => routeCase.path === '/admin/overview')!)

    await page.getByRole('tab', { name: '细项配置' }).click()
    const toolPanel = page.locator('.panel').filter({ hasText: '工具源' })
    await toolPanel.getByRole('button', { name: '编辑' }).first().click()

    const drawer = page.locator('.el-drawer').filter({ hasText: '编辑工具源' })
    await expect(drawer).toBeVisible()
    const endpoint = `https://tools.example.com/e2e/${Date.now()}`
    await drawer
      .locator('.el-form-item')
      .filter({ hasText: '接口地址' })
      .locator('input')
      .fill(endpoint)
    await drawer
      .locator('.el-form-item')
      .filter({ hasText: '变更原因' })
      .locator('textarea')
      .fill('E2E 更新工具源接口地址。')
    await drawer.getByRole('button', { name: '保存配置' }).click()

    await expect(page.locator('.el-message').filter({ hasText: '工具源已保存' })).toBeVisible()
    const diffDialog = page.locator('.el-dialog').filter({ hasText: '配置差异' })
    await expect(diffDialog).toBeVisible()
    await expect(diffDialog).toContainText(endpoint)
  })

  test('admin updates field mapping threshold and receives config diff', async ({ page }) => {
    await openRoute(page, routeCases.find((routeCase) => routeCase.path === '/admin/overview')!)

    await page.getByRole('tab', { name: '细项配置' }).click()
    const mappingPanel = page.locator('.panel').filter({ hasText: '字段映射' })
    await mappingPanel.getByRole('button', { name: '编辑' }).first().click()

    const drawer = page.locator('.el-drawer').filter({ hasText: '编辑字段映射' })
    await expect(drawer).toBeVisible()
    await drawer
      .locator('.el-form-item')
      .filter({ hasText: '置信阈值' })
      .locator('input')
      .fill('0.92')
    await drawer
      .locator('.el-form-item')
      .filter({ hasText: '变更原因' })
      .locator('textarea')
      .fill('E2E 调整字段映射置信阈值。')
    await drawer.getByRole('button', { name: '保存配置' }).click()

    await expect(page.locator('.el-message').filter({ hasText: '字段映射已保存' })).toBeVisible()
    const diffDialog = page.locator('.el-dialog').filter({ hasText: '配置差异' })
    await expect(diffDialog).toBeVisible()
    await expect(diffDialog).toContainText('0.92')
  })

  test('admin reviews integration contract field diffs by status', async ({ page }) => {
    await openRoute(page, routeCases.find((routeCase) => routeCase.path === '/admin/overview')!)

    await page.getByRole('tab', { name: '联调清单' }).click()
    const panel = page.locator('.integration-panel')
    await expect(panel).toContainText('真实联调字段差异清单')
    await expect(panel).toContainText('字段总数')
    await expect(panel).toContainText('工作台首屏')
    await expect(panel.locator('.integration-contract-table')).toContainText('riskLevel')

    await panel.locator('.integration-filter-bar .el-select').nth(1).click()
    await page
      .locator('.el-select-dropdown:visible .el-select-dropdown__item')
      .filter({ hasText: '后端缺失' })
      .click()

    await expect(panel.locator('.integration-contract-table')).toContainText(
      '当前筛选下没有字段差异'
    )
    await expect(panel).toContainText('阻塞项')
    await expect(panel).toContainText('可推进')

    await page.setViewportSize({ width: 390, height: 900 })
    await expectNoPageOverflow(page)
  })

  test('knowledge task retry and cancel update task table', async ({ page }) => {
    await openRoute(page, routeCases.find((routeCase) => routeCase.path === '/knowledge/overview')!)

    await page.getByRole('tab', { name: '任务中心' }).click()
    const retryableTaskRow = page
      .getByRole('row')
      .filter({ has: page.getByRole('button', { name: '重试' }) })
      .first()
    await expect(retryableTaskRow).toBeVisible()
    const retryTaskId = (await retryableTaskRow.locator('td').first().innerText()).trim()
    const retryTaskRow = page.getByRole('row').filter({ hasText: retryTaskId })

    await retryTaskRow.getByRole('button', { name: '重试' }).click()

    await expect(page.locator('.el-message').filter({ hasText: '已重新排队' })).toBeVisible()
    await expect(retryTaskRow).toContainText(/排队中|成功/)

    const cancellableTaskRow = page
      .getByRole('row')
      .filter({ has: page.getByRole('button', { name: '取消' }) })
      .first()
    await expect(cancellableTaskRow).toContainText('排队中')
    const taskId = (await cancellableTaskRow.locator('td').first().innerText()).trim()
    const taskRow = page.getByRole('row').filter({ hasText: taskId })

    await taskRow.getByRole('button', { name: '取消' }).click()

    await expect(taskRow).toContainText('已取消')
  })

  test('knowledge config save writes audit state', async ({ page }) => {
    await openRoute(page, routeCases.find((routeCase) => routeCase.path === '/knowledge/overview')!)

    await page.getByRole('tab', { name: '配置审计' }).click()
    const configPanel = page.locator('.panel').filter({ hasText: '知识库配置' })
    const embeddingInput = configPanel
      .locator('.el-form-item')
      .filter({ hasText: 'Embedding 模型' })
      .locator('input')
    await embeddingInput.fill('text-embedding-3-small')
    await configPanel.getByRole('button', { name: '保存配置' }).click()

    await expect(page.locator('.el-message').filter({ hasText: '知识库配置已保存' })).toBeVisible()
    await expect(embeddingInput).toHaveValue('text-embedding-3-small')
  })

  test('knowledge multi-model compare renders fresh result', async ({ page }) => {
    await openRoute(page, routeCases.find((routeCase) => routeCase.path === '/knowledge/overview')!)

    await page.getByRole('tab', { name: '多模型对比' }).click()
    const question = `E2E 多模型对比 ${Date.now()}`
    const comparePanel = page.locator('.panel').filter({ hasText: '对比输入' })
    await comparePanel.locator('textarea').fill(question)
    await comparePanel.getByRole('button', { name: '开始对比' }).click()

    await expect(page.locator('.compare-result')).toContainText('LLM-A')
    await expect(page.locator('.compare-result')).toContainText('LLM-B')
    await expect(page.locator('.compare-history')).toContainText(question)
  })

  test('inspection exports report and opens export task detail', async ({ page }) => {
    await openRoute(
      page,
      routeCases.find((routeCase) => routeCase.path === '/workbench/inspection')!
    )
    await selectProject(page, '华东成品油管道改造工程')

    await page.locator('.report-panel button:has-text("导出"):not(.is-disabled)').first().click()

    await expect(
      page.locator('.el-message').filter({ hasText: '报告导出任务已创建' })
    ).toBeVisible()
    const exportDrawer = page.locator('.export-task-drawer')
    await expect(exportDrawer).toBeVisible()
    await expect(exportDrawer).toContainText('导出类型')
    await expect(exportDrawer).toContainText('报告导出')
    await expect(exportDrawer).toContainText('.pdf')
  })

  test('inspection report detail drawer retries after load failure', async ({ page }) => {
    let detailAttempts = 0
    await page.route('**/api/projects/*/reports/*', async (route) => {
      const request = route.request()
      if (
        request.method() === 'GET' &&
        /\/api\/projects\/[^/]+\/reports\/[^/?]+(?:\?.*)?$/.test(new URL(request.url()).pathname)
      ) {
        detailAttempts += 1
        if (detailAttempts === 1) {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(businessError(40450, '报告不存在或已被移除。', 'REPORT_NOT_FOUND'))
          })
          return
        }
      }
      await route.fallback()
    })

    await openRoute(
      page,
      routeCases.find((routeCase) => routeCase.path === '/workbench/inspection')!
    )
    await selectProject(page, '华东成品油管道改造工程')

    const panel = page.locator('.report-panel')
    await panel.locator('.el-table').first().getByRole('button', { name: '详情' }).first().click()

    const drawer = page.locator('.report-detail-drawer')
    const issue = drawer.locator('.report-detail-error').filter({ hasText: 'REPORT_NOT_FOUND' })
    await expect(issue).toBeVisible()
    await expect(issue).toContainText('报告不存在')

    await page.setViewportSize({ width: 390, height: 900 })
    await expectNoPageOverflow(page)

    await issue.getByRole('button', { name: '重新加载报告详情' }).click()

    await expect(issue).toBeHidden()
    await expect(drawer).toContainText('报告编号')
    await expect(drawer).toContainText('报告章节')
    expect(detailAttempts).toBeGreaterThanOrEqual(2)
  })

  test('inspection archive detail drawer retries after load failure', async ({ page }) => {
    let archiveAttempts = 0
    await page.route('**/api/projects/*/archive/*', async (route) => {
      const request = route.request()
      if (
        request.method() === 'GET' &&
        /\/api\/projects\/[^/]+\/archive\/[^/?]+(?:\?.*)?$/.test(new URL(request.url()).pathname)
      ) {
        archiveAttempts += 1
        if (archiveAttempts === 1) {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(
              businessError(40460, '归档资料不存在或已被移除。', 'ARCHIVE_NOT_FOUND')
            )
          })
          return
        }
      }
      await route.fallback()
    })

    await openRoute(
      page,
      routeCases.find((routeCase) => routeCase.path === '/workbench/inspection')!
    )
    await selectProject(page, '华东成品油管道改造工程')

    const panel = page.locator('.report-panel')
    await panel.locator('.el-table').nth(1).getByRole('button', { name: '详情' }).first().click()

    const drawer = page.locator('.archive-detail-drawer')
    const issue = drawer.locator('.archive-detail-error').filter({ hasText: 'ARCHIVE_NOT_FOUND' })
    await expect(issue).toBeVisible()
    await expect(issue).toContainText('归档资料不存在')

    await page.setViewportSize({ width: 390, height: 900 })
    await expectNoPageOverflow(page)

    await issue.getByRole('button', { name: '重新加载归档详情' }).click()

    await expect(issue).toBeHidden()
    await expect(drawer).toContainText('证据引用')
    await expect(drawer).toContainText('导出任务')
    expect(archiveAttempts).toBeGreaterThanOrEqual(2)
  })

  test('inspection export task drawer retries after load failure', async ({ page }) => {
    let taskAttempts = 0
    await page.route('**/api/projects/*/export-tasks/*', async (route) => {
      if (route.request().method() === 'GET') {
        taskAttempts += 1
        if (taskAttempts === 1) {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(
              businessError(40461, '导出任务不存在或已过期。', 'EXPORT_TASK_NOT_FOUND')
            )
          })
          return
        }
      }
      await route.fallback()
    })

    await openRoute(
      page,
      routeCases.find((routeCase) => routeCase.path === '/workbench/inspection')!
    )
    await selectProject(page, '华东成品油管道改造工程')

    await page.locator('.report-panel button:has-text("导出"):not(.is-disabled)').first().click()

    const drawer = page.locator('.export-task-drawer')
    const issue = drawer.locator('.export-task-error').filter({ hasText: 'EXPORT_TASK_NOT_FOUND' })
    await expect(issue).toBeVisible()
    await expect(issue).toContainText('导出任务不存在')

    await page.setViewportSize({ width: 390, height: 900 })
    await expectNoPageOverflow(page)

    await issue.getByRole('button', { name: '重新加载导出任务' }).click()

    await expect(issue).toBeHidden()
    await expect(drawer).toContainText('导出类型')
    await expect(drawer).toContainText('.pdf')
    expect(taskAttempts).toBeGreaterThanOrEqual(2)
  })

  test('inspection generates report draft and adds review version', async ({ page }) => {
    await openRoute(
      page,
      routeCases.find((routeCase) => routeCase.path === '/workbench/inspection')!
    )
    await selectProject(page, '华东成品油管道改造工程')

    const panel = page.locator('.report-panel')
    await panel.getByRole('button', { name: '生成报告草稿' }).click()

    await expect(
      page.locator('.el-message').filter({ hasText: '报告草稿已生成，进入复核' })
    ).toBeVisible()
    await expect(panel).toContainText('V1')
    await expect(panel).toContainText('复核中')
  })

  test('inspection archives report and project switches to readonly', async ({ page }) => {
    await openRoute(
      page,
      routeCases.find((routeCase) => routeCase.path === '/workbench/inspection')!
    )
    await selectProject(page, '华东成品油管道改造工程')

    await page.locator('.report-panel button:has-text("归档"):not(.is-disabled)').first().click()
    await page
      .locator('.el-popconfirm')
      .getByRole('button', { name: /确认|确定|是|Yes|OK/i })
      .click()

    await expect(page.locator('.el-message').filter({ hasText: '报告已归档' })).toBeVisible()
    await expect(page.getByText('项目已归档，只读查看')).toBeVisible()
  })
})
