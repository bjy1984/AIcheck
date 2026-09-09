import { chromium, expect } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
const errors = []
const originalRequests = []
page.on('pageerror', error => errors.push(error.message))
await page.route('**/api/projects/**', route => {
  if (new URL(route.request().url()).pathname.endsWith('/original')) {
    originalRequests.push(new URL(route.request().url()))
    return route.fulfill({ status: 404, json: { code: 404, message: '示例版本原文暂不可用' } })
  }
  return route.fulfill({ json: { code: 0, data: { items: [], total: 0, rules: [], atomicOptions: [] } } })
})
try {
  await page.goto('http://127.0.0.1:4394/e2e/lab-rules/workstation-overview.html')
  const overview = page.getByRole('region', { name: '节点待办与结果' })
  await expect(overview).toBeVisible()
  await expect(overview.locator('.finding-list > li')).toHaveCount(1)
  await overview.getByRole('button', { name: '查看全部 2' }).click()
  await expect(overview.locator('.finding-list > li')).toHaveCount(2)
  await expect(overview.getByText('文件编号已填写', { exact: true })).toBeVisible()
  await overview.getByRole('button', { name: '待核对 1' }).click()
  await overview.locator('.finding-detail summary').first().focus()
  await page.keyboard.press('Enter')
  await overview.getByRole('button', { name: /工艺规程.pdf.*查看原文/ }).click()
  await expect(page.locator('.inline-locator')).toBeVisible()
  await expect(page.locator('.inline-locator').getByRole('alert')).toBeVisible()
  expect(originalRequests.some(url => url.pathname === '/api/projects/PROJECT-A/documents/DOC-DEMO/original' && url.searchParams.get('versionId') === 'DV-DEMO')).toBe(true)
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.locator('#preview-version').click()
  await expect.poll(() => originalRequests.some(url => url.searchParams.get('versionId') === 'DV-OTHER')).toBe(true)
  await page.locator('#preview-mode').click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.setViewportSize({ width: 390, height: 900 })
  const bounds = await page.getByRole('dialog').boundingBox()
  expect(bounds.width).toBeLessThanOrEqual(390)
  await page.getByRole('dialog').getByRole('button', { name: 'Close this dialog', exact: true }).click()
  await page.locator('#preview-mode').click()
  await page.setViewportSize({ width: 1440, height: 1000 })
  await overview.getByRole('button', { name: /工艺规程.pdf.*查看原文/ }).click()
  await page.getByRole('button', { name: '返回审查' }).click()
  await expect(page.locator('.inline-locator')).toHaveCount(0)
  await overview.getByRole('button', { name: '调整资料' }).click()
  await expect(page.getByRole('button', { name: '选择本次文件', exact: true })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.getByRole('dialog').getByRole('button', { name: 'Close this dialog', exact: true }).click()
  await overview.getByRole('button', { name: '有疑问，继续追问' }).click()
  await expect(page.locator('#prototype-navigation')).toHaveText('已打开追问入口')
  for (const [state, text] of Object.entries({ loading: '正在加载这个节点的资料', error: '这次加载失败', empty: '先选择一个节点', readonly: '当前没有保存人工结论的权限', stale: '资料已经变了' })) {
    await page.locator(`[data-state=${state}]`).click()
    await expect(overview).toContainText(text)
    if (state === 'readonly') await expect(overview.getByRole('button', { name: '核对并填写人工结论' })).toBeDisabled()
  }
  await page.locator('[data-state=normal]').click()
  await mkdir('../docs/lab/verification/browser', { recursive: true })
  for (const width of [390, 900, 1440]) {
    await page.setViewportSize({ width, height: 1000 })
    for (const theme of ['light', 'dark']) {
      await page.evaluate(theme => document.documentElement.classList.toggle('dark', theme === 'dark'), theme)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      await page.screenshot({ path: `../docs/lab/verification/browser/workstation-overview-${width}-${theme}.png`, fullPage: true })
    }
  }
  expect(errors).toEqual([])
  console.log('Overview prototype: six states, conservative filtering, complete results, inline evidence, existing tools, keyboard, mobile and themes passed')
} finally { await browser.close() }
