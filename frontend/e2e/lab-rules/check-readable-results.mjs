import { chromium, expect } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 390, height: 900 } })
const errors = []
page.on('pageerror', error => errors.push(error.message))
try {
  await page.goto('http://127.0.0.1:4394/e2e/lab-rules/readable-results.html')
  const card = page.getByRole('region', { name: '当前节点审查结果' })
  await expect(card).toBeVisible()
  await expect(card.getByRole('heading', { name: '证据不足', exact: true })).toBeVisible()
  await expect(card.locator('.finding-list > li')).toHaveCount(3)
  await expect(card.locator('.detail-body').first()).not.toBeVisible()
  await expect(card.locator('.run-details dd').first()).not.toBeVisible()
  const summary = card.locator('.finding-detail summary').first()
  await summary.focus()
  await page.keyboard.press('Enter')
  await expect(card.locator('.detail-body').first()).toBeVisible()
  await card.getByRole('button', { name: '无损检测工艺规程.pdf · 第 2 页 · 查看原文' }).click()
  await expect(page.locator('#opened')).toHaveText('DV-1:2')
  await expect(card.getByText('未能定位的引用仍保留。')).toBeVisible()
  await expect(card.getByText('这项没有附上原文引用，还需要补充或核对依据。').first()).not.toBeVisible()
  await summary.click()
  await expect(page.locator('.readable-analysis .review-markdown')).not.toBeVisible()
  await page.locator('.readable-analysis summary').click()
  await expect(page.locator('.readable-analysis')).toContainText('原文全文保留。'.repeat(150))
  await page.locator('.readable-analysis summary').click()
  await expect(page.getByText('这是普通问答的完整回答。'.repeat(80), { exact: true })).toBeVisible()
  for (const [value, label] of Object.entries({ supported: '证据支持', partially_supported: '部分证据支持', conflict: '证据冲突', mismatch: '不一致', new_status: '待人工确认' })) {
    await page.locator('#status').selectOption(value)
    await expect(card.getByRole('heading', { name: label, exact: true })).toBeVisible()
  }
  await page.locator('#empty').click()
  await expect(card).toContainText('还不能据此认定通过')
  await page.locator('#many').click()
  await expect(card.locator('.finding-list > li')).toHaveCount(12)
  await expect(card.getByText('需要核对的事项 12', { exact: true })).toBeVisible()
  await page.reload()
  await mkdir('../docs/lab/verification/browser', { recursive: true })
  for (const width of [390, 1280]) {
    await page.setViewportSize({ width, height: 900 })
    for (const theme of ['light', 'dark']) {
      await page.evaluate(theme => { document.documentElement.classList.toggle('dark', theme === 'dark'); document.body.style.background = 'var(--el-bg-color)' }, theme)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      await card.screenshot({ path: `../docs/lab/verification/browser/readable-results-${width}-${theme}.png` })
      await card.locator('.finding-detail summary').first().click()
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      await card.locator('.finding-detail summary').first().click()
    }
  }
  expect(errors).toEqual([])
  console.log('Readable results: all findings, status labels, empty/unknown states, keyboard disclosure, pinned evidence, full text, mobile and themes passed')
} finally { await browser.close() }
