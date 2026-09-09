import { chromium, expect } from '@playwright/test'
const browser = await chromium.launch({ headless: true, channel: 'chrome' })
try {
  for (const width of [1280, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 1000 } })
    page.setDefaultTimeout(15000)
    const errors = []
    page.on('pageerror', error => errors.push(String(error)))
    await page.goto('http://127.0.0.1:4393/e2e/lab-rules/documents.html')
    await page.getByRole('button', { name: '选择本次文件', exact: true }).click()
    await page.getByLabel('搜索文件名称、来源单位或类别').fill('LAB-PICK-01')
    await page.getByRole('button', { name: '搜索 / 刷新', exact: true }).click()
    await page.locator('.document-picker-row').filter({ hasText: 'LAB-PICK-01.txt' }).getByRole('button', { name: '版本', exact: true }).click()
    const pdf = page.locator('.version-row').filter({ hasText: 'historical.pdf' })
    await pdf.locator('.el-checkbox').click()
    const overflow = await page.locator('.version-row').evaluateAll(rows => rows.some(row => row.scrollWidth > row.clientWidth + 1))
    expect(overflow).toBe(false)
    await page.screenshot({ path: `../docs/lab/verification/browser/version-list-${width}.png`, fullPage: true, animations: 'disabled' })
    const responsePromise = page.waitForResponse(response => response.url().includes('versionId=VER-PICK-1-PDF'))
    await pdf.getByRole('button', { name: '预览此版本' }).click()
    const response = await responsePromise
    expect(response.headers()['content-type']).toContain('application/pdf')
    await expect(page.locator('.version-preview')).toBeVisible()
    await expect(page.locator('.version-preview')).toHaveAttribute('src', /^blob:/)
    const prefix = await page.locator('.version-preview').evaluate(async frame => (await (await fetch(frame.src)).text()).slice(0, 5))
    expect(prefix).toBe('%PDF-')
    // Wait for Chrome's built-in viewer document, then inspect its actual loaded state.
    await expect.poll(() => page.frames().some(frame => frame.url().startsWith('chrome-extension:'))).toBe(true)
    const viewer = page.frames().find(frame => frame.url().startsWith('chrome-extension:'))
    await expect.poll(() => viewer.evaluate(() => document.querySelector('pdf-viewer')?.shadowRoot?.querySelector('viewer-toolbar')?.docLength || 0)).toBe(2)
    await page.screenshot({ path: `../docs/lab/verification/browser/version-pdf-${width}.png`, fullPage: true, animations: 'disabled' })
    const dialog = page.getByRole('dialog', { name: 'historical.pdf · V-PDF', exact: true })
    const box = await dialog.boundingBox()
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width).toBeLessThanOrEqual(width)
    await dialog.locator('.el-dialog__headerbtn').click()
    await page.getByRole('button', { name: '返回文件选择', exact: true }).click()
    await page.getByRole('button', { name: '保存本次选择', exact: true }).click()
    await expect(page.getByTestId('selection')).toContainText('VER-PICK-1-PDF')
    expect(errors).toEqual([])
    await page.close()
  }
  console.log('PASS PDF viewer: two real pages loaded; desktop and narrow viewport selection/preview/save')
} finally { await browser.close() }
