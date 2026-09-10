import { chromium, expect } from '@playwright/test'
import { readFile } from 'node:fs/promises'
const browser = await chromium.launch({ channel: 'chrome', headless: true })
try {
 const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
 const errors = []
 page.on('pageerror', e => errors.push(e.message))
 const pdf = await readFile('../test2/9.1金辉焊接工艺评定20.pdf')
 await page.route('**/fixtures/real-rt.pdf', route => route.fulfill({ status: 200, contentType: 'application/pdf', body: pdf }))
 await page.goto('http://127.0.0.1:4394/e2e/lab-rules/file-detail-pages.html')
 await page.getByRole('heading', { name: '这份文件里有哪些资料' }).waitFor()
 await page.getByRole('button', { name: /第 11 页 · 射线检测报告/ }).click()
 const frame = page.locator('iframe.preview-frame')
 await expect(frame).toHaveAttribute('src', /real-rt.pdf#page=11$/)
 await expect(page.locator('.locate-hint')).toContainText('第 11 页')
 await page.waitForTimeout(2000) // Native PDF viewer paints asynchronously after iframe navigation.
 await page.screenshot({ path: '../docs/lab/verification/browser/file-detail-page-11.png', fullPage: true })
 await page.locator('#stale').click()
 await expect(page.getByRole('heading', { name: '这份文件里有哪些资料' })).toHaveCount(0)
 await expect(frame).not.toHaveAttribute('src', /#page=11$/)
 expect(errors).toEqual([])
 console.log('PASS: original FileDetailDialog renders classifications, selects page 11 via existing PDF iframe and hint; mismatched-version classifications removed. Seeded metadata / intercepted local real PDF, not authenticated API acceptance.')
} finally { await browser.close() }
