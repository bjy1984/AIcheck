import { chromium } from '@playwright/test'

const baseUrl = process.env.AICHECK_BASE_URL || 'http://127.0.0.1:4000'
const strict = process.argv.includes('--strict')
const configuredViewports = process.env.AICHECK_UI_AUDIT_VIEWPORTS
const viewports = configuredViewports
  ? configuredViewports
      .split(',')
      .map((value) => Number.parseInt(value.trim(), 10))
      .filter(Number.isFinite)
  : [390, 768, 1024, 1440]
const allRoutes = [
  { account: 'inspection', path: '/workbench/inspection', label: '监检工作台' },
  {
    account: 'inspection',
    path: '/workbench/inspection?nodeId=24&auditItem=submission',
    label: '监检节点审计'
  },
  { account: 'contractor', path: '/workbench/contractor', label: '施工方工作台' },
  { account: 'ndt', path: '/workbench/ndt', label: '无损检测工作台' },
  { account: 'owner', path: '/workbench/owner', label: '建设方工作台' },
  { account: 'admin', path: '/admin/overview', label: '管理后台' },
  { account: 'admin', path: '/knowledge/overview', label: '知识库管理' },
  { account: 'fde', path: '/fde/standards-vectorization', label: 'FDE 规范库治理' }
]
const configuredRoutes = new Set(
  (process.env.AICHECK_UI_AUDIT_ROUTES || '')
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean)
)
const routes = configuredRoutes.size
  ? allRoutes.filter((route) => configuredRoutes.has(route.path))
  : allRoutes

const passwordFor = (account) => {
  const key = account.toUpperCase().replaceAll('-', '_')
  return (
    process.env[`AICHECK_UI_AUDIT_PASSWORD_${key}`] ||
    process.env[`AICHECK_BOOTSTRAP_PASSWORD_${key}`] ||
    account
  )
}

const login = async (page, account, path) => {
  const [routePath, routeQuery] = path.split('?')
  await page.goto(`${baseUrl}/#/login?redirect=${encodeURIComponent(routePath)}`)
  await page.getByRole('textbox', { name: '用户名' }).fill(account)
  await page.getByRole('textbox', { name: '密码' }).fill(passwordFor(account))
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL((url) => url.hash.includes(routePath), { timeout: 20_000 })
  await page.waitForLoadState('networkidle').catch(() => {})
  if (routeQuery) {
    const mobileNavigationTrigger = page.getByRole('button', { name: '审核节点', exact: true })
    const nodeNavigation = page.locator('#audit-node-navigation')
    const navigationEntry = await Promise.race([
      mobileNavigationTrigger
        .waitFor({ state: 'visible', timeout: 20_000 })
        .then(() => 'mobile-trigger'),
      nodeNavigation.waitFor({ state: 'visible', timeout: 20_000 }).then(() => 'navigation')
    ])
    if (navigationEntry === 'mobile-trigger') await mobileNavigationTrigger.click()
    await nodeNavigation.waitFor({ state: 'visible', timeout: 20_000 })
    const auditNode = nodeNavigation
      .locator('.node-button')
      .filter({ hasText: '焊工资格证及持证合格项目' })
      .first()
    if ((await auditNode.count()) === 0) {
      await nodeNavigation.getByRole('treeitem', { name: '焊接（粘接）', exact: true }).click()
    }
    await auditNode.click()
    if (navigationEntry === 'mobile-trigger') {
      await nodeNavigation.waitFor({ state: 'hidden', timeout: 20_000 })
    }
    await page.getByRole('region', { name: '审计项目录' }).waitFor({ timeout: 20_000 })
    await page
      .locator('.audit-item-directory:not(.is-loading)')
      .waitFor({ state: 'attached', timeout: 20_000 })
    return
  }
}

