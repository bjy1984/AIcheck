import { chromium, expect as baseExpect } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
const expect = baseExpect.configure({ timeout: 45000 })

const origin = 'http://127.0.0.1:4407'
const backend = 'http://127.0.0.1:4410'
const projectId = 'P-2026-HDCP-001'
const output = '../output/important-review'
const existing = process.argv.includes('--existing')
let fileName = `专项审查联调样本-${Date.now()}.pdf`
mkdirSync(output, { recursive: true })
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1480, height: 1080 } })
page.setDefaultTimeout(30000)
const errors = []
page.on('pageerror', (error) => errors.push(String(error)))
const failedApi = []
page.on('response', (response) => {
  if (response.url().includes('/api/') && response.status() >= 400)
    failedApi.push({ path: new URL(response.url()).pathname, status: response.status() })
})
try {
  const login = await page.request.post(`${origin}/api/auth/login`, {
    data: { username: 'inspection', password: 'anyuekeji.123' }
  })
  const payload = await login.json()
  if (payload.code !== 0) throw new Error(`Isolated login failed: ${payload.code}`)
  await page.addInitScript(({ token, user }) => {
    sessionStorage.setItem(
      'user',
      JSON.stringify({ tokenKey: 'Authorization', token: `Bearer ${token}`, userInfo: user })
    )
  }, payload.data)
  await page.goto(`${origin}/#/workbench/inspection?projectId=${projectId}&view=important`)
  await expect(page.getByRole('tab', { name: '重要节点审查', exact: true })).toHaveAttribute(
    'aria-selected',
    'true'
  )
  await expect(page.getByRole('heading', { name: '工程资料', exact: true })).toBeVisible()
  if (existing) {
    const response = await page.request.get(
      `${origin}/api/projects/${projectId}/inspection/important-review/runs`,
      { headers: { Authorization: `Bearer ${payload.data.token}` } }
    )
    const runs = await response.json()
    fileName = runs.data.items.find((run) => run.nodeId === 4).documents[0].fileName
  } else {
    const sample = await page.request.get(`${backend}/__important_test/sample.pdf`)
    await page
      .locator('.important-review input[type=file]')
      .setInputFiles({ name: fileName, mimeType: 'application/pdf', buffer: await sample.body() })
    const fileRow = page.locator('.important-review .el-table__row').filter({ hasText: fileName })
    await expect(fileRow).toHaveCount(1)
    await expect(fileRow.getByText('已解析', { exact: true })).toBeVisible({ timeout: 300000 })
    await fileRow.getByRole('checkbox').locator('..').click()
    await page.getByRole('button', { name: '分析适用节点', exact: true }).click()
    await expect(page.getByRole('checkbox', { name: '选择 R04', exact: true })).toBeChecked()
    for (const id of [4, 5, 6, 7, 8, 9, 12, 13, 16, 24, 25, 26]) {
      const box = page.getByRole('checkbox', {
        name: `选择 R${String(id).padStart(2, '0')}`,
        exact: true
      })
      if ((await box.isChecked()) !== (id === 4)) await box.locator('..').click()
    }
    await page
      .locator('.node-row')
      .filter({ hasText: 'R04' })
      .getByRole('button', { name: '审查规则', exact: true })
      .click()
    await expect(page.getByText('来源：业务节点描述 v3', { exact: false })).toBeVisible()
    await page.locator('.el-drawer__close-btn:visible').click()
    await page.screenshot({ path: `${output}/full-workbench-before.png` })
    await page.getByRole('button', { name: /开始审查（已选 1 个节点，1 份文件）/ }).click()
  }
  await expect(page.locator('.result-status').getByText('已完成', { exact: true })).toBeVisible({
    timeout: 300000
  })
  await expect(page.locator('.important-outcomes')).toBeVisible()
  if (existing) await page.getByRole('button', { name: '收起', exact: true }).click()
  await page.getByText('查看固定资料版本', { exact: true }).click()
  await page.locator('.run-meta').getByRole('button', { name: fileName, exact: true }).click()
  await expect(page.locator('.el-drawer:visible')).toBeVisible()
  await expect(page.locator('.el-drawer:visible canvas').first()).toBeVisible({ timeout: 60000 })
  await expect(page.locator('.el-drawer:visible .pdf-evidence')).toHaveAttribute(
    'aria-busy',
    'false',
    { timeout: 60000 }
  )
  await expect(page.locator('.el-drawer:visible').getByRole('status')).toHaveText('第 1 / 2 页')
  await page
    .locator('.el-drawer:visible')
    .getByRole('button', { name: '下一页', exact: true })
    .click()
  await expect(page.locator('.el-drawer:visible').getByRole('status')).toHaveText('第 2 / 2 页')
  await page.screenshot({ path: `${output}/full-workbench-evidence.png` })
  await page.locator('.el-drawer__close-btn:visible').click()
  await page.getByRole('tab', { name: '完整工作台', exact: true }).click()
  await expect(page.locator('.important-review')).not.toBeVisible()
  await page.getByRole('tab', { name: '重要节点审查', exact: true }).click()
  await expect(page.locator('.result-status').getByText('已完成', { exact: true })).toBeVisible()
  await page.screenshot({ path: `${output}/full-workbench-result.png` })
  const report = await (await page.request.get(`${backend}/__important_test/report`)).json()
  writeFileSync(
    `${output}/full-workbench-report.json`,
    JSON.stringify({ ...report, errors, failedApi }, null, 2)
  )
  if (errors.length || report.errors.length || failedApi.length)
    throw new Error('See isolated integration report for errors')
  if (report.liveProviders && !report.reviews.some((run) => run.llmCalled))
    throw new Error('Live review did not call the model')
  console.log(
    'PASS: full workbench + real login/upload/read/analyze/review/PDF APIs',
    JSON.stringify(report)
  )
} catch (error) {
  await page.screenshot({ path: `${output}/full-workbench-failure.png` })
  console.error(JSON.stringify({ errors, failedApi }))
  throw error
} finally {
  await browser.close()
}
