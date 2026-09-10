import { chromium } from '@playwright/test'
import assert from 'node:assert/strict'
const browser = await chromium.launch({ channel: 'chrome', headless: true })
try {
 const page = await browser.newPage({ viewport: { width: 1280, height: 950 } })
 const errors = []
 page.on('pageerror', e => errors.push(e.message))
 await page.goto('http://127.0.0.1:4394/e2e/lab-rules/approval-checks.html')
 await page.getByRole('heading', { name: '签批记录核对' }).waitFor()
 assert.equal(await page.locator('li').count(), 2)
 assert.match(await page.locator('section').innerText(), /共 3 项，2 项待核对/)
 await page.locator('summary').first().click()
 assert.equal(await page.getByRole('button', { name: /查看原文/ }).count(), 1)
 assert.equal(await page.getByText('第 3 页 · 引用暂时打不开，请到所选文件核对。').count(), 1)
 const button = page.getByRole('button', { name: '第 3 页 · 查看原文' })
 await button.focus()
 await page.keyboard.press('Enter')
 assert.equal(await page.locator('output').innerText(), '定位 V1 第 3 页')
 assert.ok((await button.boundingBox()).height >= 44)
 await page.locator('summary').nth(1).click()
 await page.getByText('第 9 页 · 引用暂时打不开，请到所选文件核对。').waitFor()
 await page.getByRole('button', { name: '查看全部 3' }).click()
 assert.equal(await page.locator('li').count(), 3)
 await page.waitForTimeout(400) // Wait for newly shown Element Plus status tags to finish entering.
 await page.screenshot({ path: '../docs/lab/verification/browser/approval-checks-light.png', fullPage: true })
 await page.evaluate(() => { document.documentElement.classList.add('dark'); document.body.style.background = '#141414' })
 await page.waitForTimeout(400)
 await page.screenshot({ path: '../docs/lab/verification/browser/approval-checks-dark.png', fullPage: true })
 assert.deepEqual(errors, [])
 console.log('PASS: counts, pending/all, preserved judgment, keyboard evidence event, unavailable reference, 44px, light/dark; synthetic component, not authenticated case acceptance')
} finally { await browser.close() }
