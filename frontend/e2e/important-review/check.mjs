import { chromium, expect } from '@playwright/test'
import { mkdirSync } from 'node:fs'
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } })
page.setDefaultTimeout(20000)
const errors = [],
  starts = [],
  uploads = []
page.on('pageerror', (e) => errors.push(String(e)))
const names = [
  '设计文件批准程序',
  '施工图审查手续',
  '计算书审批',
  '设计变更批准',
  '标准版本',
  '检测与试验要求',
  '制造单位许可',
  '监检与型式试验',
  '产品质量证明',
  '焊工资格及作业覆盖',
  '焊接工艺文件',
  '焊材质量证明'
]
const ids = [4, 5, 6, 7, 8, 9, 12, 13, 16, 24, 25, 26]
const rules = ids.map((nodeId, i) => ({
  nodeId,
  code: `R${String(nodeId).padStart(2, '0')}`,
  name: names[i],
  group: nodeId < 10 ? '设计文件' : nodeId < 20 ? '元件与材料' : '焊接',
  version: 'frozen-test-version-20260922',
  source: '业务节点描述 v3',
  sections: [
    { title: '方法', text: '核对证书与作业记录；缺少施焊日期不得默认通过。' },
    { title: '判断准则', text: '适用标准与版本须有原文依据。' }
  ]
}))
const docs = Array.from({ length: 11 }, (_, i) => ({
  id: `D${i}`,
  projectId: 'P-IMPORTANT-TEST',
  currentVersionId: `V${i}`,
  fileName: i === 0 ? '焊工资格证.pdf' : i === 10 ? '综合资料.pdf' : `工程文件${i}.pdf`,
  currentOcrStatus: '已识别',
  bodyUploaded: true
}))
let result = []
await page.route('http://127.0.0.1:4407/api/**', async (route) => {
  const url = new URL(route.request().url()),
    path = url.pathname
  let data = {}
  if (path.endsWith('/documents/upload-session')) {
    uploads.push(route.request().postDataJSON())
    if (!route.request().headers()['idempotency-key'])
      throw new Error('Missing upload idempotency key')
    data = {
      uploadSessionId: 'U1',
      uploadUrls: [{ url: '/api/test-upload', method: 'PUT', documentVersionId: 'VU1' }]
    }
  } else if (path === '/api/test-upload') {
    if (route.request().method() !== 'PUT' || !route.request().postDataBuffer()?.length)
      throw new Error('Missing upload body')
    uploads.push('body')
  } else if (path.endsWith('/upload-session/U1/complete')) {
    uploads.push(route.request().postDataJSON())
    data = { completionWarnings: [] }
  } else if (path.endsWith('/important-review'))
    data = { nodes: rules, enabled: true, disabledReason: '' }
  else if (path.endsWith('/documents')) {
    const p = Number(url.searchParams.get('page') || 1)
    data = {
      items: path.includes('P-OTHER') ? [] : docs.slice((p - 1) * 10, p * 10),
      total: path.includes('P-OTHER') ? 0 : 11
    }
  } else if (path.endsWith('/analyze'))
    data = {
      nodes: ids.map((nodeId) => ({
        nodeId,
        recommended: nodeId === 24,
        documents:
          nodeId === 24
            ? [
                {
                  documentId: 'D0',
                  versionId: 'V0',
                  fileName: docs[0].fileName,
                  reason: '包含焊工资格'
                }
              ]
            : [],
        message: nodeId === 24 ? '已找到候选资料，完整性需审查确认' : '适用性待确认，可手动选择'
      }))
    }
  else if (path.includes('/nodes/24/runs')) {
    starts.push(route.request().postDataJSON())
    data = { runId: 'A1' }
    result = [
      {
        id: 'A1',
        nodeId: 24,
        reviewRunId: 'R1',
        status: 'waiting_human_review',
        startedAt: '2026-09-22 10:00:00',
        documents: [
          { documentId: 'D0', versionId: 'V0', fileName: docs[0].fileName },
          { documentId: 'D10', versionId: 'V10', fileName: docs[10].fileName }
        ],
        documentsChanged: false,
        rule: rules.find((r) => r.nodeId === 24),
        atomicCheckOutcomes: [
          {
            atomicCheckId: 'AC-R24-01',
            name: '证书身份核对',
            result: 'passed',
            checks: [{ code: 'all_values_equal', actual: '示例焊工', expected: '示例焊工' }],
            facts: [
              {
                label: '证书',
                evidence: [
                  { documentId: 'D0', documentVersionId: 'V0', pageNo: 1, quotedText: '测试原文' }
                ]
              }
            ]
          },
          {
            atomicCheckId: 'AC-R24-02',
            name: '有效期覆盖施焊日期',
            result: 'evidence_insufficient',
            reason: 'periodStart_and_periodEnd_missing',
            checks: [],
            facts: []
          }
        ],
        findingDrafts: []
      }
    ]
  } else if (path.endsWith('/important-review/runs'))
    data = { items: path.includes('P-OTHER') ? [] : result }
  else if (path.endsWith('/original')) {
    await route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ code: 404, message: '测试原文不可用' })
    })
    return
  } else if (path.endsWith('/documents/D0'))
    data = {
      document: docs[0],
      versions: [],
      preview: {
        url: '/api/projects/P-IMPORTANT-TEST/documents/D0/original?versionId=V0',
        previewType: 'pdf'
      }
    }
  else throw new Error(`Unexpected API ${path}`)
  await route.fulfill({ json: { code: 0, data, message: 'ok' } })
})
try {
  await page.goto('http://127.0.0.1:4407/e2e/important-review/index.html')
  await expect(page.getByRole('heading', { name: '工程资料', exact: true })).toBeVisible()
  await page
    .locator('input[type=file]')
    .setInputFiles({
      name: '监检补充资料.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('%PDF-1.4 test upload')
    })
  await expect(page.getByText('资料已上传，解析完成后可用于审查。')).toBeVisible()
  if (
    uploads.length !== 3 ||
    uploads[0].files[0].fileName !== '监检补充资料.pdf' ||
    uploads[2].completedFiles[0].documentVersionId !== 'VU1'
  )
    throw new Error('Upload lifecycle incomplete')
  await page
    .getByRole('checkbox', { name: '选择 焊工资格证.pdf', exact: true })
    .locator('..')
    .click()
  await page.locator('.btn-next').click()
  await page.getByRole('checkbox', { name: '选择 综合资料.pdf', exact: true }).locator('..').click()
  await expect(page.getByText('已选 2 份', { exact: false })).toBeVisible()
  await page.getByRole('button', { name: '分析适用节点', exact: true }).click()
  await expect(page.getByRole('checkbox', { name: '选择 R24', exact: true })).toBeChecked()
  await expect(page.getByRole('checkbox', { name: '选择 R13', exact: true })).not.toBeChecked()
  const node = page.locator('.node-row').filter({ hasText: 'R24' })
  await node.getByRole('button', { name: '审查规则', exact: true }).click()
  await expect(page.getByText('核对证书与作业记录；缺少施焊日期不得默认通过。')).toBeVisible()
  mkdirSync('../output/important-review', { recursive: true })
  await page.waitForTimeout(400)
  await page.screenshot({ path: '../output/important-review/rules.png', fullPage: true })
  await page.locator('.el-drawer__close-btn:visible').click()
  await page.getByRole('button', { name: /开始审查（已选 1 个节点，2 份文件）/ }).click()
  await expect(page.getByText('有效期覆盖施焊日期', { exact: true })).toBeVisible()
  await expect(page.getByText('证据不足', { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('button', { name: '展开资料', exact: true })).toBeVisible()
  if (JSON.stringify(starts) !== JSON.stringify([{ inputDocumentVersionIds: ['V0', 'V10'] }]))
    throw new Error('Selection scope changed')
  await page.waitForTimeout(400)
  await page.screenshot({ path: '../output/important-review/results.png', fullPage: true })
  await page
    .locator('.important-outcomes')
    .getByRole('button', { name: '焊工资格证.pdf · 第 1 页' })
    .click()
  await expect(page.getByText('对应核查项：证书身份核对')).toBeVisible()
  await page.locator('.el-drawer__close-btn:visible').click()
  await page.getByRole('button', { name: '展开资料', exact: true }).click()
  await page.getByRole('button', { name: '切换工作台视图' }).click()
  await page.getByRole('button', { name: '切换工作台视图' }).click()
  await expect(page.getByText('已选 2 份', { exact: false })).toBeVisible()
  await page.getByRole('button', { name: '切换测试工程' }).click()
  await expect(page.getByText('已选 0 份', { exact: false })).toBeVisible()
  await expect(page.getByText('尚未开始审查，请先选择资料并确认审查范围')).toBeVisible()
  if (errors.length) throw new Error(errors.join('\n'))
  console.log(
    'PASS: upload lifecycle, unbound cross-page selection, rules, run scope, results, evidence, view preservation, project reset'
  )
} catch (error) {
  console.error(errors)
  await page.screenshot({ path: '../output/important-review/failure.png', fullPage: true })
  throw error
} finally {
  await browser.close()
}
