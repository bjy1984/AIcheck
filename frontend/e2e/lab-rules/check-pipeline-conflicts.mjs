import { chromium, expect } from '@playwright/test'
const browser = await chromium.launch({ headless: true, channel: 'chrome' })
const page = await browser.newPage({ viewport: { width: 390, height: 844 } })
const errors = []
page.on('pageerror', error => errors.push(String(error)))
const report = run => ({ projectId: 'PROJECT', reviewRunId: run, createdAt: '2026-09-09', conflicts: [{
  pipelineId: 'PL-101', field: 'designPressureMPa', sources: [
    { value: 1.6, source: { fileName: '管道特性表.pdf', documentVersionId: 'DESIGN-V1', pageNo: 2 } },
    { value: 2.5, source: { fileName: '管道特性表修订版.pdf', documentVersionId: 'DESIGN-V2', pageNo: 3 } }
  ] }] })
let mode = 'ok'
let pending
await page.route('**/pipeline-conflicts', async route => {
  const run = route.request().url().includes('RUN-A') ? 'RUN-A' : 'RUN-B'
  if (mode === 'delay') { pending = route; return }
  if (mode === 'fail') return route.fulfill({ json: { code: 403, message: 'denied' } })
  return route.fulfill({ json: { code: 0, data: { report: report(mode === 'mismatch' ? 'OTHER' : run) } } })
})
try {
  await page.goto('http://127.0.0.1:4393/e2e/lab-rules/conflicts.html')
  await page.getByRole('button', { name: '查看冲突明细' }).click()
  await expect(page.getByText('PL-101 · 设计压力（MPa）')).toBeVisible()
  await expect(page.getByText('2.5', { exact: true })).toBeVisible()
  await expect(page.getByText('页码 3', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: '../docs/lab/verification/browser/pipeline-conflicts-390.png', fullPage: true })
  for (const failure of ['fail', 'mismatch']) {
    mode = failure
    await page.getByRole('button', { name: /读取冲突报告|查看冲突明细/ }).click()
    await expect(page.getByText('冲突报告暂不可用或无权读取，请核对文件权限后重试。')).toBeVisible()
    await expect(page.getByText('2.5', { exact: true })).toHaveCount(0)
  }
  mode = 'delay'
  await page.getByRole('button', { name: '查看冲突明细' }).click()
  await expect.poll(() => Boolean(pending)).toBe(true)
  await page.getByRole('button', { name: '切换任务' }).click()
  mode = 'ok'
  await page.getByRole('button', { name: '查看冲突明细' }).click()
  await expect(page.getByText('2.5', { exact: true })).toBeVisible()
  const oldResponse = page.waitForResponse(response => response.url().includes('RUN-A') && response.url().endsWith('pipeline-conflicts'))
  await pending.fulfill({ json: { code: 0, data: { report: { ...report('RUN-A'), conflicts: [] } } } })
  await oldResponse
  await expect(page.getByText('2.5', { exact: true })).toBeVisible()
  expect(errors).toEqual([])
  console.log('Conflict panel: values, versions, narrow layout, errors, identity mismatch and stale response passed')
} finally { await browser.close() }
