import { chromium, expect } from '@playwright/test'
const browser = await chromium.launch({ headless: true, channel: 'chrome' })
const page = await browser.newPage({ viewport: { width: 390, height: 844 } })
page.setDefaultTimeout(7000)
const errors = []
page.on('pageerror', error => errors.push(String(error)))
let mode = 'ok', submitted, pending
const reviews = []
const item = (run = 'RUN-A') => ({
  id: 'H1', projectId: 'PROJECT',
  draft: { schemaVersion: 'review-handoff-draft-v2', snapshotHash: 'frozen-1', kind: 'collaboration',
    subject: { objectType: 'weld', objectId: 'W-101', repairRound: 1, eventId: 'EV-1' },
    source: { runId: 'SOURCE', stationId: 'A', nodeId: 24 }, target: { runId: run, stationId: 'E', nodeId: 35 },
    payload: { '协作事项': '请核对焊口 W-101 的返修检测事件 EV-1。' }, evidenceRefs: [] },
  validation: { status: mode === 'stale' ? 'stale_or_invalid' : 'current_draft',
    inputSourceCheck: { status: 'current' }, evidenceLocationCheck: { status: 'no_references' } },
  verification: { status: reviews.at(-1)?.outcome || 'unreviewed', authoritative: false }, verifications: reviews
})
await page.route('**/api/projects/PROJECT/review-handoffs**', async route => {
  const request = route.request()
  if (request.method() === 'POST') {
    submitted = request.postDataJSON()
    if (mode === 'submit-fail') return route.fulfill({ json: { code: 409, message: 'changed' } })
    reviews.push({ id: 'VERIFY-' + (reviews.length + 1), outcome: submitted.outcome,
      reviewedByUserId: 'synthetic-reviewer', createdAt: '2026-09-09', note: submitted.note })
    return route.fulfill({ json: { code: 0, data: item() } })
  }
  const url = new URL(request.url())
  if (url.pathname.endsWith('/H1')) {
    if (mode === 'delay') { pending = route; return }
    return route.fulfill({ json: { code: 0, data: item() } })
  }
  const run = url.searchParams.get('targetRunId')
  return route.fulfill({ json: { code: 0, data: { items: run === 'RUN-A' ? [item(run)] : [], total: run === 'RUN-A' ? 1 : 0 } } })
})
const choose = () => page.getByRole('button', { name: /A → E/ }).click()
const confirm = () => page.getByRole('button', { name: '确认交接', exact: true })
const reject = () => page.getByRole('button', { name: '退回交接', exact: true })
const note = () => page.getByRole('textbox', { name: '核验说明（必填）' })
const switchRun = () => page.evaluate(() => document.querySelector('#switch-run').click())
const open = () => page.getByRole('button', { name: '工位交接', exact: true }).click()
try {
  await page.goto('http://127.0.0.1:4394/e2e/lab-rules/handoffs.html')
  await open()
  await choose()
  await expect(confirm()).toBeDisabled()
  await note().fill('合成案例人工确认意见')
  await page.getByText('已核对对象、事件及返修轮次一致', { exact: true }).click()
  await expect(page.getByRole('checkbox', { name: '已核对对象、事件及返修轮次一致' })).toBeChecked()
  await expect(confirm()).toBeDisabled()
  await page.getByText('已核对原文支持交接内容', { exact: true }).click()
  await expect(page.getByRole('checkbox', { name: '已核对原文支持交接内容' })).toBeChecked()
  await confirm().click()
  await expect(page.getByRole('status')).toContainText('人工确认已保存')
  expect(submitted.subject.eventId).toBe('EV-1')
  expect(submitted.snapshotHash).toBe('frozen-1')
  expect(submitted.expectedPreviousId).toBe(null)
  expect(submitted.reviewedByUserId).toBeUndefined()
  await choose()
  await expect(page.getByText('合成案例人工确认意见', { exact: true })).toBeVisible()
  await note().fill('合成案例退回意见')
  await reject().click()
  expect(submitted.expectedPreviousId).toBe('VERIFY-1')
  expect(submitted.outcome).toBe('rejected')
  mode = 'stale'
  await choose()
  await expect(page.getByText('交接内容或来源已变更，请重新建立交接后核验。')).toBeVisible()
  await expect(confirm()).toBeDisabled()
  await expect(reject()).toBeDisabled()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: '../docs/lab/verification/browser/handoff-review-390.png', fullPage: true })
  await page.getByRole('group', { name: '人工核验', exact: true }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: '../docs/lab/verification/browser/handoff-review-form-390.png', fullPage: true })
  await page.setViewportSize({ width: 1280, height: 1000 })
  await page.getByRole('heading', { name: '当前任务 · 收到的工位交接' }).scrollIntoViewIfNeeded()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: '../docs/lab/verification/browser/handoff-review-1280.png', fullPage: true })
  mode = 'submit-fail'
  await choose()
  await note().fill('保留这份意见')
  await reject().click()
  await expect(page.getByRole('alert').filter({ hasText: '提交结果未确认' })).toBeVisible()
  await expect(note()).toHaveValue('保留这份意见')
  await expect(reject()).toBeDisabled()
  await switchRun()
  await expect(page.getByRole('dialog')).not.toBeVisible()
  await switchRun()
  await open()
  mode = 'delay'
  await choose()
  await expect.poll(() => !!pending).toBe(true)
  await switchRun()
  await pending.fulfill({ json: { code: 0, data: item() } })
  await open()
  await expect(page.getByText('当前任务没有可读取的交接。')).toBeVisible()
  await expect(page.getByRole('heading', { name: /W-101/ })).not.toBeVisible()
  expect(errors).toEqual([])
  console.log('handoff browser checks passed: confirmation, history, stale, error retention, scope switch, mobile')
} finally { await browser.close() }
