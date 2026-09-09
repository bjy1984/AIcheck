import { chromium, expect } from '@playwright/test'
const browser = await chromium.launch({ headless: true, channel: 'chrome' })
const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } })
page.setDefaultTimeout(10000)
const base = 'http://127.0.0.1:4394'
const path = '/api/projects/P-2026-HDCP-001/review-handoffs'
const errors = []
page.on('pageerror', error => errors.push(String(error)))
try {
  await expect.poll(async () => {
    try { return (await page.request.get(base + path)).status() } catch { return 0 }
  }, { timeout: 10000 }).toBe(200)
  const created = await page.request.post(base + path, { data: {
    sourceRunId: 'RR-LAB-HANDOFF-SOURCE', targetRunId: 'RR-LAB-HANDOFF-TARGET', kind: 'facts',
    subject: { objectType: 'weld', objectId: 'W-101', repairRound: 1, eventId: 'EV-1' },
    payload: { '协作事项': '合成测试：核对 W-101 / EV-1 / 返修轮次 1' },
    evidenceRefs: [{ documentVersionId: 'VER-LAB-HANDOFF', pageNo: 1,
      quotedText: 'SYNTHETIC TEST ONLY: W-101 / EV-1 / repair round 1' }]
  } })
  const result = await created.json()
  expect(result.code).toBe(0)
  const id = result.data.id
  const detail = async () => (await (await page.request.get(base + path + '/' + id)).json()).data
  await page.goto(base + '/e2e/lab-rules/handoffs-live.html')
  await page.getByRole('button', { name: '工位交接', exact: true }).click()
  const choose = () => page.getByRole('button', { name: /A → E/ }).click()
  await choose()
  const original = page.waitForResponse(response => response.url().includes('/original?versionId=VER-LAB-HANDOFF'))
  await page.getByRole('button', { name: '查看原文 1' }).click()
  const pdf = await original
  expect(pdf.status()).toBe(200)
  expect(pdf.headers()['content-type']).toContain('application/pdf')
  const signature = await page.evaluate(async url => {
    const response = await fetch(url)
    const bytes = new Uint8Array(await response.arrayBuffer())
    return String.fromCharCode(...bytes.slice(0, 5))
  }, pdf.url())
  expect(signature).toBe('%PDF-')
  const preview = page.getByRole('dialog', { name: '文件证据定位' })
  await expect(preview).toBeVisible()
  await expect(preview.locator('iframe')).toHaveAttribute('src', /blob:.*#page=1/)
  const openedSignature = await page.evaluate(async url => {
    const bytes = new Uint8Array(await (await fetch(url.split('#')[0])).arrayBuffer())
    return String.fromCharCode(...bytes.slice(0, 5))
  }, await preview.locator('iframe').getAttribute('src'))
  expect(openedSignature).toBe('%PDF-')
  await preview.getByRole('button', { name: /close|关闭/i }).click()
  await page.getByRole('textbox', { name: '核验说明（必填）' }).fill('合成资料联调：已核对固定原文和事件')
  await page.getByText('已核对对象、事件及返修轮次一致', { exact: true }).click()
  await page.getByText('已核对原文支持交接内容', { exact: true }).click()
  await page.getByRole('button', { name: '确认交接', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('人工确认已保存')
  const verified = await detail()
  expect(verified.verification.status).toBe('verified')
  expect(verified.verifications[0].reviewedByUserId).toBe('USER-INSPECTION-001')
  expect(verified.draft.authoritative).toBe(false)
  expect(verified.draft.schemaVersion).toBe('review-handoff-draft-v3')
  await page.request.post(base + '/__lab/handoff/progress-target')
  const progressed = await detail()
  expect(progressed.verification.status).toBe('verified')
  expect(progressed.verifications).toEqual(verified.verifications)
  await choose()
  await page.getByRole('textbox', { name: '核验说明（必填）' }).fill('合成资料联调：追加退回，保留前次记录')
  await page.getByRole('button', { name: '退回交接', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('退回意见已保存')
  const rejected = await detail()
  expect(rejected.verifications).toHaveLength(2)
  expect(rejected.verifications[0]).toEqual(verified.verifications[0])
  expect(rejected.verification.status).toBe('rejected')
  await page.request.post(base + '/__lab/handoff/change-source')
  await choose()
  await expect(page.getByText('交接内容或来源已变更，请重新建立交接后核验。')).toBeVisible()
  await expect(page.getByRole('button', { name: '确认交接', exact: true })).toBeDisabled()
  const stale = await detail()
  expect(stale.verification.status).toBe('stale')
  expect(stale.verifications).toEqual(rejected.verifications)
  await expect(page.getByRole('button', { name: '查看原文 1' })).toBeEnabled()
  await page.screenshot({ path: '../docs/lab/verification/browser/handoff-live-stale.png', fullPage: true })
  await page.request.post(base + '/__lab/handoff/restrict-source')
  await page.getByRole('button', { name: '刷新交接列表', exact: true }).click()
  await expect(page.getByText('当前任务没有可读取的交接。')).toBeVisible()
  const denied = await (await page.request.get(base + path + '/' + id)).json()
  expect(denied.code).not.toBe(0)
  expect(errors).toEqual([])
  console.log('real API handoff browser integration passed: pinned PDF, confirm, reject, stale sources, revoked node permission')
} finally { await browser.close() }
