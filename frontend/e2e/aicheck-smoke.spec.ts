import { expect, test, type Locator, type Page } from '@playwright/test'

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
  { path: '/admin/overview', title: '项目管理', titleLocator: '.admin-page .page-title' },
  { path: '/fde/projects', title: '项目审计工作台', titleLocator: '.fde-console .page-title' },
  {
    path: '/knowledge/overview',
    title: 'AI 知识库管理',
    titleLocator: '.knowledge-page .page-title'
  }
]

const adminDeepRouteCases = [
  { path: '/admin/projects', menu: '项目管理', tab: '项目管理' },
  { path: '/admin/org', menu: '组织用户', tab: '组织用户' },
  { path: '/admin/permission', menu: '权限与节点', tab: '权限与节点' },
  { path: '/admin/rules', menu: 'AI业务规则与流程', tab: 'AI业务规则与流程' },
  { path: '/admin/prompt-templates', menu: 'Prompt 模板管理', tab: 'Prompt 模板管理' },
  { path: '/admin/fine-config', menu: '细项配置', tab: '细项配置' },
  { path: '/admin/integration', menu: '联调清单', tab: '联调清单' },
  { path: '/admin/audit', menu: '审计日志', tab: '审计日志' }
]

const knowledgeDeepRouteCases = [
  { path: '/knowledge/sources', menu: '标准规范库', tab: '标准规范库' },
  { path: '/knowledge/files', menu: '项目文件知识库', tab: '项目文件知识库' },
  { path: '/knowledge/tasks', menu: 'OCR/向量任务中心', tab: '任务中心' },
  { path: '/knowledge/rules', menu: '监检业务判断规则管理', tab: '规则配置' },
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
    menu: '章节溯源',
    hint: '章节节点',
    context: '项目审计工作台',
    title: '项目审计工作台',
    content: '检索溯源'
  },
  {
    path: '/fde/projects?view=langgraph',
    menu: 'LangGraph 可视化',
    hint: 'ReviewRun',
    context: '项目审计工作台',
    title: '项目审计工作台',
    content: 'COG 思考摘要'
  },
  {
    path: '/fde/projects?view=ocr-labeling',
    menu: 'OCR 打标',
    hint: '样本',
    context: '项目审计工作台',
    title: '项目审计工作台',
    content: '标准答案覆盖'
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

const fdeViewForPath = (path: string) => new URLSearchParams(path.split('?')[1] || '').get('view')

const waitForFdePath = async (page: Page, path: string) => {
  const view = fdeViewForPath(path)
  await page.waitForURL((url) => {
    if (!url.hash.includes('/fde/projects')) return false
    if (!view) return true
    return new URLSearchParams(url.hash.split('?')[1] || '').get('view') === view
  })
}

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
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      await page.waitForLoadState('domcontentloaded')
      await page.evaluate(() => {
        localStorage.clear()
        sessionStorage.clear()
      })
      await page.reload({ waitUntil: 'domcontentloaded' })
      await page.waitForLoadState('networkidle').catch(() => {})
      return
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      if (!message.includes('Execution context was destroyed') || attempt === 2) throw error
      await page.waitForLoadState('domcontentloaded').catch(() => {})
    }
  }
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

const visibleOverlay = (page: Page, text: string) =>
  page.locator('.el-overlay:visible').filter({ hasText: text }).last()

const chooseFirstSelectOption = async (page: Page, select: Locator) => {
  await select.click()
  const dropdown = page.locator('.el-select-dropdown:visible').last()
  const option = dropdown.locator('.el-select-dropdown__item:not(.is-disabled)').first()
  await expect(option).toBeVisible()
  await option.click()
  await expect(dropdown).toBeHidden()
}

const submitAdminPublishPreview = async (page: Page, reason: string) => {
  await page.getByRole('button', { name: '发布配置' }).click()
  const reasonDialog = visibleOverlay(page, '发布配置')
  await expect(reasonDialog).toBeVisible()
  await reasonDialog.locator('input').fill(reason)
  await reasonDialog.getByRole('button', { name: '生成影响预览' }).click()
  const impactDialog = visibleOverlay(page, '确认发布影响')
  await expect(impactDialog).toBeVisible()
  await impactDialog.getByRole('button', { name: '确认发布' }).click()
}

