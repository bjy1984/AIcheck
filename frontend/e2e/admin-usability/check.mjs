import { chromium, expect } from '@playwright/test'
import assert from 'node:assert/strict'
import { mkdirSync } from 'node:fs'
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } })
page.setDefaultTimeout(15_000)
const errors = [],
  requests = [],
  mutations = []
page.on('pageerror', (e) => errors.push(String(e)))
page.on('console', (message) => {
  if (message.type() === 'error') console.error(message.text())
})

const prompt = {
  id: 'PT1',
  name: '证据审查正式版',
  version: 'v1',
  status: 'production',
  promptKey: 'review',
  businessPackId: 'test-pack',
  agentId: 'reviewer',
  systemPrompt: '必须引用证据',
  userPromptTemplate: '{{reviewTaskJson}}',
  plannerPromptTemplate: '查证据',
  criticPromptTemplate: '复核',
  outputSchema: {},
  etag: 'pt1'
}
const draft = {
  ...prompt,
  id: 'PT2',
  name: '证据审查草稿',
  version: 'v2',
  status: 'draft',
  etag: 'pt2'
}
const report = {
  id: 'RT1',
  name: '工程报告正式版',
  version: 'r1',
  businessPackId: 'test-pack',
  status: 'production',
  exportTypes: ['report'],
  sections: [{ code: 'overview', title: '概况', source: 'project' }],
  etag: 'rt1'
}
const reportDraft = { ...report, id: 'RT2', name: '工程报告草稿', status: 'draft', version: 'r2' }
const promptHistory = [
  ...Array.from({ length: 203 }, (_, i) => ({
    ...prompt,
    id: `PT-HISTORY-${i}`,
    status: 'retired'
  })),
  draft,
  prompt
]
const reportHistory = [
  ...Array.from({ length: 203 }, (_, i) => ({
    ...report,
    id: `RT-HISTORY-${i}`,
    status: 'retired'
  })),
  reportDraft,
  report
]
const templatePage = (url, shown, history) => {
  const pageSize = Number(url.searchParams.get('pageSize'))
  const currentPage = Number(url.searchParams.get('page') || 1)
  const records = pageSize === 100 ? history : shown
  return {
    items: records.slice((currentPage - 1) * pageSize, currentPage * pageSize),
    total: records.length,
    page: currentPage,
    pageSize
  }
}
const reviewPoint = {
  id: 'MP1',
  businessPackId: 'test-pack',
  nodeId: 1,
  nodeName: '核对',
  ruleId: 'R1',
  reviewContent: '检查签名',
  materialTypeName: '签名记录',
  evidenceItems: [],
  minConfidence: 0,
  enabled: true
}
const users = Array.from({ length: 13 }, (_, i) => ({
  id: `U${i}`,
  name: `用户${i}`,
  username: `user${i}`,
  orgId: 'O1',
  orgName: '测试组织',
  role: 'contractor',
  mobile: '',
  status: '启用',
  lastLoginAt: '-'
}))
const fullOverview = {
  metrics: [{ key: 'project', label: '项目总数', value: '7', tone: 'blue' }],
  orgUnits: [
    {
      id: 'O1',
      name: '测试组织',
      type: 'contractor',
      contactName: '',
      contactPhone: '',
      projectCount: 2,
      status: '启用'
    }
  ],
  users,
  permissionMatrix: [],
  nodeTemplates: [],
  workflowStateMachines: [],
  todoRules: [],
  messageTemplates: [],
  toolSources: [],
  fieldMappings: [
    {
      id: 'FM1',
      nodeId: 1,
      fieldName: '签名',
      sourceField: 'signature',
      targetField: 'signature',
      required: false,
      confidenceThreshold: 0
    }
  ],
  ruleVersions: [
    {
      id: 'R1',
      name: '规则加载回归样本',
      version: 'r1',
      nodeIds: [1],
      status: '待发布',
      promptVersion: 'v1',
      outputSchemaVersion: 'v1'
    }
  ],
  materialReviewPoints: [reviewPoint],
  businessPacks: [],
  etag: 'admin1'
}
let integrationFailed = true
await page.route('http://127.0.0.1:4491/api/**', async (route) => {
  const req = route.request(),
    url = new URL(req.url()),
    path = url.pathname
  requests.push({ path, params: Object.fromEntries(url.searchParams), method: req.method() })
  if (req.method() !== 'GET')
    mutations.push({ path, method: req.method(), body: req.postData() ? req.postDataJSON() : null })
  let data = { items: [], total: 0, page: 1, pageSize: 10 }
  if (path === '/api/admin/config-overview') {
    data = structuredClone(fullOverview)
    const sections = (url.searchParams.get('sections') || '').split(',')
    data.omittedSections = ['ruleVersions', 'materialReviewPoints'].filter(
      (key) => !sections.includes(key) && sections[0]
    )
    for (const key of data.omittedSections) data[key] = []
  } else if (path.endsWith('/business-packs')) data = []
  else if (path.includes('/business-packs/') && path.endsWith('validate-all'))
    data = { ok: false, items: [], summary: {} }
  else if (path === '/api/admin/prompt-templates' && req.method() === 'GET')
    data = templatePage(url, [prompt, draft], promptHistory)
  else if (path === '/api/admin/report-templates')
    data = templatePage(url, [report, reportDraft], reportHistory)
  else if (path.includes('/integration-contract')) {
    if (integrationFailed)
      return route.fulfill({ status: 500, json: { code: 500, message: '模拟联调加载失败' } })
    data = {
      summary: { total: 0, aligned: 0, pending: 0, blockers: 0 },
      modules: [],
      fields: [],
      generatedAt: 'test'
    }
  } else if (req.method() === 'DELETE')
    return route.fulfill({ status: 409, json: { code: 409, message: '模拟删除冲突：记录已更新' } })
  else if (path.endsWith('/publish-preview'))
    data = {
      previewId: 'PV1',
      expiresAt: '2099-01-01',
      impact: {
        totalAffected: 1,
        linkedProjects: 7,
        warnings: [],
        impacts: [{ domain: 'rule', label: '业务规则', affectedCount: 1 }]
      }
    }
  else if (path.endsWith('/publish')) data = { template: draft }
  else if (req.method() === 'PUT') data = { overview: fullOverview, diff: { changed: [] } }
  else if (path === '/api/admin/prompt-templates' && req.method() === 'POST')
    data = { template: { ...draft, id: 'PT3' } }
  await route.fulfill({ json: { code: 0, data, operationId: 'test', serverTime: 'test' } })
})
const goto = async (path) => {
  await page.goto(`http://127.0.0.1:4491/e2e/admin-usability/index.html#${path}`, {
    waitUntil: 'networkidle'
  })
  await expect(page.locator('.admin-page .page-title')).toBeVisible()
}
const visiblePane = () => page.locator('.el-tab-pane:visible')
try {
  await goto('/admin/rules')
  await expect(visiblePane().getByText('规则加载回归样本', { exact: true })).toBeVisible()
  assert.ok(
    requests.some(
      (r) => r.path === '/api/admin/config-overview' && r.params.sections === 'ruleVersions'
    )
  )
  await expect(visiblePane().getByText('1 待发布', { exact: true })).toBeVisible()
  await expect(visiblePane().getByText('0 个配置', { exact: true })).toBeVisible()
  await expect(visiblePane().getByText('启用', { exact: true })).toHaveCount(0)
  await goto('/admin/permission')
  await expect(page.getByText('规则状态未获取', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('未获取 条审计记录', { exact: true })).toBeVisible()
  await goto('/admin/business-packs')
  await expect(visiblePane().getByText('未检查', { exact: true })).toBeVisible()
  await goto('/admin/integration')
  await expect(visiblePane().getByText('检查失败', { exact: true })).toBeVisible()
  await expect(visiblePane().getByText('可推进', { exact: true })).toHaveCount(0)
  integrationFailed = false
  await visiblePane().getByRole('button', { name: '重新加载', exact: true }).click()
  await expect(visiblePane().getByText('无阻塞项', { exact: true })).toBeVisible()
  console.log('PASS: actual rule sections and unknown/error states')

  await goto('/admin/prompt-templates')
  await expect(page.getByRole('button', { name: '登记配置版本', exact: true })).toHaveCount(0)
  const prodRow = visiblePane().locator('.el-table__row').filter({ hasText: '证据审查正式版' })
  await prodRow.getByRole('button', { name: '查看', exact: true }).click()
  const drawer = page.locator('.el-drawer:visible')
  await expect(drawer.getByRole('textbox').first()).toBeDisabled()
  await expect(drawer.getByRole('button', { name: '保存模板', exact: true })).toHaveCount(0)
  await drawer.getByRole('button', { name: '取消', exact: true }).click()
  await prodRow.getByRole('button', { name: '创建草稿', exact: true }).click()
  await expect(drawer.getByRole('textbox').first()).toBeEnabled()
  await expect(drawer.locator('input').nth(2)).toHaveValue('v1-draft')
  await drawer.getByRole('button', { name: '保存模板', exact: true }).click()
  await expect(page.locator('.el-drawer:visible')).toHaveCount(0)
  const create = mutations.find(
    (m) => m.path === '/api/admin/prompt-templates' && m.method === 'POST'
  )
  assert.equal(create.body.status, 'draft')
  assert.equal(create.body.systemPrompt, prompt.systemPrompt)
  assert.ok(!create.body.id)
  const before = mutations.length
  await visiblePane()
    .locator('.el-table__row')
    .filter({ hasText: '证据审查草稿' })
    .getByRole('button', { name: '发布', exact: true })
    .click()
  const confirm = page.locator('.el-message-box:visible')
  await expect(confirm).toContainText('证据审查草稿')
  await expect(confirm).toContainText('PT2')
  await expect(confirm).toContainText('PT1')
  assert.ok(requests.some((r) => r.path === '/api/admin/prompt-templates' && r.params.page === '3'))
  await expect(confirm).toContainText('已保存的审查快照不改写')
  await confirm.getByRole('button', { name: '返回检查', exact: true }).click()
  assert.equal(mutations.length, before)
  await visiblePane()
    .locator('.el-table__row')
    .filter({ hasText: '证据审查草稿' })
    .getByRole('button', { name: '发布', exact: true })
    .click()
  await confirm.getByRole('button', { name: '确认发布此版本', exact: true }).click()
  await expect
    .poll(
      () => mutations.filter((m) => m.path === '/api/admin/prompt-templates/PT2/publish').length
    )
    .toBe(1)
  const publication = mutations.find((m) => m.path === '/api/admin/prompt-templates/PT2/publish')
  assert.match(publication.body.reason, /证据审查草稿.*v2.*PT2/)
  await expect(confirm).toHaveCount(0)
  console.log('PASS: immutable production, copy draft, named publish and cancellation')

  await goto('/admin/report-templates')
  await visiblePane()
    .locator('.el-table__row')
    .filter({ hasText: '工程报告草稿' })
    .getByRole('button', { name: '发布', exact: true })
    .click()
  await expect(confirm).toContainText('RT1')
  assert.ok(requests.some((r) => r.path === '/api/admin/report-templates' && r.params.page === '3'))
  await expect(confirm).toContainText('RT2')
  await confirm.getByRole('button', { name: '返回检查', exact: true }).click()
  await goto('/admin/org?userId=U12')
  const dialog = page.locator('.el-dialog:visible')
  await expect(dialog).toContainText('编辑用户')
  await expect(dialog.locator('input').first()).toHaveValue('user12')
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  await expect(visiblePane().getByText('user12', { exact: true })).toBeVisible()
  await goto('/admin/org?orgId=O1')
  await expect(dialog).toContainText('编辑组织')
  await expect(dialog.locator('input').first()).toHaveValue('测试组织')
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  console.log('PASS: report replacement confirmation and user/org deep links')

  await goto('/admin/material-review-points')
  await visiblePane()
    .locator('.el-table__row')
    .filter({ hasText: '检查签名' })
    .getByRole('button', { name: '删除', exact: true })
    .click()
  await confirm.getByRole('button', { name: '删除', exact: true }).click()
  await expect(page.locator('.error-stack')).toContainText('模拟删除冲突')
  await expect(page.locator('.el-drawer:visible')).toHaveCount(0)
  await goto('/admin/fine-config')
  await visiblePane()
    .locator('.el-table__row')
    .filter({ hasText: 'signature' })
    .getByRole('button', { name: '编辑', exact: true })
    .click()
  await expect(drawer.locator('.el-input-number').last().locator('input')).toHaveValue(
    /^0(?:\.0+)?$/
  )
  await drawer.getByRole('button', { name: '保存配置', exact: true }).click()
  await expect
    .poll(() =>
      mutations.some(
        (m) =>
          m.path.includes('/config-items/field-mapping/FM1') &&
          m.body?.values?.confidenceThreshold === 0
      )
    )
    .toBe(true)
  await expect(page.locator('.el-dialog:visible')).toContainText('配置差异')
  await page.locator('.el-dialog:visible').getByRole('button', { name: /Close/ }).click()
  await expect(page.locator('.el-dialog:visible')).toHaveCount(0)
  await goto('/admin/rules')
  await page.getByRole('button', { name: '登记配置版本', exact: true }).click()
  await expect(confirm).toContainText('业务规则')
  await expect(confirm).toContainText('不切换规则、Prompt 或报告模板')
  await confirm.getByRole('textbox').fill('回归验证')
  await confirm.getByRole('button', { name: '生成影响预览', exact: true }).click()
  const recordConfirm = confirm.filter({ hasText: '确认配置版本登记' })
  await expect(recordConfirm).toContainText('业务规则：1 项')
  await expect(recordConfirm).toContainText('不自动切换生产版本或发送消息')
  await recordConfirm.getByRole('button', { name: '返回检查', exact: true }).click()
  await expect(confirm).toHaveCount(0)
  assert.equal(mutations.filter((m) => m.path === '/api/admin/config-overview/publish').length, 0)
  console.log('PASS: list deletion errors, zero confidence and accurate registration scope')
  mkdirSync('/tmp/aicheck-admin-ui', { recursive: true })
  await page.screenshot({ path: '/tmp/aicheck-admin-ui/rules.png', fullPage: true })
  assert.deepEqual(errors, [])
  console.log('All admin usability browser checks passed; no browser errors.')
} catch (error) {
  mkdirSync('/tmp/aicheck-admin-ui', { recursive: true })
  await page.screenshot({ path: '/tmp/aicheck-admin-ui/failure.png', fullPage: true })
  console.error('Browser errors:', errors)
  throw error
} finally {
  await browser.close()
}
