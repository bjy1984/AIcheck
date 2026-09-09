import { readFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import assert from 'node:assert/strict'
import { chromium } from '@playwright/test'
const file = 'src/views/AIReviewB/ConversationalReviewWorkbenchB.vue'
const base = process.argv[2] || '4cac73d1'
const sources = [execFileSync('git', ['show', `${base}:frontend/${file}`], { encoding: 'utf8' }), readFileSync(file, 'utf8')]
const browser = await chromium.launch({ channel: 'chrome', headless: true })
try {
  const results = []
  for (const source of sources) {
    const page = await browser.newPage()
    await page.setContent(`<style>${source.split('<style scoped>')[1].split('</style>')[0]} * { transition: none !important; }</style><div class="review-b-shell"><div class="review-b-layout"><span class="typing-caret"></span><div class="brand"></div><div class="project-switcher"></div></div></div>`)
    const samples = []
    for (const width of [1200, 1600]) {
      await page.setViewportSize({ width, height: 900 })
      for (const reducedMotion of ['reduce', 'no-preference']) {
        await page.emulateMedia({ reducedMotion })
        samples.push(await page.evaluate(() => [getComputedStyle(document.querySelector('.review-b-layout')).gridTemplateColumns, getComputedStyle(document.querySelector('.typing-caret')).animationName, getComputedStyle(document.querySelector('.project-switcher')).width]))
      }
    }
    results.push(samples)
    await page.close()
  }
  assert.deepEqual(results[1], results[0])
  console.log('Chrome responsive and reduced-motion comparison passed')
} finally { await browser.close() }