const expectNoPageOverflow = async (page: Page) => {
  await expect
    .poll(
      () =>
        page.evaluate(() => {
          const documentWidth = document.documentElement.scrollWidth
          const bodyWidth = document.body.scrollWidth
          const viewportWidth = document.documentElement.clientWidth
          const contentWidth = Math.max(documentWidth, bodyWidth)
          if (contentWidth <= viewportWidth + 1) return ''
          const offenders = Array.from(document.querySelectorAll<HTMLElement>('body *'))
            .map((element) => ({
              name: element.className || element.tagName,
              right: Math.round(element.getBoundingClientRect().right),
              width: Math.round(element.getBoundingClientRect().width)
            }))
            .filter((item) => item.right > viewportWidth + 1)
            .sort((left, right) => right.right - left.right)
            .slice(0, 3)
          return JSON.stringify({ viewportWidth, documentWidth, bodyWidth, offenders })
        }),
      { timeout: 1500 }
    )
    .toBe('')
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

const expectFixedChartTransformZoom = async (
  page: Page,
  shell: Locator,
  options: {
    zoomButtonName: string
    resetButtonName: string
    echartSelector: string
  }
) => {
  const content = shell.locator('.chart-zoom-content').first()
  await expect(shell.locator('canvas').first()).toBeVisible()

  const shellWidthBefore = await shell.evaluate((el) => (el as HTMLElement).offsetWidth)
  const shellHeightBefore = await shell.evaluate((el) => (el as HTMLElement).offsetHeight)
  const frameWidthBefore = await shell
    .locator('.chart-zoom-frame')
    .first()
    .evaluate((el) => (el as HTMLElement).offsetWidth)
  const frameHeightBefore = await shell
    .locator('.chart-zoom-frame')
    .first()
    .evaluate((el) => (el as HTMLElement).offsetHeight)
  const chartWidthBefore = await shell
    .locator(options.echartSelector)
    .first()
    .evaluate((el) => (el as HTMLElement).offsetWidth)
  const chartHeightBefore = await shell
    .locator(options.echartSelector)
    .first()
    .evaluate((el) => (el as HTMLElement).offsetHeight)
  const transformBefore = await content.evaluate(
    (el) => getComputedStyle(el as HTMLElement).transform
  )

  await page.getByRole('button', { name: options.zoomButtonName }).click()

  await expect
    .poll(async () => content.evaluate((el) => getComputedStyle(el as HTMLElement).transform))
    .not.toBe(transformBefore)
  await expect
    .poll(async () => shell.evaluate((el) => (el as HTMLElement).offsetWidth))
    .toBe(shellWidthBefore)
  await expect
    .poll(async () => shell.evaluate((el) => (el as HTMLElement).offsetHeight))
    .toBe(shellHeightBefore)
  await expect
    .poll(async () =>
      shell
        .locator('.chart-zoom-frame')
        .first()
        .evaluate((el) => (el as HTMLElement).offsetWidth)
    )
    .toBe(frameWidthBefore)
  await expect
    .poll(async () =>
      shell
        .locator('.chart-zoom-frame')
        .first()
        .evaluate((el) => (el as HTMLElement).offsetHeight)
    )
    .toBe(frameHeightBefore)
  await expect
    .poll(async () =>
      shell
        .locator(options.echartSelector)
        .first()
        .evaluate((el) => (el as HTMLElement).offsetWidth)
    )
    .toBe(chartWidthBefore)
  await expect
    .poll(async () =>
      shell
        .locator(options.echartSelector)
        .first()
        .evaluate((el) => (el as HTMLElement).offsetHeight)
    )
    .toBe(chartHeightBefore)

  await page.getByRole('button', { name: options.resetButtonName }).click()
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
            const openedNodeMenus = Array.from(
              tree.querySelectorAll<HTMLElement>('.tree-section-menu.is-opened .el-menu--inline')
            ).filter(visible)
            for (const menu of openedNodeMenus) {
              const nodes = Array.from(menu.querySelectorAll<HTMLElement>('.tree-node')).filter(
                visible
              )
              if (nodes.length > 1) {
                const rects = nodes.map((node) => node.getBoundingClientRect())
                const topRows = new Set(rects.map((rect) => Math.round(rect.top)))
                const leftValues = rects.map((rect) => Math.round(rect.left))
                const leftSpread = Math.max(...leftValues) - Math.min(...leftValues)
                if (topRows.size !== nodes.length) {
                  failures.push(`tree-node-not-single-column:${nodes.length}/${topRows.size}`)
                }
                if (leftSpread > 3) {
                  failures.push(`tree-node-left-spread:${leftSpread}`)
                }
                for (const node of nodes) {
                  const nodeRect = node.getBoundingClientRect()
                  const marker = node.querySelector<HTMLElement>('.tree-node-marker')
                  if (marker) {
                    const style = getComputedStyle(node)
                    const firstColumn = Number.parseFloat(style.gridTemplateColumns.split(' ')[0])
                    const paddingLeft = Number.parseFloat(style.paddingLeft || '0')
                    const borderLeft = Number.parseFloat(style.borderLeftWidth || '0')
                    const markerRect = marker.getBoundingClientRect()
                    const markerCenterX = markerRect.left + markerRect.width / 2
                    const expectedCenterX =
                      nodeRect.left + borderLeft + paddingLeft + firstColumn / 2
                    if (Math.abs(markerCenterX - expectedCenterX) > 2) {
                      failures.push(
                        `tree-node-marker-off-center:${Math.round(markerCenterX - expectedCenterX)}`
                      )
                    }
                  }
                }
              }
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

const openInspectionAuditItem = async (page: Page, itemLabel: string) => {
  const directory = page.getByRole('region', { name: '审计项目录' })
  await expect(directory).toBeVisible()
  const item = directory.getByRole('tab', { name: new RegExp(itemLabel) })
  await expect(item).toBeVisible()
  await item.click()
  await expect(item).toHaveAttribute('aria-selected', 'true')
}

const openInspectionNodeAuditItem = async (
  page: Page,
  itemLabel: string,
  nodeName = '焊工资格证及持证合格项目'
) => {
  const nodeLink = page.getByRole('link', { name: new RegExp(nodeName) }).first()
  await expect(nodeLink).toBeVisible()
  await nodeLink.click()
  await openInspectionAuditItem(page, itemLabel)
}

test.describe('AIcheck route smoke', () => {
  test('role accounts land on their default panel without redirect', async ({ browser }) => {
    test.setTimeout(90_000)
    const cases = [
      { account: 'inspection', path: '/workbench/inspection', title: '监检工作台' },
      { account: 'contractor', path: '/workbench/contractor', title: '施工方工作台' },
      { account: 'ndt', path: '/workbench/ndt', title: '无损检测工作台' },
      { account: 'owner', path: '/workbench/owner', title: '建设方工作台' },
      { account: 'admin', path: '/admin/overview', title: '项目与权限配置' },
      { account: 'fde', path: '/fde/projects', title: '项目审计工作台' }
    ]

    for (const routeCase of cases) {
      const context = await browser.newContext()
      const rolePage = await context.newPage()
      await loginWithoutRedirect(rolePage, routeCase.account, routeCase.path)
      await expect(rolePage.getByText(routeCase.title).first()).toBeVisible()
      await context.close()
    }
  })

  test('login business errors stay visible instead of resolving undefined data', async ({
    page
  }) => {
    await page.route('**/api/auth/login', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(businessError(401, '账号或密码错误', 'AUTH_REQUIRED'))
      })
    })

    const loginInputs = await gotoLoginPage(page)
    await loginInputs.nth(0).fill('invalid-user')
    await loginInputs.nth(1).fill('invalid-password')
    await page.getByRole('button', { name: /^登录$/ }).click()

    await expect(page.getByText(/账号或密码错误/).first()).toBeVisible()
    await expect(page.getByText(/AUTH_REQUIRED/).first()).toBeVisible()
    await expect(page.getByText(/Cannot read properties of undefined/)).toHaveCount(0)
    await expect(page).toHaveURL(/#\/login/)
  })

  test('login HTTP errors preserve the business envelope', async ({ page }) => {
    await page.route('**/api/auth/login', async (route) => {
      await route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify(businessError(401, '账号或密码错误', 'AUTH_REQUIRED'))
      })
    })

    const loginInputs = await gotoLoginPage(page)
    await loginInputs.nth(0).fill('invalid-user')
    await loginInputs.nth(1).fill('invalid-password')
    await page.getByRole('button', { name: /^登录$/ }).click()

    await expect(page.getByText(/账号或密码错误/).first()).toBeVisible()
    await expect(page.getByText(/AUTH_REQUIRED/).first()).toBeVisible()
    await expect(page.getByText(/Cannot read properties of undefined/)).toHaveCount(0)
    await expect(page).toHaveURL(/#\/login/)
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

  test('first login requires password change and keeps bearer token out of localStorage', async ({
    page
  }) => {
    test.setTimeout(90_000)
    const replacementLogin = await page.request.post('/api/auth/login', {
      data: {
        username: 'inspection',
        password: passwordForAccount('inspection')
      }
    })
    expect(replacementLogin.ok()).toBe(true)
    const replacementLoginBody = await replacementLogin.json()
    const replacementToken = String(replacementLoginBody.data?.token || '')
    expect(replacementToken).not.toBe('')
    await page.route('**/api/auth/login', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          code: 0,
          data: {
            token: 'initial-signed-token',
            user: {
              id: 'USER-FIRST-LOGIN',
              username: 'first-login',
              role: 'inspection',
              roleId: 'inspection',
              mustChangePassword: true,
              defaultPath: '/workbench/inspection'
            }
          },
          operationId: 'E2E-FIRST-LOGIN',
          serverTime: '2026-07-10 08:00:00'
        })
      })
    })
    await page.route('**/api/auth/change-password', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          code: 0,
          data: {
            token: replacementToken,
            user: {
              id: 'USER-FIRST-LOGIN',
              username: 'first-login',
              role: 'inspection',
              roleId: 'inspection',
              mustChangePassword: false,
              defaultPath: '/workbench/inspection'
            },
            defaultPath: '/workbench/inspection'
          },
          operationId: 'E2E-PASSWORD-CHANGED',
          serverTime: '2026-07-10 08:01:00'
        })
      })
    })

    await page.goto('/#/login')
    await clearLoginState(page)
    const loginInputs = page.locator('.auth-form .el-input__inner')
    await expect(loginInputs.first()).toBeVisible()
    await loginInputs.nth(0).fill('first-login')
    await loginInputs.nth(1).fill('Initial!Password2026')
    await page.getByRole('button', { name: /^登录$/ }).click()
    await page.waitForURL((url) => url.hash.includes('/change-password'))

    const storage = await page.evaluate(() => ({
      local: localStorage.getItem('user'),
      session: sessionStorage.getItem('user')
    }))
    expect(storage.local || '').not.toContain('initial-signed-token')
    expect(storage.session || '').toContain('initial-signed-token')

    await page.getByLabel('当前密码').fill('Initial!Password2026')
    await page.getByLabel('新密码', { exact: true }).fill('Replacement!Safe2026')
    await page.getByLabel('确认新密码').fill('Replacement!Safe2026')
    await page.getByRole('button', { name: '保存并进入系统' }).click()
    await page.waitForURL((url) => url.hash.includes('/workbench/inspection'))
    await expect(page.getByText('监检工作台').first()).toBeVisible()
    await expect
      .poll(() => page.evaluate(() => sessionStorage.getItem('user') || ''))
      .toContain(replacementToken)
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

  test('inspection node navigation remains usable at responsive breakpoints', async ({ page }) => {
    await openRoute(
      page,
      routeCases.find((routeCase) => routeCase.path === '/workbench/inspection')!
    )

    for (const viewport of [
      { width: 390, height: 900 },
      { width: 768, height: 1024 }
    ]) {
      await page.setViewportSize(viewport)
      const nodeNavigation = page.locator('#audit-node-navigation')
      const trigger = page.getByRole('button', { name: '审核节点', exact: true })
      await expect(trigger).toBeVisible()
      await expect(trigger).toHaveAttribute('aria-expanded', 'false')
      await expect(nodeNavigation).toBeHidden()

      await trigger.click()
      await expect(nodeNavigation).toBeVisible()
      await expect(trigger).toHaveAttribute('aria-expanded', 'true')

      const nodeButtons = nodeNavigation.locator('.node-button')
      if ((await nodeButtons.count()) === 0) {
        await nodeNavigation.getByRole('treeitem', { name: '焊接（粘接）', exact: true }).click()
      }
      await expect(nodeButtons.first()).toBeVisible()
      await nodeButtons.first().click()
      await expect(nodeNavigation).toBeHidden()
      const auditDirectory = page.getByRole('region', { name: '审计项目录' })
      await expect(auditDirectory).toBeVisible()
      await expect(auditDirectory.locator('.el-steps')).toHaveClass(/el-steps--horizontal/)
      await expect(auditDirectory.getByRole('tab')).toHaveCount(7)
      await expect(page.locator('.audit-item-directory__summary')).toBeVisible()
      await expectNoPageOverflow(page)
    }

    await page.setViewportSize({ width: 1440, height: 1000 })
    await expect(page.getByRole('button', { name: '审核节点', exact: true })).toBeHidden()
    await expect(page.locator('#audit-node-navigation')).toBeVisible()
    const desktopAuditDirectory = page.getByRole('region', { name: '审计项目录' })
    await expect(desktopAuditDirectory.locator('.el-steps')).toHaveClass(/el-steps--horizontal/)
    await expect(desktopAuditDirectory.getByRole('tab')).toHaveCount(7)
    const selectedItem = desktopAuditDirectory.locator('.audit-item-directory__item.is-selected')
    await expect(selectedItem).toHaveCount(1)
    await expect(selectedItem).toHaveAttribute('aria-selected', 'true')
    await expect(page.locator('.audit-item-directory__legend')).toContainText('当前查看')

    const center = page.locator('.center')
    await center.evaluate((element) => {
      element.scrollTop = 700
    })
    const stickyTopInset = await center.evaluate((element) => {
      return Math.round(Number.parseFloat(getComputedStyle(element).paddingTop))
    })
    await expect
      .poll(async () => {
        const [directoryBox, centerBox] = await Promise.all([
          desktopAuditDirectory.boundingBox(),
          center.boundingBox()
        ])
        if (!directoryBox || !centerBox) return -1
        return Math.round(directoryBox.y - centerBox.y)
      })
      .toBe(stickyTopInset)
    await expectNoPageOverflow(page)
  })

  test('inspection audit directory supports keyboard selection and restorable deep links', async ({
    page
  }) => {
    await page.emulateMedia({ reducedMotion: 'no-preference' })
    await openRoute(
      page,
      routeCases.find((routeCase) => routeCase.path === '/workbench/inspection')!
    )
    await openInspectionNodeAuditItem(page, '证据确认')

    const directory = page.getByRole('region', { name: '审计项目录' })
    const evidenceItem = directory.getByRole('tab', { name: /证据确认/ })
    await expect(evidenceItem).toHaveAttribute('aria-selected', 'true')
    await expect(page).toHaveURL(/auditItem=evidence/)

    await evidenceItem.press('ArrowRight')
    const aiReviewItem = directory.getByRole('tab', { name: /AI 复核/ })
    await expect(aiReviewItem).toHaveAttribute('aria-selected', 'true')
    await expect(page).toHaveURL(/auditItem=ai_review/)
    await expect(page.locator('#inspection-audit-panel-ai_review')).toBeVisible()
    await expect
      .poll(() =>
        aiReviewItem.locator('.audit-stage-index').evaluate((element) => {
          return getComputedStyle(element, '::after').animationName
        })
      )
      .toMatch(/^audit-item-ripple/)

    await page.reload()
    const restoredDirectory = page.getByRole('region', { name: '审计项目录' })
    await expect(restoredDirectory.getByRole('tab', { name: /AI 复核/ })).toHaveAttribute(
      'aria-selected',
      'true'
    )
    await expect(page.locator('#inspection-audit-panel-ai_review')).toBeVisible()
  })

  test('inspection renders responsible role codes as Chinese labels', async ({ page }) => {
    await openRoute(
      page,
      routeCases.find((routeCase) => routeCase.path === '/workbench/inspection')!
    )
    await openInspectionNodeAuditItem(page, '资料提交')

    const requirements = page.locator('#inspection-node-requirements')
    await expect(requirements).toContainText('施工方')
    await expect(requirements.getByText('contractor', { exact: true })).toHaveCount(0)
  })

  test('inspection progress sends missing materials to review instead of upload', async ({
    page
  }) => {
    await openRoute(
      page,
      routeCases.find((routeCase) => routeCase.path === '/workbench/inspection')!
    )
    await page.getByRole('link', { name: '设计单位许可资质', exact: true }).first().click()

    const auditDirectory = page.getByRole('region', { name: '审计项目录' })
    const submissionItem = auditDirectory.getByRole('tab', { name: /资料提交/ })
    await expect(submissionItem).toHaveClass(/is-needs_attention/)
    await expect(auditDirectory.getByRole('button', { name: '上传资料' })).toHaveCount(0)
    await openInspectionAuditItem(page, 'OCR 抽取')
    await expect(page.locator('#inspection-audit-panel-ocr')).toBeVisible()
    await openInspectionAuditItem(page, '资料提交')
    await expect(page.locator('#inspection-node-requirements')).toBeVisible()
  })

  test('inspection standard references use a virtual tree and open the original file', async ({
    page
  }) => {
    await openRoute(
      page,
      routeCases.find((routeCase) => routeCase.path === '/workbench/inspection')!
    )
    await page.getByRole('treeitem', { name: '施工组织设计', exact: true }).click()
    await page
      .locator('#audit-node-navigation .node-button')
      .filter({ hasText: '11施工组织设计' })
      .first()
      .click()
    await openInspectionAuditItem(page, '证据确认')

    const standardTree = page.locator('.standard-reference-tree')
    await expect(standardTree).toBeVisible()
    await expect(standardTree.locator('.el-vl__wrapper')).toBeVisible()
    await expect(standardTree).toContainText('引用标准文件（29）')
    await expect(standardTree).toContainText('NB/T 47013 承压设备无损检测')

    const previewableFile = standardTree.locator('.standard-tree-node.is-file').first()
    await expect(previewableFile).toContainText('预览')
    await previewableFile.click()

    const previewDrawer = page.locator('.aicheck-preview-drawer:visible')
    await expect(previewDrawer).toContainText('规范原文预览')
    await expect(previewDrawer.locator('iframe')).toHaveAttribute('src', /^blob:/)
    await expect(previewDrawer).not.toContainText('原文预览加载失败')
  })
})

