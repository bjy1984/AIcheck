import { chromium } from '@playwright/test'
import assert from 'node:assert/strict'
const browser = await chromium.launch({ channel: 'chrome', headless: true })
try {
 const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
 const errors = []
 page.on('pageerror', e => errors.push(e.message))
 await page.goto('http://127.0.0.1:4394/e2e/lab-rules/document-pages.html')
 await page.getByRole('heading', { name: '这份文件里有哪些资料' }).waitFor()
 assert.equal(await page.locator('li').count(), 6)
 assert.ok((await page.locator('section').innerText()).includes('8 页还需确认'))
 await page.getByRole('button', { name: '查看全部 9 页' }).click()
 assert.equal(await page.locator('li').count(), 9)
 const target = page.getByRole('button', { name: /第 9 页/ })
 await target.focus()
 await page.keyboard.press('Enter')
 assert.equal(await page.locator('output').innerText(), '定位到第 9 页')
 assert.equal(await target.getAttribute('aria-pressed'), 'true')
 assert.ok((await target.boundingBox()).height >= 44)
 await page.screenshot({ path: '../docs/lab/verification/browser/document-pages-light.png', fullPage: true })
 await page.evaluate(() => { document.documentElement.classList.add('dark'); document.body.style.background = '#141414'; document.body.style.color = '#eee' })
 await page.waitForTimeout(400) // Let Element Plus theme color transitions settle before visual capture.
 await page.screenshot({ path: '../docs/lab/verification/browser/document-pages-dark.png', fullPage: true })
 assert.deepEqual(errors, [])
 console.log('PASS: full counts, expansion, keyboard selection, 44px targets, light/dark rendering; synthetic component, not authenticated full-flow acceptance')
} finally { await browser.close() }
