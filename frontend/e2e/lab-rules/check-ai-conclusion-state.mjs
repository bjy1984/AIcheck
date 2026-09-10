import { chromium } from '@playwright/test'
import assert from 'node:assert/strict'
const browser = await chromium.launch({ channel: 'chrome', headless: true })
try {
 const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
 const errors = []
 page.on('pageerror', e => errors.push(e.message))
 await page.goto('http://127.0.0.1:4394/e2e/lab-rules/ai-conclusion-state.html')
 await page.getByText('原 AI 结果面板 · 合成状态测试').waitFor()
 for (const state of ['empty', 'running', 'failed']) {
  await page.getByRole('button', { name: state, exact: true }).click()
  assert.equal(await page.locator('[aria-label="AI 结论卡"]').count(), 0)
  assert.equal(await page.getByRole('button', { name: '补充 AI 未发现的问题' }).count(), 0)
 }
 await page.getByRole('button', { name: 'complete', exact: true }).click()
 assert.equal(await page.locator('[aria-label="AI 结论卡"]').count(), 1)
 assert.match(await page.locator('[aria-label="AI 结论卡"]').innerText(), /证据不足/)
 await page.getByRole('button', { name: 'empty', exact: true }).click()
 assert.equal(await page.locator('[aria-label="AI 结论卡"]').count(), 0)
 assert.deepEqual(errors, [])
 console.log('PASS: original panel hides conclusions for absent/running/failed runs; completed insufficient result remains; switching to empty removes stale conclusion')
} finally { await browser.close() }