test.describe('AIcheck deep route menu', () => {
  test('admin subroutes select one static menu without duplicate tabs', async ({ page }) => {
    await loginTo(page, adminDeepRouteCases[0].path)

    for (const routeCase of adminDeepRouteCases) {
      await page.goto(`/#${routeCase.path}`)
      await page.waitForURL((url) => url.hash.includes(routeCase.path))
      await page.waitForLoadState('networkidle')
      await expect(page.locator('.admin-page .page-title')).toContainText(routeCase.tab)
      await expect(page.locator('.static-tree-menu .tree-node.active').first()).toContainText(
        routeCase.menu
      )
      await expect(page.locator('.admin-tabs > .el-tabs__header')).toBeHidden()
      await expectNoPageOverflow(page)
    }
  })

  test('knowledge subroutes select one static menu without duplicate tabs', async ({ page }) => {
    await loginTo(page, knowledgeDeepRouteCases[0].path)

    for (const routeCase of knowledgeDeepRouteCases) {
      await page.goto(`/#${routeCase.path}`)
      await page.waitForURL((url) => url.hash.includes(routeCase.path))
      await page.waitForLoadState('networkidle')
      await expect(page.locator('.knowledge-page .page-title')).toContainText('AI 知识库管理')
      await expect(page.locator('.static-tree-menu .tree-node.active').first()).toContainText(
        routeCase.menu
      )
      await expect(page.locator('.knowledge-tabs > .el-tabs__header')).toBeHidden()
      await expectNoPageOverflow(page)
    }
  })

  test('fde subroutes select static menu and route context', async ({ page }) => {
    await loginTo(page, '/fde/projects')
    await waitForFdeProjectAuditReady(page)
    await expect(page.locator('.fde-console')).toContainText('项目审计工作台')

    for (const routeCase of fdeDeepRouteCases) {
      await page.goto(`/#${routeCase.path}`)
      await waitForFdePath(page, routeCase.path)
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
        await waitForFdePath(page, path)
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

  test('fde project workspace shows a truthful empty state without synthetic evidence', async ({
    page
  }) => {
    await loginTo(page, '/fde/projects')
    await page.goto('/#/fde/projects?projectId=P-2026-GDLNG-002&view=vectorization')
    await page.waitForLoadState('networkidle')
    await waitForFdeProjectAuditReady(page)

    await expectFdeProjectTreeUsable(page)
    await expect(page.locator('.fde-console')).toContainText('资料解析')
    await expect(page.locator('.fde-console')).toContainText('知识切片')
    await expect(page.locator('.fde-console')).toContainText('向量入库')
    await expect(page.locator('.fde-console')).toContainText('资料知识资产溯源')
    await expect(page.locator('.fde-console')).toContainText('每份资料为什么能进入 Agent 审查')
    await expect(page.locator('.fde-console')).toContainText('0 个资料版本')
    await expect(page.locator('.fde-console')).toContainText('暂无数据')
    await expect(page.locator('.fde-console')).toContainText('Lineage 来源')
    await expect(page.locator('.fde-console')).toContainText('后端审计投影')
    await expect(page.getByTestId('fde-open-vector-file-detail')).toHaveCount(0)
    await expect(page.getByTestId('fde-open-review-detail')).toHaveCount(0)
    await expect(page.getByTestId('fde-open-ocr-detail')).toHaveCount(0)
    await expect(page.locator('.fde-console')).not.toContainText('管道特性表-第2版.png')
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

    await loginTo(page, '/admin/fine-config')
    await submitAdminPublishPreview(page, '验证配置发布冲突恢复提示')

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

    await loginTo(page, '/knowledge/retrieval')
    await page.locator('textarea:visible').first().fill('焊工资格证有效期如何校验？')
    await page.getByRole('button', { name: '运行检索' }).click()

    const issue = page.locator('.local-operation-error').filter({ hasText: '错误码：TASK_RUNNING' })
    await expect(issue).toBeVisible()
    await expect(issue).toContainText('已有任务正在运行')
    await expect(issue.getByRole('button', { name: '重试检索' })).toBeVisible()
  })

  test('workbench ai recheck maps live business error in action toast', async ({ page }) => {
    await page.route('**/api/projects/*/nodes/*/package', async (route) => {
      const response = await route.fetch()
      const body = await response.json()
      const data = body.data || {}
      const requirements = Array.isArray(data.requirements) ? data.requirements : []
      const nodeId = Number(data.node?.nodeId || 24)
      const nodeEvidenceLinks = requirements.map((requirement, index: number) => ({
        id: `E2E-CONFIRMED-${nodeId}-${index + 1}`,
        projectId: data.node?.projectId || 'P-2026-HDCP-001',
        nodeId,
        reviewPointId: requirement.id,
        fieldName: requirement.name,
        fieldValue: `已确认 ${requirement.name}`,
        quotedText: `已确认 ${requirement.name}`,
        manualStatus: 'confirmed',
        manualStatusLabel: '已确认',
        matchedEvidenceItems: [`已确认 ${requirement.name}`]
      }))
      const readiness = {
        schemaVersion: 'node-evidence-readiness-v1',
        hasReviewPoints: requirements.length > 0,
        requiredCount: requirements.length,
        satisfiedCount: requirements.length,
        missingCount: 0,
        pendingCount: 0,
        rejectedCount: 0,
        progressPercent: requirements.length ? 100 : 0,
        readyForAi: true,
        readyForAiFormal: true,
        readyForGapPrecheck: true,
        evidenceReviewComplete: true,
        blockingReasons: [],
        requirements: requirements.map((requirement, index: number) => ({
          ...requirement,
          fulfilled: true,
          matchedBindingCount: 1,
          confirmedLinkCount: 1,
          pendingLinkCount: 0,
          rejectedLinkCount: 0,
          evidenceLinkIds: [nodeEvidenceLinks[index]?.id],
          confirmedEvidenceLinkIds: [nodeEvidenceLinks[index]?.id]
        })),
        missingRequirements: [],
        nodeEvidenceLinks,
        supportingDocumentCount: nodeEvidenceLinks.length
      }
      await route.fulfill({
        response,
        json: {
          ...body,
          data: {
            ...data,
            evidenceReadiness: readiness,
            nodeEvidenceLinks
          }
        }
      })
    })
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
    await openInspectionNodeAuditItem(page, 'AI 复核')
    await page
      .locator('.ai-review-mode-control .el-radio-button')
      .filter({ hasText: '正式复核' })
      .click()
    await page.locator('.node-ai-recheck-button').click()

    const blocker = page.locator('.ai-recheck-output-error')
    await expect(blocker).toBeVisible()
    await expect(blocker).toContainText('错误码：TASK_RUNNING')
    await expect(blocker).toContainText('已有任务正在运行')
  })
})

test.describe('AIcheck business writeback flows', () => {
  test('contractor project file library exposes upload, binding, and feedback actions', async ({
    page
  }) => {
    await openRoute(
      page,
      routeCases.find((routeCase) => routeCase.path === '/workbench/contractor')!
    )
    await selectProject(page, '华东成品油管道改造工程')

    const pageRoot = page.locator('.aicheck-page')
    await expect(pageRoot).toContainText('施工方工作台 · 项目文件库与补正反馈')
    await expect(pageRoot).toContainText('标准资料上传')
    await expect(pageRoot).toContainText('审核反馈列表')

    await page.getByRole('button', { name: '批量上传文件' }).click()
    const uploadDialog = visibleOverlay(page, '上传项目文件')
    await expect(uploadDialog).toBeVisible()
    await expect(uploadDialog).toContainText('选择或拖拽文件')
    await uploadDialog.getByRole('button', { name: '取消' }).click()

    await page.getByRole('button', { name: '关联文件' }).first().click()
    const bindDialog = visibleOverlay(page, '关联项目文件到审核环节')
    await expect(bindDialog).toBeVisible()
    await expect(bindDialog).toContainText(/项目文件库暂无可关联文件|确认关联/)
    await bindDialog.getByRole('button', { name: '取消' }).click()

    await page.getByRole('button', { name: '提交反馈' }).first().click()
    const feedbackDialog = visibleOverlay(page, '补正详情与反馈')
    await expect(feedbackDialog).toBeVisible()
    await expect(feedbackDialog).toContainText('反馈说明')
    const feedbackInput = feedbackDialog.locator('textarea')
    await feedbackInput.fill('E2E 资料库补正反馈保留输入，不绕过后端证据校验。')
    await expect(feedbackInput).toHaveValue('E2E 资料库补正反馈保留输入，不绕过后端证据校验。')
    await expect(feedbackDialog.getByRole('button', { name: '提交补正反馈' })).toBeVisible()

    await page.setViewportSize({ width: 390, height: 900 })
    await expectNoPageOverflow(page)
  })

  test('ndt material library routes uploads by document category', async ({ page }) => {
    await openRoute(page, routeCases.find((routeCase) => routeCase.path === '/workbench/ndt')!)

    const pageRoot = page.locator('.aicheck-page')
    await expect(pageRoot).toContainText('无损检测工作台 · 检测资料库与补正反馈')
    await expect(pageRoot).toContainText('标准资料上传')

    const uploadCases = [
      { button: '上传底片/影像', category: '底片与影像资料' },
      { button: '上传检测记录', category: '检测记录' },
      { button: '上传检测报告', category: '检测报告' },
      { button: '上传补正', category: '问题处理闭环' }
    ]

    for (const uploadCase of uploadCases) {
      await page.getByRole('button', { name: uploadCase.button }).first().click()
      const uploadDialog = visibleOverlay(page, '上传项目文件')
      await expect(uploadDialog).toBeVisible()
      await expect(uploadDialog).toContainText(uploadCase.category)
      await expect(uploadDialog).toContainText('选择或拖拽文件')
      await uploadDialog.getByRole('button', { name: '取消' }).click()
    }

    await page.setViewportSize({ width: 390, height: 900 })
    await expectNoPageOverflow(page)
  })

  test('ndt submit is blocked until report readiness is satisfied', async ({ page }) => {
    await openRoute(page, routeCases.find((routeCase) => routeCase.path === '/workbench/ndt')!)

    const panel = page.locator('.ndt-panel')
    const actions = panel.locator('.ndt-actions')
    await expect(actions).toContainText(/待提交报告 \d+ 份/)

    const submitButton = panel.getByRole('button', { name: '提交检测资料' })
    await expect(submitButton).toBeDisabled()
    const issue = panel.locator('.ndt-submit-error').filter({ hasText: '检测资料暂不满足提交条件' })
    if (await issue.isVisible().catch(() => false)) {
      await expect(issue).toContainText(/OCR 未完成|至少一份待提交检测报告/)
    }

    await page.setViewportSize({ width: 390, height: 900 })
    await expectNoPageOverflow(page)
  })

  test('admin creates todo rule and receives save confirmation', async ({ page }) => {
    await loginTo(page, '/admin/fine-config')
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

    await expect(page.locator('.el-message')).toContainText('待办规则已新增')
  })

  test('admin exports config package and surfaces export task card', async ({ page }) => {
    await loginTo(page, '/admin/audit')

    await page.getByRole('button', { name: '导出配置包' }).click()

    await expect(page.locator('.el-message')).toContainText(/配置包已生成：后台配置包-all-\d+\.zip/)
  })

  test('admin publishes config and reviews linked impact trace', async ({ page }) => {
    await loginTo(page, '/admin/fine-config')
    await submitAdminPublishPreview(page, 'E2E 验证配置影响预览和发布追溯')

    await expect(page.locator('.el-message').filter({ hasText: '配置已发布' })).toBeVisible()
    const configPanel = page.locator('.config-panel')
    await expect(configPanel).toContainText('最近发布：config-r')
    await expect(configPanel).toContainText('在检项目')
    await expect(configPanel).toContainText('推送')
    await expect(configPanel).toContainText('条消息')

    await configPanel.getByRole('button', { name: '查看联动' }).click()
    const traceDialog = page.locator('.el-dialog').filter({ hasText: '发布联动追溯' })
    await expect(traceDialog).toBeVisible()
    await expect(traceDialog).toContainText('工作台消息')
    await expect(traceDialog).toContainText('复核待办')
    await expect(traceDialog).toContainText('工作流状态机')
    await expect(traceDialog).toContainText('已发布')
    await page.locator('.el-notification').evaluateAll((elements) => {
      elements.forEach((element) => element.remove())
    })
    await traceDialog.locator('.el-dialog__headerbtn').click()
    await expect(traceDialog).toBeHidden()

    await page.setViewportSize({ width: 390, height: 900 })
    await expectNoPageOverflow(page)
  })

  test('admin authorizes a project member and refreshes member table', async ({ page }) => {
    await openRoute(page, routeCases.find((routeCase) => routeCase.path === '/admin/overview')!)

    const projectTable = page.locator('.panel').filter({ hasText: '项目清单' })
    const projectRow = projectTable
      .getByRole('row')
      .filter({ has: page.getByRole('button', { name: '详情' }) })
      .first()
    await projectRow.getByRole('button', { name: '详情' }).click()
    const projectDrawer = page.locator('.el-drawer').filter({ hasText: '项目详情与成员授权' })
    await expect(projectDrawer).toBeVisible()
    await expect(projectDrawer).toContainText('成员授权')

    await projectDrawer.getByRole('button', { name: '新增授权' }).click()
    const memberDialog = visibleOverlay(page, '项目成员授权')
    await expect(memberDialog).toBeVisible()
    await expect(memberDialog).toContainText('角色筛选')
    await expect(memberDialog).toContainText('用户')
    await expect(memberDialog).toContainText('到期时间')
    await expect(memberDialog.getByRole('button', { name: '保存' })).toBeVisible()
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
    await wizard.locator('.el-form-item').filter({ hasText: '区域' }).locator('input').fill('华东')
    await wizard.getByRole('button', { name: '下一步' }).click()
    for (const label of ['建设单位', '施工单位', '无损检测单位', '监检机构']) {
      const formItem = wizard.locator('.el-form-item').filter({ hasText: label })
      await chooseFirstSelectOption(page, formItem.locator('.el-select'))
    }
    await wizard.getByRole('button', { name: '下一步' }).click()
    const memberSelects = wizard.locator('.wizard-member-table .el-select')
    const memberSelectCount = await memberSelects.count()
    expect(memberSelectCount).toBe(4)
    for (let index = 0; index < memberSelectCount; index++) {
      await chooseFirstSelectOption(page, memberSelects.nth(index))
    }
    await expect(wizard).toContainText('业务类型生成节点')
    await wizard.getByRole('button', { name: '创建项目' }).click()

    const projectDrawer = page.locator('.el-drawer').filter({ hasText: '项目详情与成员授权' })
    await expect(projectDrawer).toBeVisible()
    await expect(projectDrawer).toContainText(projectCode)
    await expect(projectDrawer).toContainText(projectName)
    await expect(projectDrawer).toContainText('4 名成员')
  })

  test('admin batch authorizes project members with shared node scope', async ({ page }) => {
    await openRoute(page, routeCases.find((routeCase) => routeCase.path === '/admin/overview')!)

    const projectTable = page.locator('.panel').filter({ hasText: '项目清单' })
    const projectRow = projectTable
      .getByRole('row')
      .filter({ has: page.getByRole('button', { name: '详情' }) })
      .first()
    await projectRow.getByRole('button', { name: '详情' }).click()
    const projectDrawer = page.locator('.el-drawer').filter({ hasText: '项目详情与成员授权' })
    await expect(projectDrawer).toBeVisible()

    await projectDrawer.getByRole('button', { name: '批量授权' }).click()
    const batchDialog = visibleOverlay(page, '批量项目成员授权')
    await expect(batchDialog).toBeVisible()
    await expect(batchDialog).toContainText('角色筛选')
    await expect(batchDialog).toContainText('用户')
    await expect(batchDialog.getByRole('button', { name: '保存' })).toBeVisible()
  })

  test('admin updates permission matrix project scope and receives save confirmation', async ({
    page
  }) => {
    await loginTo(page, '/admin/permission')
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

    await expect(page.locator('.el-message')).toContainText('角色权限矩阵已保存')
  })

  test('admin updates workflow state machine version and receives save confirmation', async ({
    page
  }) => {
    await loginTo(page, '/admin/rules')
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

    await expect(page.locator('.el-message')).toContainText('流程状态机已保存')
  })

  test('admin creates message template and receives save confirmation', async ({ page }) => {
    await loginTo(page, '/admin/fine-config')
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

    await expect(page.locator('.el-message')).toContainText('消息模板已新增')
  })

  test('admin updates tool source endpoint and receives save confirmation', async ({ page }) => {
    await loginTo(page, '/admin/fine-config')
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

    await expect(page.locator('.el-message')).toContainText('工具源已保存')
  })

  test('admin updates field mapping threshold and receives save confirmation', async ({ page }) => {
    await loginTo(page, '/admin/fine-config')
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

    await expect(page.locator('.el-message')).toContainText('字段映射已保存')
  })

  test('admin reviews integration contract field diffs by status', async ({ page }) => {
    await loginTo(page, '/admin/integration')
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

  test('knowledge task cancel and retry update task table', async ({ page }) => {
    await loginTo(page, '/knowledge/tasks')
    const taskPanel = page.getByRole('tabpanel', { name: '任务中心' })
    const cancellableTaskRow = taskPanel
      .getByRole('row')
      .filter({ has: page.getByRole('button', { name: '取消' }) })
      .first()
    await expect(cancellableTaskRow).toContainText('排队中')
    const taskId = (await cancellableTaskRow.locator('td').first().innerText()).trim()
    const taskRow = taskPanel.getByRole('row').filter({ hasText: taskId })

    const cancelResponsePromise = page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' &&
        response.url().includes(`/api/knowledge/tasks/${taskId}/cancel`)
    )
    await taskRow.getByRole('button', { name: '取消' }).click()
    const cancelResponse = await cancelResponsePromise
    const cancelBody = await cancelResponse.json()
    expect(cancelBody.data?.task?.status).toBe('已取消')
    await taskPanel.locator('.filter-bar .el-select').nth(1).click()
    await page.getByRole('option', { name: '已取消', exact: true }).click()
    const cancelledTaskRow = taskPanel.getByRole('row').filter({ hasText: taskId })
    await expect(cancelledTaskRow).toContainText('已取消')

    const retryResponsePromise = page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' &&
        response.url().includes(`/api/knowledge/tasks/${taskId}/retry`)
    )
    await cancelledTaskRow.getByRole('button', { name: '重试' }).click()
    const retryResponse = await retryResponsePromise
    const retryBody = await retryResponse.json()
    const retriedStatus = String(retryBody.data?.task?.status || '')
    expect(['排队中', '成功']).toContain(retriedStatus)
    await taskPanel.locator('.filter-bar .el-select').nth(1).click()
    await page.getByRole('option', { name: retriedStatus, exact: true }).click()
    await expect(taskPanel.getByRole('row').filter({ hasText: taskId })).toContainText(
      retriedStatus
    )
  })

  test('knowledge config save writes audit state', async ({ page }) => {
    await loginTo(page, '/knowledge/config')
    const configPanel = page.locator('.panel').filter({ hasText: '知识库配置' })
    const embeddingInput = configPanel
      .locator('.el-form-item')
      .filter({ hasText: 'Embedding 模型' })
      .locator('input')
    await embeddingInput.fill('BAAI/bge-m3')
    await configPanel.getByRole('button', { name: '保存配置' }).click()

    await expect(page.locator('.el-message').filter({ hasText: '知识库配置已保存' })).toBeVisible()
    await expect(embeddingInput).toHaveValue('BAAI/bge-m3')
  })

  test('knowledge multi-model compare renders fresh result', async ({ page }) => {
    await loginTo(page, '/knowledge/compare')
    const question = `E2E 多模型对比 ${Date.now()}`
    const comparePanel = page.locator('.panel').filter({ hasText: '对比输入' })
    await comparePanel.locator('textarea').fill(question)
    await comparePanel.getByRole('button', { name: '开始对比' }).click()

    await expect(page.locator('.compare-result')).toContainText('审计复核模型')
    await expect(page.locator('.compare-result')).toContainText('快速对比模型')
    await expect(page.locator('.compare-history')).toContainText(question)
  })

  test('inspection blocks report export until review and evidence gates pass', async ({ page }) => {
    await openRoute(
      page,
      routeCases.find((routeCase) => routeCase.path === '/workbench/inspection')!
    )
    await selectProject(page, '华东成品油管道改造工程')
    await openInspectionNodeAuditItem(page, '报告复核')

    const reportPanel = page.locator('.report-panel')
    const reportExportButtons = reportPanel.getByRole('button', { name: '导出' })
    await expect(reportExportButtons.first()).toBeDisabled()
    await expect(reportPanel).toContainText('复核中')
    await expect(page.locator('.export-task-drawer')).toBeHidden()
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
    await openInspectionNodeAuditItem(page, '报告复核')

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
    await openInspectionNodeAuditItem(page, '签发归档')

    const panel = page.locator('.report-panel')
    await panel
      .locator('.archive-items-table')
      .getByRole('button', { name: '详情' })
      .first()
      .click()

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
    await openInspectionNodeAuditItem(page, '签发归档')

    await page.locator('.report-panel').getByRole('button', { name: '归档包' }).click()

    const drawer = page.locator('.export-task-drawer')
    const issue = drawer.locator('.export-task-error').filter({ hasText: 'EXPORT_TASK_NOT_FOUND' })
    await expect(issue).toBeVisible()
    await expect(issue).toContainText('导出任务不存在')

    await page.setViewportSize({ width: 390, height: 900 })
    await expectNoPageOverflow(page)

    await issue.getByRole('button', { name: '重新加载导出任务' }).click()

    await expect(issue).toBeHidden()
    await expect(drawer).toContainText('导出类型')
    await expect(drawer).toContainText('.zip')
    expect(taskAttempts).toBeGreaterThanOrEqual(2)
  })

  test('inspection blocks report draft without validated confirmed evidence', async ({ page }) => {
    await openRoute(
      page,
      routeCases.find((routeCase) => routeCase.path === '/workbench/inspection')!
    )
    await selectProject(page, '华东成品油管道改造工程')
    await openInspectionNodeAuditItem(page, '报告复核')

    const panel = page.locator('.report-panel')
    await expect(panel.getByRole('button', { name: '生成报告草稿' })).toBeDisabled()
    await expect(panel.locator('.report-gate-alert')).toContainText(
      /confirmed 证据|confirmed-only 校验|readiness 快照/
    )
  })

  test('inspection cannot archive report before review or signature gates pass', async ({
    page
  }) => {
    await openRoute(
      page,
      routeCases.find((routeCase) => routeCase.path === '/workbench/inspection')!
    )
    await selectProject(page, '华东成品油管道改造工程')
    await openInspectionNodeAuditItem(page, '签发归档')

    const archiveButton = page.locator('.report-panel button:has-text("归档")').first()
    await expect(archiveButton).toBeDisabled()
    await expect(page.locator('.report-panel')).toContainText('复核中')
  })
})
