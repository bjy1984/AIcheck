import { chromium, expect } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 390, height: 900 } })
const errors = []
const requests = []
page.on('pageerror', error => errors.push(error.message))
await page.route('**/api/projects/**', route => {
  requests.push(new URL(route.request().url()))
  return route.fulfill({ json: { code: 0, data: { items: [], total: 0, rules: [], atomicOptions: [] } } })
})
const region = () => page.getByRole('region', { name: '当前节点审查工具' })
const button = name => region().getByRole('button', { name, exact: true })
try {
  await page.goto('http://127.0.0.1:4394/e2e/lab-rules/workstation-tools.html')
  await expect(region()).toBeVisible()
  await expect(button('选择本次文件')).toBeEnabled()
  await expect(button('工程规则')).toBeEnabled()
  await expect(button('工位交接')).toBeEnabled()
  for (const name of ['选择本次文件', '工程规则', '工位交接']) {
    const box = await button(name).boundingBox()
    expect(box.height).toBeGreaterThanOrEqual(44)
    await button(name).focus()
    await page.keyboard.press('Enter')
    await expect(page.getByRole('dialog')).toBeVisible()
    if (name === '工位交接') await expect(page.getByRole('button', { name: '刷新交接列表' })).not.toHaveClass(/is-loading/)
    await page.getByRole('dialog').getByRole('button', { name: 'Close this dialog', exact: true }).focus()
    await page.keyboard.press('Enter')
    await expect(page.getByRole('dialog')).not.toBeVisible()
  }
  expect(requests.some(url => url.pathname.includes('/PROJECT-A/documents'))).toBe(true)
  expect(requests.some(url => url.pathname.includes('/PROJECT-A/rules/versions'))).toBe(true)
  expect(requests.some(url => url.searchParams.get('targetRunId') === 'RUN-A')).toBe(true)
  await button('工程规则').click()
  await page.locator('#scope').evaluate(el => el.click())
  await expect(page.getByRole('dialog')).not.toBeVisible()
  await button('工位交接').click()
  await expect(page.getByRole('dialog')).toBeVisible()
  expect(requests.some(url => url.pathname.includes('/PROJECT-B/review-handoffs') && url.searchParams.get('targetRunId') === 'RUN-B')).toBe(true)
  await expect(page.getByRole('button', { name: '刷新交接列表' })).not.toHaveClass(/is-loading/)
  await page.getByRole('dialog').getByRole('button', { name: 'Close this dialog', exact: true }).click()
  await expect(page.getByRole('dialog')).not.toBeVisible()
  await page.locator('#busy').click()
  await expect(button('选择本次文件')).toBeDisabled()
  await page.locator('#run').click()
  await expect(button('工位交接')).toBeDisabled()
  await expect(region()).toContainText('发起审查后')
  await page.locator('#busy').click()
  await page.locator('#run').click()
  await mkdir('../docs/lab/verification/browser', { recursive: true })
  for (const [width, height] of [[390, 900], [900, 390], [1280, 900]]) {
    await page.setViewportSize({ width, height })
    for (const theme of ['light', 'dark']) {
      await page.evaluate(theme => { document.documentElement.classList.toggle('dark', theme === 'dark'); document.body.style.background = 'var(--el-bg-color)' }, theme)
      await page.emulateMedia({ reducedMotion: 'reduce', colorScheme: theme })
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      await region().screenshot({ path: `../docs/lab/verification/browser/workstation-tools-${width}-${theme}.png` })
    }
  }
  expect(errors).toEqual([])
  console.log('Workstation toolbar: three dialogs, keyboard, scope reset, permissions, responsive and theme checks passed')
} finally { await browser.close() }
