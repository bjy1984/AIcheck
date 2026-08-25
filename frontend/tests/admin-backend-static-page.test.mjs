import assert from 'node:assert/strict'
import test from 'node:test'
import { pathToFileURL } from 'node:url'

import { chromium } from '@playwright/test'

const adminBackendUrl = pathToFileURL(
  new URL('../../ui/admin_backend.html', import.meta.url).pathname
).href

test('does not show the administrator boundary notice below the menu', async () => {
  const browser = await chromium.launch({ headless: true })

  try {
    const page = await browser.newPage()
    await page.goto(adminBackendUrl)

    assert.equal(await page.locator('aside.left > .node-files').count(), 0)
  } finally {
    await browser.close()
  }
})