const inspectPage = async (page, viewport) =>
  page.evaluate((width) => {
    const visible = (element) => {
      const rect = element.getBoundingClientRect()
      const style = getComputedStyle(element)
      return (
        rect.width > 0 &&
        rect.height > 0 &&
        style.display !== 'none' &&
        style.visibility !== 'hidden' &&
        style.opacity !== '0'
      )
    }
    const rgb = (value) => {
      const match = value.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/)
      return match ? [Number(match[1]), Number(match[2]), Number(match[3])] : null
    }
    const luminance = (color) => {
      const values = color.map((value) => {
        const normalized = value / 255
        return normalized <= 0.04045
          ? normalized / 12.92
          : Math.pow((normalized + 0.055) / 1.055, 2.4)
      })
      return 0.2126 * values[0] + 0.7152 * values[1] + 0.0722 * values[2]
    }
    const contrast = (foreground, background) => {
      const first = rgb(foreground)
      const second = rgb(background)
      if (!first || !second) return null
      const firstLuminance = luminance(first)
      const secondLuminance = luminance(second)
      return Number(
        (
          (Math.max(firstLuminance, secondLuminance) + 0.05) /
          (Math.min(firstLuminance, secondLuminance) + 0.05)
        ).toFixed(2)
      )
    }
    const effectiveBackground = (element) => {
      let current = element
      while (current) {
        const value = getComputedStyle(current).backgroundColor
        if (value && value !== 'transparent' && !value.endsWith(', 0)')) return value
        current = current.parentElement
      }
      return 'rgb(255, 255, 255)'
    }
    const leafText = Array.from(document.querySelectorAll('body *')).filter(
      (element) =>
        visible(element) &&
        element.children.length === 0 &&
        (element.textContent || '').trim().length >= 2 &&
        !element.classList.contains('el-sr-only')
    )
    const textRecords = leafText.map((element) => {
      const style = getComputedStyle(element)
      const background = effectiveBackground(element)
      let classifiedAncestor = element.parentElement
      while (classifiedAncestor && !classifiedAncestor.className) {
        classifiedAncestor = classifiedAncestor.parentElement
      }
      return {
        text: (element.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 60),
        tagName: element.tagName.toLowerCase(),
        className: String(element.className || '').slice(0, 100),
        parentClassName: String(element.parentElement?.className || '').slice(0, 100),
        ancestorClassName: String(classifiedAncestor?.className || '').slice(0, 100),
        fontSize: Number.parseFloat(style.fontSize),
        fontWeight: Number(style.fontWeight) || (style.fontWeight === 'bold' ? 700 : 400),
        contrast: contrast(style.color, background)
      }
    })
    const targets = Array.from(
      document.querySelectorAll(
        "button, a, [role='button'], [role='treeitem'], .audit-item-directory [role='tab'], .standard-tree-node.is-file"
      )
    )
      .filter(visible)
      .map((element) => {
        const rect = element.getBoundingClientRect()
        return {
          text: (element.textContent || element.getAttribute('aria-label') || '')
            .trim()
            .replace(/\s+/g, ' ')
            .slice(0, 50),
          width: Math.round(rect.width),
          height: Math.round(rect.height)
        }
      })
    const underTwelve = textRecords.filter((item) => item.fontSize < 12)
    const excessiveWeight = textRecords.filter((item) => item.fontWeight >= 800)
    const lowContrast = textRecords.filter((item) => item.contrast !== null && item.contrast < 4.5)
    const minimumTargetSize = width <= 900 ? 44 : 32
    const undersizedTargets = targets.filter(
      (item) => item.width < minimumTargetSize || item.height < minimumTargetSize
    )
    return {
      visibleTextCount: textRecords.length,
      underTwelveCount: underTwelve.length,
      excessiveWeightCount: excessiveWeight.length,
      lowContrastCount: lowContrast.length,
      undersizedTargetCount: undersizedTargets.length,
      horizontalOverflow:
        document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
      examples: {
        underTwelve: underTwelve.slice(0, 8),
        excessiveWeight: excessiveWeight.slice(0, 8),
        lowContrast: lowContrast.slice(0, 8),
        undersizedTargets: undersizedTargets.slice(0, 8)
      }
    }
  }, viewport)

const browser = await chromium.launch({ headless: true })
const results = []

try {
  for (const viewport of viewports) {
    for (const route of routes) {
      const context = await browser.newContext({ viewport: { width: viewport, height: 900 } })
      const page = await context.newPage()
      try {
        await login(page, route.account, route.path)
        results.push({
          route: route.path,
          label: route.label,
          account: route.account,
          viewport,
          ...(await inspectPage(page, viewport))
        })
      } catch (error) {
        results.push({
          route: route.path,
          label: route.label,
          account: route.account,
          viewport,
          error: error instanceof Error ? error.message : String(error)
        })
      } finally {
        await context.close()
      }
    }
  }
} finally {
  await browser.close()
}

const summary = {
  schemaVersion: 'aicheck-ui-visual-audit@1',
  generatedAt: new Date().toISOString(),
  baseUrl,
  strict,
  checks: results.length,
  failedLoads: results.filter((item) => item.error).length,
  underTwelve: results.reduce((sum, item) => sum + (item.underTwelveCount || 0), 0),
  excessiveWeight: results.reduce((sum, item) => sum + (item.excessiveWeightCount || 0), 0),
  lowContrast: results.reduce((sum, item) => sum + (item.lowContrastCount || 0), 0),
  undersizedTargets: results.reduce((sum, item) => sum + (item.undersizedTargetCount || 0), 0),
  horizontalOverflow: results.filter((item) => item.horizontalOverflow).length,
  results
}

console.log(JSON.stringify(summary, null, 2))

if (
  strict &&
  (summary.failedLoads ||
    summary.underTwelve ||
    summary.excessiveWeight ||
    summary.lowContrast ||
    summary.undersizedTargets ||
    summary.horizontalOverflow)
) {
  process.exitCode = 1
}
