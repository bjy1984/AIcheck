import { chromium, expect } from '@playwright/test'
const browser = await chromium.launch({ headless: true, channel: 'chrome' })
const page = await browser.newPage({ viewport: { width: 1280, height: 1200 } })
page.setDefaultTimeout(15000)
const errors = []
page.on('pageerror', error => errors.push(String(error)))
const root = 'http://127.0.0.1:4393'
const packageUrl = `${root}/api/projects/P-2026-HDCP-001/nodes/24/package`
const bindings = async () => (await (await page.request.get(packageUrl)).json()).data.bindings
try {
  const before = await bindings()
  await page.goto(`${root}/e2e/lab-rules/documents.html`)
  await page.getByRole('button', { name: '选择本次文件', exact: true }).click()
  await expect(page.getByRole('checkbox', { name: '同时保存为本节点补充资料' })).not.toBeChecked()
  await page.getByLabel('搜索文件名称、来源单位或类别').fill('LAB-PICK-01')
  await page.getByRole('button', { name: '搜索 / 刷新', exact: true }).click()
  await page.getByText('LAB-PICK-01.txt', { exact: true }).click()
  await page.getByText('同时保存为本节点补充资料', { exact: true }).click()
  const keys = []
  await page.route('**/inspection/nodes/24/file-bindings', async route => {
    keys.push(route.request().headers()['idempotency-key'])
    expect(route.request().postDataJSON().bindings).toEqual([
      { documentId: 'DOC-PICK-1', documentVersionId: 'VER-PICK-1', usage: '监检资料' }
    ])
    const response = await route.fetch()
    expect((await response.json()).code).toBe(0)
    if (keys.length === 1) await route.abort()
    else await route.fulfill({ response })
  })
  await page.getByRole('button', { name: '保存选择并挂载', exact: true }).click()
  await expect(page.getByText('节点挂载未确认成功，已选文件仍保留。可重试；若工程已更新，请刷新工作台后再保存。')).toBeVisible()
  await expect(page.getByTestId('selection')).toHaveText('null')
  await expect(page.locator('.document-picker-chosen .el-tag')).toHaveCount(1)
  await page.screenshot({ path: '../docs/lab/verification/browser/document-binding-retry.png', fullPage: true, animations: 'disabled' })
  await page.getByRole('button', { name: '保存选择并挂载', exact: true }).click()
  await expect(page.getByTestId('selection')).toContainText('VER-PICK-1')
  expect(keys).toHaveLength(2)
  expect(keys[0]).toBe(keys[1])
  const added = (await bindings()).filter(row => !before.some(old => old.id === row.id))
  expect(added).toHaveLength(1)
  expect(added[0].documentVersionId).toBe('VER-PICK-1')
  expect(added[0].requirementId).toBeNull()
  await page.getByRole('button', { name: '本次文件 1 份', exact: true }).click()
  await expect(page.getByRole('checkbox', { name: '同时保存为本节点补充资料' })).not.toBeChecked()
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await page.unroute('**/inspection/nodes/24/file-bindings')
  await page.reload()
  await page.getByRole('button', { name: '选择本次文件', exact: true }).click()
  await page.getByLabel('搜索文件名称、来源单位或类别').fill('LAB-PICK-01')
  await page.getByRole('button', { name: '搜索 / 刷新', exact: true }).click()
  await page.getByText('LAB-PICK-01.txt', { exact: true }).click()
  await page.getByText('同时保存为本节点补充资料', { exact: true }).click()
  await page.getByRole('button', { name: '保存选择并挂载', exact: true }).click()
  await expect(page.getByTestId('selection')).toContainText('VER-PICK-1')
  const afterReload = (await bindings()).filter(row => !before.some(old => old.id === row.id))
  expect(afterReload.map(row => row.id)).toEqual(added.map(row => row.id))
  await page.getByRole('button', { name: '本次文件 1 份', exact: true }).click()
  await page.getByText('同时保存为本节点补充资料', { exact: true }).click()
  let release
  let arrived
  const gate = new Promise(resolve => { release = resolve })
  const started = new Promise(resolve => { arrived = resolve })
  await page.route('**/inspection/nodes/24/file-bindings', async route => {
    const response = await route.fetch()
    arrived()
    await gate
    await route.fulfill({ response })
  })
  await page.getByRole('button', { name: '保存选择并挂载', exact: true }).click()
  await started
  await expect(page.getByRole('button', { name: '取消', exact: true })).toBeDisabled()
  // Simulate the host changing props while the mutation response is in flight.
  await page.getByRole('button', { name: '切换测试节点', exact: true }).dispatchEvent('click')
  release()
  await expect(page.getByRole('button', { name: '选择本次文件', exact: true })).toBeEnabled()
  await expect(page.getByTestId('selection')).toHaveText('null')
  await page.getByRole('button', { name: '选择本次文件', exact: true }).click()
  await expect(page.locator('.document-picker-chosen .el-tag')).toHaveCount(0)
  expect(errors).toEqual([])
  console.log('PASS persistent binding: explicit opt-in, fixed version, lost-response retry, no duplicate after reload, supplemental requirement, default reset')
} finally { await browser.close() }
