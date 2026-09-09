import { chromium, expect } from '@playwright/test'
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
const errors = []
const pending = []
page.on('pageerror', error => errors.push(error.message))
await page.route('**/api/projects/*/review-handoff-node-statuses', route => { pending.push(route) })
const waitRequest = count => expect.poll(() => pending.length).toBe(count)
const finish = async (index, projectId, stale = false) => {
  const delivered = page.waitForEvent('requestfinished', request => request === pending[index].request())
  await pending[index].fulfill({ json: { code: 0, data: {
  projectId, items: [35, 36].map(nodeId => ({ nodeId,
    status: stale ? 'requires_revalidation' : 'current', requiresRevalidation: stale }))
} } })
  await delivered
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
}
const summary = page.getByRole('region', { name: '工位与节点筛选' })
try {
  await page.goto('http://127.0.0.1:4394/e2e/lab-rules/handoff-races.html')
  await waitRequest(1)
  await expect(summary).toContainText('正在核对交接状态')
  await page.getByRole('button', { name: '工程 B', exact: true }).click()
  await waitRequest(2)
  await finish(1, 'B')
  await expect(summary).toContainText('0 个节点需重验')
  await finish(0, 'A', true)
  await expect(page.locator('#project')).toHaveText('B')
  await expect(summary).toContainText('0 个节点需重验')
  await expect(page.getByRole('tree')).toContainText('B 节点 35')
  await expect(page.getByRole('tree')).not.toContainText('A 节点')
  await summary.getByRole('button', { name: '刷新工位交接状态' }).click()
  await waitRequest(3)
  await pending[2].fulfill({ status: 503, json: { code: 50334, message: '暂时无法核对' } })
  await expect(summary.getByRole('alert')).toContainText('这不代表没有需重验节点')
  await expect(summary).not.toContainText('0 个节点需重验')
  await summary.getByRole('button', { name: '刷新工位交接状态' }).click()
  await waitRequest(4)
  await finish(3, 'B', true)
  await expect(summary).toContainText('2 个节点需重验')
  await expect(summary.getByRole('alert')).toHaveCount(0)
  // A response with the wrong project identity must fail, even for the newest request.
  await summary.getByRole('button', { name: '刷新工位交接状态' }).click()
  await waitRequest(5)
  await finish(4, 'A')
  await expect(summary.getByRole('alert')).toBeVisible()
  await summary.getByRole('button', { name: '刷新工位交接状态' }).click()
  await waitRequest(6)
  await page.getByRole('button', { name: '切换挂载' }).click()
  await finish(5, 'B', true)
  await expect(summary).toHaveCount(0)
  await page.getByRole('button', { name: '切换挂载' }).click()
  await waitRequest(7)
  await finish(6, 'B')
  await expect(summary).toContainText('0 个节点需重验')
  expect(errors).toEqual([])
  console.log('PASS: original workstation component; late project response, 503 without false zero, recovery, wrong-project rejection, unmount/remount; no page errors')
} finally { await browser.close() }
