import { chromium, expect } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
const errors = []
page.on('pageerror', error => errors.push(error.message))
try {
  await page.goto('http://127.0.0.1:4394/e2e/lab-rules/automation-limitations.html')
  const region = page.getByRole('region', { name: '尚需人工核验的系统能力' })
  await expect(region).toBeVisible()
  await expect(region.locator('li')).toHaveCount(3)
  await expect(region).toContainText('参数、单位和适用条件')
  await expect(region).toContainText('哪份设计或规程')
  await expect(region).toContainText('报告结论、缺陷评定和签章')
  await expect(region).not.toContainText('AC-R40-01')
  await expect(region).toContainText('节点 40 · 第 1 项')
  await expect(region).toContainText('补文件不一定能解决')
  await mkdir('../docs/lab/verification/browser', { recursive: true })
  for (const theme of ['light', 'dark']) {
    await page.evaluate(theme => document.documentElement.classList.toggle('dark', theme === 'dark'), theme)
    await page.screenshot({ path: `../docs/lab/verification/browser/r40-limitations-${theme}.png` })
  }
  expect(errors).toEqual([])
  console.log('PASS: existing limitation component shows three distinct actions, readable node/item label, retained system-capability warning; light/dark screenshots saved')
} finally { await browser.close() }
