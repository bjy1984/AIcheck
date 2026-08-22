import {
  expect,
  test,
  type APIResponse,
  type Locator,
  type Page,
  type TestInfo
} from '@playwright/test'
import { createHash, randomUUID } from 'node:crypto'
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { basename, extname, relative, resolve, sep } from 'node:path'
import {
  isExactNodePackageResponse,
  isIgnoredFixtureMetadata
} from './projectRegistrationUploadReviewHelpers'

type ApiEnvelope<T> = {
  code: number
  message?: string
  data: T
  operationId?: string
}

type ProjectFile = {
  id: string
  fileName: string
  sourceOrgName?: string
  currentOcrStatus?: string
  sliceStatus?: string
  vectorStatus?: string
  bodyUploaded?: boolean
  materialTypeCode?: string
  materialTypeName?: string
  bindings?: Array<{ id: string; nodeId: number; bindingStatus: string }>
}

type NodePackage = {
  projectFiles: ProjectFile[]
  businessBasis?: {
    ruleId?: string
    ruleVersion?: string
    referencedStandards?: unknown[]
  }
  evidenceReadiness?: {
    pendingCount?: number
    missingCount?: number
    readyForAi?: boolean
    readyForAiFormal?: boolean
    blockingReasons?: unknown[]
  }
  nodeEvidenceLinks?: Array<{
    id: string
    manualStatus?: string
    fileName?: string
    reviewPointId?: string
  }>
  aiRuns?: Array<{
    id: string
    status: string
    reviewRunId?: string
    ruleVersion?: string
    evidenceLinks?: Array<{ id: string; clauseNo?: string; standardRef?: string }>
    suggestion?: {
      result?: string
      confidence?: number
    }
  }>
  reviewTimeline?: Array<{ actor: string; conclusion?: string; summary?: string; refId?: string }>
}

type AcceptanceSummary = {
  projectId: string
  projectName: string
  buildSha: string
  databaseSchema: string
  linkIssuers: string[]
  registeredRoles: string[]
  contractorFileCount: number
  ndtFileCount: number
  isolation: {
    contractorVisibleDocumentIds: string[]
    ndtVisibleDocumentIds: string[]
    ownerUploadControls: number
    directResourceProbes: AuthorizationProbe[]
    anonymousManagementProbes: AuthorizationProbe[]
  }
  readiness: {
    ocr: number
    sliced: number
    vectorized: number
    total: number
  }
  ai: {
    runId: string
    reviewRunId?: string
    result: string
    confidence?: number
    evidenceLinkIds: string[]
    ruleReferences: unknown[]
  }
  screenshots: string[]
  openRequiredGateCount: number
  openP0P1Defects: number
  defectInventorySource: string
  defectInventory: DefectRecord[]
  gateResults: GateResult[]
}

type AuthorizationProbe = {
  actor: string
  endpoint: string
  documentId?: string
  status: number
  businessCode?: number
  reason?: string
}

type GateResult = {
  id: string
  severity: 'P0' | 'P1'
  status: 'passed' | 'open'
  evidence: string
}

type DefectRecord = {
  id: string
  gateId: string
  severity: 'P0' | 'P1'
  status: 'open'
  message: string
  caughtAt: string
}

const requiredReleaseGates: Array<Pick<GateResult, 'id' | 'severity'>> = [
  { id: 'P0-target-isolation', severity: 'P0' },
  { id: 'P0-registration-cross-approval', severity: 'P0' },
  { id: 'P0-approved-member-project-access', severity: 'P0' },
  { id: 'P0-cross-organization-document-isolation', severity: 'P0' },
  { id: 'P1-project-package-binding', severity: 'P1' },
  { id: 'P1-contractor-fifteen-file-batch', severity: 'P1' },
  { id: 'P1-ndt-eight-file-bindings', severity: 'P1' },
  { id: 'P1-owner-upload-denial', severity: 'P1' },
  { id: 'P1-processing-readiness-and-submission', severity: 'P1' },
  { id: 'P1-evidence-confirmation', severity: 'P1' },
  { id: 'P1-formal-ai-result-agreement', severity: 'P1' }
]

const contractorRelativeFiles = [
  '0、地上甲类储罐区2（含泵区）管道目录/0、地上甲类储罐区2（含泵区）管道目录.doc',
  '1、设计、安装资质证书/广东政和设计院压力管道设计资质.png',
  '1、设计、安装资质证书/江苏三江压力管道资质.jpg',
  '2、质量手册/质量手册.pdf',
  '3、告知书、回执单/告知回执.png',
  '3、告知书、回执单/罐区告知书2026-4-27.png',
  '4、监检合同/压力管道施工监检合同.pdf',
  '5、施工方案/珠海海瑞德泵区施工方案2026-04-30.doc',
  '6、会审记录、图纸/会审记录.png',
  '6、会审记录、图纸/地上甲类储罐区2（含泵区）施工图.pdf',
  '7、管道元件及材料验收材料报审/0常用管道元件核查记录-施工单位填写.doc',
  '7、管道元件及材料验收材料报审/管道元件及材料验收材料报审.pdf',
  '8、焊接工艺评定/不锈钢氩弧焊HP022-2024焊接工艺评定.pdf',
  '9、焊工资质核查/李卫伍社保缴纳证明.pdf',
  '9、焊工资质核查/焊工清单.docx'
]

const ndtUploadGroupDefinitions = [
  {
    material: '无损检测机构核准证',
    files: ['10、无损检测委托单位资质/1、机构资质证书/公司资质202407 - 副本.pdf'],
    expectedNodes: [35]
  },
  {
    material: '无损检测人员资格证',
    files: [
      '10、无损检测委托单位资质/2、无损检测人员资质和执业注册证/李国平(1).pdf',
      '10、无损检测委托单位资质/2、无损检测人员资质和执业注册证/李国平RT注册证.jpg',
      '10、无损检测委托单位资质/2、无损检测人员资质和执业注册证/段杰RT证.jpg',
      '10、无损检测委托单位资质/2、无损检测人员资质和执业注册证/段杰注册证.pdf',
      '10、无损检测委托单位资质/2、无损检测人员资质和执业注册证/汪仲冬RT检测证.jpg',
      '10、无损检测委托单位资质/2、无损检测人员资质和执业注册证/汪仲冬执业注册证书(1).pdf'
    ],
    expectedNodes: [38]
  },
  {
    material: '无损检测方案',
    files: ['10、无损检测委托单位资质/3.检测方案/射线检测施工方案(1).pdf'],
    expectedNodes: [36, 38]
  }
]

const ndtRuleNames: Record<number, string> = {
  35: '无损检测机构施工现场质量保证体系的实施',
  36: '无损检测方案',
  38: '无损检测人员资格证、执业注册证及持证合格项目'
}

const requiredEnvironment = {
  adminUsername: process.env.AICHECK_E2E_ADMIN_USERNAME || '',
  adminPassword: process.env.AICHECK_E2E_ADMIN_PASSWORD || '',
  leaderUsername: process.env.AICHECK_E2E_LEADER_USERNAME || '',
  leaderPassword: process.env.AICHECK_E2E_LEADER_PASSWORD || '',
  leaderMemberLabel: process.env.AICHECK_E2E_LEADER_MEMBER_LABEL || '',
  fixtureRoot: process.env.AICHECK_E2E_FIXTURE_ROOT || '',
  testPostgresUrl: process.env.AICHECK_TEST_POSTGRES_URL || '',
  buildVersion: process.env.AICHECK_E2E_BUILD_VERSION || '',
  runMarker: process.env.AICHECK_E2E_RUN_MARKER || '',
  buildSha:
    process.env.AICHECK_E2E_BUILD_SHA || process.env.GITHUB_SHA || process.env.CI_COMMIT_SHA || ''
}

const requiredEnvironmentNames: Record<keyof typeof requiredEnvironment, string> = {
  adminUsername: 'AICHECK_E2E_ADMIN_USERNAME',
  adminPassword: 'AICHECK_E2E_ADMIN_PASSWORD',
  leaderUsername: 'AICHECK_E2E_LEADER_USERNAME',
  leaderPassword: 'AICHECK_E2E_LEADER_PASSWORD',
  leaderMemberLabel: 'AICHECK_E2E_LEADER_MEMBER_LABEL',
  fixtureRoot: 'AICHECK_E2E_FIXTURE_ROOT',
  testPostgresUrl: 'AICHECK_TEST_POSTGRES_URL',
  buildVersion: 'AICHECK_E2E_BUILD_VERSION',
  runMarker: 'AICHECK_E2E_RUN_MARKER',
  buildSha: 'AICHECK_E2E_BUILD_SHA (or GITHUB_SHA/CI_COMMIT_SHA)'
}

const missingEnvironment = Object.entries(requiredEnvironment)
  .filter(([, value]) => !value)
  .map(([key]) => requiredEnvironmentNames[key as keyof typeof requiredEnvironment])

if (missingEnvironment.length) {
  throw new Error(
    `Formal E2E collection failed: missing required environment values: ${missingEnvironment.join(', ')}`
  )
}

const fixtureRoot = resolve(requiredEnvironment.fixtureRoot)
const expectedFixtureRelativePaths = [
  ...contractorRelativeFiles,
  ...ndtUploadGroupDefinitions.flatMap((group) => group.files)
]
const allowedFixtureExtensions = new Set(['.pdf', '.doc', '.docx', '.png', '.jpg', '.jpeg'])

const collectFixtureRelativePaths = (root: string, directory = root): string[] =>
  readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(directory, entry.name)
    if (entry.isDirectory()) return collectFixtureRelativePaths(root, path)
    if (!entry.isFile()) return []
    const relativePath = relative(root, path).split(sep).join('/')
    return isIgnoredFixtureMetadata(relativePath) ? [] : [relativePath]
  })

if (!existsSync(fixtureRoot) || !statSync(fixtureRoot).isDirectory()) {
  throw new Error(
    `Formal E2E collection failed: AICHECK_E2E_FIXTURE_ROOT is not an existing directory: ${fixtureRoot}`
  )
}
const actualFixtureRelativePaths = collectFixtureRelativePaths(fixtureRoot).sort()
const expectedSortedFixturePaths = [...expectedFixtureRelativePaths].sort()
if (
  actualFixtureRelativePaths.length !== 23 ||
  JSON.stringify(actualFixtureRelativePaths) !== JSON.stringify(expectedSortedFixturePaths)
) {
  const missing = expectedSortedFixturePaths.filter(
    (path) => !actualFixtureRelativePaths.includes(path)
  )
  const unexpected = actualFixtureRelativePaths.filter(
    (path) => !expectedSortedFixturePaths.includes(path)
  )
  throw new Error(
    `Formal E2E fixture validation failed: expected exactly 23 declared files. missing=${JSON.stringify(missing)}, unexpected=${JSON.stringify(unexpected)}`
  )
}

const fixtureManifest = expectedFixtureRelativePaths.map((relativePath) => {
  const path = resolve(fixtureRoot, relativePath)
  const extension = extname(relativePath).toLowerCase()
  const size = statSync(path).size
  if (!allowedFixtureExtensions.has(extension)) {
    throw new Error(`Formal E2E fixture validation failed: unsupported format ${relativePath}`)
  }
  if (size <= 0) {
    throw new Error(`Formal E2E fixture validation failed: empty file ${relativePath}`)
  }
  return {
    relativePath,
    size,
    sha256: createHash('sha256').update(readFileSync(path)).digest('hex')
  }
})

const checksumManifestPath = String(process.env.AICHECK_E2E_FIXTURE_CHECKSUM_MANIFEST || '').trim()
if (checksumManifestPath) {
  const pinned = JSON.parse(readFileSync(resolve(checksumManifestPath), 'utf8')) as Record<
    string,
    string
  >
  for (const fixture of fixtureManifest) {
    if (pinned[fixture.relativePath] !== fixture.sha256) {
      throw new Error(
        `Formal E2E fixture checksum mismatch: ${fixture.relativePath}; expected=${String(pinned[fixture.relativePath] || 'missing')}, actual=${fixture.sha256}`
      )
    }
  }
  if (Object.keys(pinned).sort().join('\n') !== expectedSortedFixturePaths.join('\n')) {
    throw new Error(
      'Formal E2E checksum manifest must contain exactly the 23 declared relative paths.'
    )
  }
}

const contractorFiles = contractorRelativeFiles.map((path) => resolve(fixtureRoot, path))
const ndtUploadGroups = ndtUploadGroupDefinitions.map((group) => ({
  ...group,
  files: group.files.map((path) => resolve(fixtureRoot, path))
}))
const ndtFiles = ndtUploadGroups.flatMap((group) => group.files)

const isolatedSchemaFromDsn = (dsn: string) => {
  if (!dsn) return ''
  let parsed: URL
  try {
    parsed = new URL(dsn)
  } catch {
    throw new Error('AICHECK_TEST_POSTGRES_URL is not a valid PostgreSQL URL.')
  }
  if (!['postgres:', 'postgresql:'].includes(parsed.protocol)) {
    throw new Error('AICHECK_TEST_POSTGRES_URL must use postgres:// or postgresql://.')
  }
  const options = decodeURIComponent(parsed.searchParams.get('options') || '')
  const match = options.match(/(?:^|\s)-c\s*search_path=([^\s]+)/)
  const schema = String(match?.[1] || '').split(',')[0]
  if (!/^aicheck_test_[A-Za-z0-9_]+$/.test(schema)) {
    throw new Error(
      'Unsafe E2E database DSN: AICHECK_TEST_POSTGRES_URL must set options=-c search_path=aicheck_test_<run>,public.'
    )
  }
  return schema
}

const normalizedDatabaseFromDsn = (dsn: string) => {
  const parsed = new URL(dsn)
  const database = decodeURIComponent(parsed.pathname.replace(/^\//, '')).trim().toLowerCase()
  if (!database) throw new Error('AICHECK_TEST_POSTGRES_URL must include a database name.')
  return database
}

const formItem = (container: Locator, label: string) =>
  container.locator('.el-form-item').filter({ hasText: label }).first()

const chooseSelectOption = async (page: Page, select: Locator, label?: string) => {
  await select.click()
  const dropdown = page.locator('.el-select-dropdown:visible').last()
  const option = label
    ? dropdown.locator('.el-select-dropdown__item').filter({ hasText: label }).first()
    : dropdown.locator('.el-select-dropdown__item:not(.is-disabled)').first()
  await expect(
    option,
    label ? `select option ${label}` : 'first enabled select option'
  ).toBeVisible()
  await option.click()
  await expect(dropdown).toBeHidden()
}

const apiJson = async <T>(response: APIResponse | import('@playwright/test').Response) => {
  const payload = (await response.json()) as ApiEnvelope<T>
  expect(
    payload.code,
    payload.message || `operation ${payload.operationId || 'unknown'} failed`
  ).toBe(0)
  return payload.data
}

const browserSessionProbe = async (
  page: Page,
  actor: string,
  endpoint: string,
  documentId?: string
): Promise<AuthorizationProbe> =>
  page.evaluate(
    async ({ actorName, path, targetDocumentId }) => {
      const storedValues = Array.from({ length: sessionStorage.length }, (_, index) =>
        sessionStorage.getItem(sessionStorage.key(index) || '')
      )
      const parsedValues = storedValues.flatMap((value) => {
        if (!value) return []
        try {
          return [JSON.parse(value) as Record<string, unknown>]
        } catch {
          return []
        }
      })
      const authState = parsedValues.find((value) => typeof value.token === 'string')
      const token = String(authState?.token || '')
      const tokenKey = String(authState?.tokenKey || 'Authorization')
      const userInfo = (authState?.userInfo || {}) as { role?: string; id?: string }
      if (!token) throw new Error(`No persisted browser session token found for ${actorName}.`)
      const response = await fetch(path, {
        method: 'GET',
        credentials: 'same-origin',
        headers: {
          [tokenKey]: token,
          'X-Role': String(userInfo.role || ''),
          'X-User-Id': String(userInfo.id || '')
        }
      })
      const contentType = response.headers.get('content-type') || ''
      const payload = contentType.includes('json')
        ? ((await response.json()) as { code?: number; data?: { reason?: string } })
        : undefined
      return {
        actor: actorName,
        endpoint: path,
        documentId: targetDocumentId,
        status: response.status,
        businessCode: payload?.code,
        reason: payload?.data?.reason
      }
    },
    { actorName: actor, path: endpoint, targetDocumentId: documentId }
  )

const browserAnonymousProbe = async (
  page: Page,
  endpoint: string,
  method: 'GET' | 'POST'
): Promise<AuthorizationProbe> =>
  page.evaluate(
    async ({ path, requestMethod }) => {
      const response = await fetch(path, {
        method: requestMethod,
        credentials: 'omit',
        headers: requestMethod === 'POST' ? { 'Content-Type': 'application/json' } : undefined,
        body: requestMethod === 'POST' ? '{}' : undefined
      })
      const payload = (await response.json().catch(() => ({}))) as {
        code?: number
        data?: { reason?: string }
      }
      return {
        actor: 'anonymous',
        endpoint: path,
        status: response.status,
        businessCode: payload.code,
        reason: payload.data?.reason
      }
    },
    { path: endpoint, requestMethod: method }
  )

const expectDeniedProbe = (probe: AuthorizationProbe) => {
  expect([403, 404], `${probe.actor} ${probe.endpoint} must be denied`).toContain(probe.status)
  expect(
    probe.businessCode,
    `${probe.actor} ${probe.endpoint} must return a business denial`
  ).not.toBe(0)
}

const probeForeignDocument = async (
  page: Page,
  actor: string,
  projectId: string,
  documentId: string
) => {
  const base = `/api/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(documentId)}`
  const endpoints = [
    base,
    `${base}/preview-url`,
    `${base}/download-url`,
    `${base}/original?disposition=inline`,
    `${base}/office-preview`
  ]
  const results: AuthorizationProbe[] = []
  for (const endpoint of endpoints) {
    const result = await browserSessionProbe(page, actor, endpoint, documentId)
    expectDeniedProbe(result)
    results.push(result)
  }
  return results
}

const login = async (
  page: Page,
  username: string,
  password: string,
  expectedPath: string,
  shouldSucceed = true
) => {
  await page.context().clearCookies()
  await page.goto('/#/login', { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => {
    localStorage.clear()
    sessionStorage.clear()
  })
  await page.reload({ waitUntil: 'domcontentloaded' })
  const inputs = page.locator('.auth-form .el-input__inner')
  await expect(inputs.first()).toBeVisible()
  await inputs.nth(0).fill(username)
  await inputs.nth(1).fill(password)
  const loginResponse = page.waitForResponse(
    (response) =>
      response.url().includes('/api/auth/login') && response.request().method() === 'POST'
  )
  await page.getByRole('button', { name: /^登录$/ }).click()
  const response = await loginResponse
  if (!shouldSucceed) {
    expect(response.status()).toBeGreaterThanOrEqual(400)
    await expect(page).toHaveURL(/#\/login/)
    await expect(page.locator('.auth-form')).toContainText(/登录失败|用户名|密码|口令|审核/)
    return
  }
  expect(response.ok()).toBeTruthy()
  await page.waitForURL((url) => url.hash.includes(expectedPath))
  await page.waitForLoadState('networkidle').catch(() => {})
}

const selectProject = async (page: Page, projectName: string) => {
  const select = page.getByLabel('当前项目')
  await expect(select).toBeVisible()
  await chooseSelectOption(page, select, projectName)
  await expect(select).toContainText(projectName)
  await page.waitForLoadState('networkidle').catch(() => {})
}

const submitAnonymousApplication = async (
  page: Page,
  link: string,
  applicant: { username: string; displayName: string; roleLabel: string; password: string }
) => {
  await page.context().clearCookies()
  await page.goto(link, { waitUntil: 'domcontentloaded' })
  const card = page.locator('.registration-card')
  await expect(card).toContainText('加入项目')
  await formItem(card, '用户名').locator('input').fill(applicant.username)
  await formItem(card, '姓名').locator('input').fill(applicant.displayName)
  await chooseSelectOption(
    page,
    formItem(card, '我的角色').locator('.el-select'),
    applicant.roleLabel
  )
  await formItem(card, '设置口令').locator('input').fill(applicant.password)
  await formItem(card, '确认口令').locator('input').fill(applicant.password)
  const applicationResponse = page.waitForResponse(
    (response) =>
      response.url().includes('/registration-links/') &&
      response.url().endsWith('/apply') &&
      response.request().method() === 'POST'
  )
  await card.getByRole('button', { name: '提交申请' }).click()
  expect((await applicationResponse).ok()).toBeTruthy()
  await expect(card).toContainText('已提交，等待项目负责人审核')
}

const reviewApplicants = async (page: Page, usernames: string[]) => {
  const panel = page.locator('.project-registration:visible')
  for (const username of usernames) {
    const row = panel.locator('.el-table__row').filter({ hasText: username }).first()
    await expect(row, `pending registration row for ${username}`).toBeVisible()
    const responsePromise = page.waitForResponse(
      (response) =>
        response.url().includes('/registration-requests/') &&
        response.url().endsWith('/review') &&
        response.request().method() === 'POST'
    )
    await row.getByRole('button', { name: '通过', exact: true }).click()
    expect((await responsePromise).ok()).toBeTruthy()
    await expect(
      panel.locator('.el-table__row').filter({ hasText: username }).first()
    ).toContainText('已通过')
  }
}

const screenshotEvidence = async (page: Page, testInfo: TestInfo, name: string) => {
  const path = testInfo.outputPath(`${name}.png`)
  await page.screenshot({ path, fullPage: true })
  await testInfo.attach(name, { path, contentType: 'image/png' })
}

const captureNodePackageOnReload = async (page: Page, projectId: string, nodeId: number) => {
  const responsePromise = page.waitForResponse(
    (response) =>
      isExactNodePackageResponse(response.url(), projectId, nodeId) &&
      response.request().method() === 'GET' &&
      response.status() === 200
  )
  await page.reload({ waitUntil: 'domcontentloaded' })
  return apiJson<NodePackage>(await responsePromise)
}

/** Project files are identical across node-package payloads for the current actor.
 * Use only for project-wide file totals/isolation where node-specific rule/readiness data is irrelevant. */
const captureAnyNodeProjectFilesOnReload = async (page: Page, projectId: string) => {
  const prefix = `/api/projects/${encodeURIComponent(projectId)}/nodes/`
  const responsePromise = page.waitForResponse((response) => {
    const pathname = new URL(response.url()).pathname
    const suffix = pathname.startsWith(prefix) ? pathname.slice(prefix.length) : ''
    return (
      /^\d+\/package$/.test(suffix) &&
      response.request().method() === 'GET' &&
      response.status() === 200
    )
  })
  await page.reload({ waitUntil: 'domcontentloaded' })
  return apiJson<NodePackage>(await responsePromise)
}

const filesAreReady = (files: ProjectFile[]) =>
  files.every(
    (file) =>
      file.bodyUploaded !== false &&
      ['已识别', '人工修正', '抽取不完整'].includes(String(file.currentOcrStatus || '')) &&
      file.sliceStatus === '已切片' &&
      file.vectorStatus === '已向量化'
  )

const waitForFilesReadyThroughBrowser = async (
  page: Page,
  projectId: string,
  nodeId: number,
  expectedIds: Set<string>,
  timeoutMs = 20 * 60_000
) => {
  const deadline = Date.now() + timeoutMs
  let latest: NodePackage | undefined
  while (Date.now() < deadline) {
    latest = await captureNodePackageOnReload(page, projectId, nodeId)
    const files = latest.projectFiles.filter((file) => expectedIds.has(file.id))
    if (files.length === expectedIds.size && filesAreReady(files)) return latest
    await page.waitForTimeout(5_000)
  }
  const state = (latest?.projectFiles || [])
    .filter((file) => expectedIds.has(file.id))
    .map((file) => ({
      fileName: file.fileName,
      bodyUploaded: file.bodyUploaded,
      ocr: file.currentOcrStatus,
      slice: file.sliceStatus,
      vector: file.vectorStatus
    }))
  throw new Error(`Timed out waiting for OCR/slice/vector readiness: ${JSON.stringify(state)}`)
}

test.describe('project registration, upload isolation, and formal review release gate', () => {
  test.describe.configure({ mode: 'serial' })

  test('runs the complete business path in a real browser without API mutations', async ({
    page,
    request
  }, testInfo) => {
    test.setTimeout(45 * 60_000)

    const passedGateEvidence = new Map<string, string>()
    const defectInventory: DefectRecord[] = []
    const passGate = (id: string, evidence: string) => {
      expect(
        requiredReleaseGates.some((gate) => gate.id === id),
        `unknown release gate ${id}`
      ).toBe(true)
      passedGateEvidence.set(id, evidence)
    }
    const gateStep = async <T>(
      title: string,
      gateIds: string[],
      action: () => Promise<T>
    ): Promise<T> =>
      test.step(title, async () => {
        try {
          return await action()
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error)
          for (const gateId of gateIds) {
            const definition = requiredReleaseGates.find((gate) => gate.id === gateId)
            if (!definition || defectInventory.some((defect) => defect.gateId === gateId)) continue
            defectInventory.push({
              id: `DEF-${gateId}-${defectInventory.length + 1}`,
              gateId,
              severity: definition.severity,
              status: 'open',
              message,
              caughtAt: new Date().toISOString()
            })
          }
          await testInfo.attach('defect-inventory.json', {
            body: Buffer.from(JSON.stringify(defectInventory, null, 2)),
            contentType: 'application/json'
          })
          throw error
        }
      })
    const directResourceProbes: AuthorizationProbe[] = []
    const anonymousManagementProbes: AuthorizationProbe[] = []
    let ownerUploadControls = -1
    let contractorVisibleDocumentIds: string[] = []
    let ndtVisibleDocumentIds: string[] = []

    const databaseSchema = isolatedSchemaFromDsn(requiredEnvironment.testPostgresUrl)
    const expectedDatabase = normalizedDatabaseFromDsn(requiredEnvironment.testPostgresUrl)
    expect(contractorFiles).toHaveLength(15)
    expect(ndtFiles).toHaveLength(8)
    await testInfo.attach('fixture-sha256-manifest.json', {
      body: Buffer.from(
        JSON.stringify(
          {
            schemaVersion: 'aicheck.e2e-fixtures.v1',
            fileCount: fixtureManifest.length,
            checksumManifestPinned: Boolean(checksumManifestPath),
            files: fixtureManifest
          },
          null,
          2
        )
      ),
      contentType: 'application/json'
    })

    await gateStep(
      'preflight non-production target, release identity, and dependencies',
      ['P0-target-isolation'],
      async () => {
        const target = new URL(String(testInfo.project.use.baseURL || 'http://127.0.0.1:4000'))
        const hostname = target.hostname.toLowerCase().replace(/^\[|\]$/g, '')
        const localTarget = ['localhost', '127.0.0.1', '::1', '0.0.0.0'].includes(hostname)
        if (!localTarget && process.env.AICHECK_E2E_ALLOW_EXTERNAL_NON_PRODUCTION !== 'true') {
          throw new Error(
            `External E2E target ${target.origin} is blocked. Set AICHECK_E2E_ALLOW_EXTERNAL_NON_PRODUCTION=true only after verifying it is non-production.`
          )
        }

        type RuntimeContext = {
          environment: string
          strictProduction: boolean
          demoDataAllowed: boolean
          buildVersion: string
          release: { gitSha: string; releaseId: string }
          databaseScope?: {
            engine?: string
            database?: string
            schema?: string
            runMarker?: string
            participants?: Record<
              'api' | 'processingWorker' | 'reviewWorker',
              {
                ready?: boolean
                database?: string
                schema?: string
                runMarker?: string
              }
            >
          }
        }
        const readRuntimeContext = async () => {
          const response = await request.get('/api/runtime/ui-context')
          expect(
            response.ok(),
            `runtime target preflight returned HTTP ${response.status()}`
          ).toBeTruthy()
          return apiJson<RuntimeContext>(response)
        }
        const assertImmutableRuntimeIdentity = (runtime: RuntimeContext) => {
          expect(
            runtime.strictProduction,
            'strict-production targets are forbidden for destructive E2E'
          ).toBe(false)
          expect(runtime.environment, 'runtime environment identity is required').toBeTruthy()
          expect(
            /prod(?:uction)?/i.test(runtime.environment),
            `production-like target environment ${runtime.environment} is forbidden`
          ).toBe(false)
          expect(runtime.demoDataAllowed, 'release E2E must not use UI demo data').toBe(false)
          expect(
            runtime.buildVersion,
            'target build version must match the candidate under test'
          ).toBe(requiredEnvironment.buildVersion)
          expect(
            runtime.release.gitSha,
            'target build SHA must match the candidate under test'
          ).toBe(requiredEnvironment.buildSha)
        }
        const databaseScopeProblems = (runtime: RuntimeContext) => {
          const scope = runtime.databaseScope
          const problems: string[] = []
          if (!scope) return ['databaseScope is absent']
          if (scope.engine !== 'postgresql') problems.push(`engine=${String(scope.engine)}`)
          if (String(scope.database || '').toLowerCase() !== expectedDatabase) {
            problems.push(`database=${String(scope.database)}`)
          }
          if (scope.schema !== databaseSchema) problems.push(`schema=${String(scope.schema)}`)
          if (scope.runMarker !== requiredEnvironment.runMarker) {
            problems.push(`runMarker=${String(scope.runMarker)}`)
          }
          for (const participant of ['api', 'processingWorker', 'reviewWorker'] as const) {
            const identity = scope.participants?.[participant]
            if (identity?.ready !== true)
              problems.push(`${participant}.ready=${String(identity?.ready)}`)
            if (String(identity?.database || '').toLowerCase() !== expectedDatabase) {
              problems.push(`${participant}.database=${String(identity?.database)}`)
            }
            if (identity?.schema !== databaseSchema) {
              problems.push(`${participant}.schema=${String(identity?.schema)}`)
            }
            if (identity?.runMarker !== requiredEnvironment.runMarker) {
              problems.push(`${participant}.runMarker=${String(identity?.runMarker)}`)
            }
          }
          return problems
        }

        let runtime = await readRuntimeContext()
        assertImmutableRuntimeIdentity(runtime)
        const databaseScopeDeadline = Date.now() + 30_000
        let scopeProblems = databaseScopeProblems(runtime)
        while (scopeProblems.length && Date.now() < databaseScopeDeadline) {
          await page.waitForTimeout(750)
          runtime = await readRuntimeContext()
          // A target that changes to production or a different build is rejected immediately;
          // only database/worker identity warm-up receives the bounded polling window.
          assertImmutableRuntimeIdentity(runtime)
          scopeProblems = databaseScopeProblems(runtime)
        }
        if (scopeProblems.length) {
          const diagnostics = {
            targetOrigin: target.origin,
            expected: {
              engine: 'postgresql',
              database: expectedDatabase,
              schema: databaseSchema,
              runMarker: requiredEnvironment.runMarker,
              participants: ['api', 'processingWorker', 'reviewWorker']
            },
            problems: scopeProblems,
            latest: {
              environment: runtime.environment,
              strictProduction: runtime.strictProduction,
              buildVersion: runtime.buildVersion,
              release: runtime.release,
              databaseScope: runtime.databaseScope
            }
          }
          await testInfo.attach('runtime-database-scope-timeout.json', {
            body: Buffer.from(JSON.stringify(diagnostics, null, 2)),
            contentType: 'application/json'
          })
          throw new Error(
            `Runtime databaseScope did not match within 30 seconds: ${scopeProblems.join('; ')}`
          )
        }
        await testInfo.attach('runtime-target.json', {
          body: Buffer.from(
            JSON.stringify(
              {
                targetOrigin: target.origin,
                localTarget,
                environment: runtime.environment,
                strictProduction: runtime.strictProduction,
                release: runtime.release,
                buildVersion: runtime.buildVersion,
                databaseScope: runtime.databaseScope
              },
              null,
              2
            )
          ),
          contentType: 'application/json'
        })

        const response = await request.get('/api/healthz')
        expect(response.ok(), `health preflight returned HTTP ${response.status()}`).toBeTruthy()
        const health = await apiJson<Record<string, any>>(response)
        expect(health.authRequired, 'authentication must be enabled').toBe(true)
        expect(health.demoUsersEnabled, 'demo users must be disabled').toBe(false)
        expect(health.databaseBackend).toBe('postgres')
        expect(health.databaseConnected).toBe(true)
        expect(health.postgresEnabled).toBe(true)
        expect(health.postgresTransactions).toBe(true)
        expect(health.objectStorageEnabled).toBe(true)
        expect(health.serviceReadiness?.ocr?.ready, 'OCR provider must be ready').toBe(true)
        expect(
          health.serviceReadiness?.embedding?.configured,
          'embedding provider must be configured'
        ).toBe(true)
        expect(
          health.mineruWorker?.ready,
          'OCR/slicing/embedding worker heartbeat must be fresh'
        ).toBe(true)
        expect(health.workflowSchemaReady, 'Temporal workflow schema must be ready').toBe(true)
        expect(health.temporalReadiness?.mode, 'formal E2E requires Temporal orchestration').toBe(
          'temporal'
        )
        expect(
          health.temporalReadiness?.serviceConnected,
          'Temporal protocol probe must pass'
        ).toBe(true)
        expect(health.reviewDispatchReadiness?.ready, 'formal review dispatch must be ready').toBe(
          true
        )
        expect(
          health.reviewDispatchReadiness?.dependencyDetails?.workerHeartbeat?.ready,
          'Review Worker heartbeat must be fresh'
        ).toBe(true)
        expect(health.workflowReady).toBe(true)
        expect(health.runtimeReady).toBe(true)
        await testInfo.attach('preflight-health.json', {
          body: Buffer.from(JSON.stringify(health, null, 2)),
          contentType: 'application/json'
        })
        passGate(
          'P0-target-isolation',
          `${target.origin} reports ${runtime.environment}, strictProduction=false, build=${runtime.buildVersion}/${runtime.release.gitSha}, database=${expectedDatabase}, schema=${databaseSchema}, runMarker=${requiredEnvironment.runMarker}; API/processing/review participants match`
        )
      }
    )

    const runId = `${requiredEnvironment.runMarker}-${Date.now()}-${randomUUID().slice(0, 8)}`
    const projectName = `AI监检回归-${runId}`
    const projectCode = `E2E-${runId}`.slice(0, 48)
    const applicantPassword = `E2e!${randomUUID()}Aa1`
    const applicants = {
      contractor: {
        username: `e2e-contractor-${runId}`,
        displayName: `施工申请人-${runId}`,
        roleLabel: '施工单位',
        rolePath: '/workbench/contractor'
      },
      ndt: {
        username: `e2e-ndt-${runId}`,
        displayName: `无损申请人-${runId}`,
        roleLabel: '无损检测',
        rolePath: '/workbench/ndt'
      },
      owner: {
        username: `e2e-owner-${runId}`,
        displayName: `建设申请人-${runId}`,
        roleLabel: '建设单位',
        rolePath: '/workbench/owner'
      },
      inspection: {
        username: `e2e-inspection-${runId}`,
        displayName: `监检申请人-${runId}`,
        roleLabel: '监检人员',
        rolePath: '/workbench/inspection'
      }
    }
    let projectId = ''
    let adminLink = ''
    let leaderLink = ''
    const screenshots: string[] = []
    const contractorDocumentIds = new Set<string>()
    const ndtDocumentIds = new Set<string>()

    await gateStep(
      'admin creates the project and appoints the project leader',
      ['P0-registration-cross-approval', 'P0-approved-member-project-access'],
      async () => {
        await login(
          page,
          requiredEnvironment.adminUsername,
          requiredEnvironment.adminPassword,
          '/admin'
        )
        await page.goto('/#/admin/projects', { waitUntil: 'domcontentloaded' })
        await page.waitForLoadState('networkidle').catch(() => {})
        await page.getByRole('button', { name: '新建项目' }).click()
        const wizard = page.getByRole('dialog', { name: '项目立项向导' })
        await expect(wizard).toBeVisible()
        await formItem(wizard, '项目编号').locator('input').fill(projectCode)
        await formItem(wizard, '项目名称').locator('input').fill(projectName)
        await wizard.getByRole('button', { name: '下一步' }).click()

        for (const label of ['建设单位', '施工单位', '无损检测单位', '监检机构']) {
          await chooseSelectOption(page, formItem(wizard, label).locator('.el-select'))
        }
        await wizard.getByRole('button', { name: '下一步' }).click()

        const roleLabels = ['监检人员', '施工单位', '无损检测', '建设单位']
        for (const roleLabel of roleLabels) {
          const row = wizard.locator('.el-table__row').filter({ hasText: roleLabel }).first()
          await expect(row).toBeVisible()
          await chooseSelectOption(
            page,
            row.locator('.el-select'),
            roleLabel === '监检人员' ? requiredEnvironment.leaderMemberLabel : undefined
          )
        }

        const createResponse = page.waitForResponse(
          (response) =>
            response.url().endsWith('/api/admin/projects') && response.request().method() === 'POST'
        )
        await wizard.getByRole('button', { name: '创建项目' }).click()
        const created = await apiJson<{ project: { id: string; name: string } }>(
          await createResponse
        )
        projectId = created.project.id
        expect(projectId).toBeTruthy()
        await expect(wizard).toBeHidden()

        const detail = page.locator('.el-drawer:visible').filter({ hasText: '项目详情与成员授权' })
        const leaderRow = detail
          .locator('.el-table__row')
          .filter({ hasText: requiredEnvironment.leaderMemberLabel })
          .first()
        await expect(
          leaderRow,
          'initial inspection member matching leader credentials'
        ).toBeVisible()
        const leaderResponse = page.waitForResponse(
          (response) =>
            response.url().includes(`/api/projects/${encodeURIComponent(projectId)}/members/`) &&
            response.request().method() === 'PUT'
        )
        await leaderRow.getByRole('button', { name: '设为负责人' }).click()
        expect((await leaderResponse).ok()).toBeTruthy()
        await expect(leaderRow).toContainText('负责人')
        await page.keyboard.press('Escape')
      }
    )

    await gateStep(
      'new project has fixed node 36 rule and clause bindings before invitations',
      ['P1-project-package-binding'],
      async () => {
        await login(
          page,
          requiredEnvironment.leaderUsername,
          requiredEnvironment.leaderPassword,
          '/workbench/inspection'
        )
        await page.goto(
          `/#/workbench/inspection?projectId=${encodeURIComponent(projectId)}&nodeId=36&auditItem=submission&view=list`,
          { waitUntil: 'domcontentloaded' }
        )
        const projectPackage = await captureNodePackageOnReload(page, projectId, 36)
        expect(
          projectPackage.businessBasis?.ruleId,
          'node 36 fixed rule must be bound at bootstrap'
        ).toBeTruthy()
        expect(
          projectPackage.businessBasis?.ruleVersion,
          'node 36 fixed rule version is required'
        ).toBeTruthy()
        expect(
          projectPackage.businessBasis?.referencedStandards?.length,
          'node 36 fixed clause/standard references must be bound at bootstrap'
        ).toBeGreaterThan(0)
        passGate(
          'P1-project-package-binding',
          `node 36 rule=${projectPackage.businessBasis?.ruleId}, version=${projectPackage.businessBasis?.ruleVersion}, references=${projectPackage.businessBasis?.referencedStandards?.length}`
        )
      }
    )

    await gateStep(
      'admin and project leader generate independent browser links',
      ['P0-registration-cross-approval'],
      async () => {
        await login(
          page,
          requiredEnvironment.adminUsername,
          requiredEnvironment.adminPassword,
          '/admin'
        )
        await page.goto('/#/admin/projects', { waitUntil: 'domcontentloaded' })
        const search = page.getByLabel('搜索项目名称、编号或区域')
        await search.fill(projectName)
        await page.getByRole('button', { name: '查询' }).click()
        const row = page
          .locator('.desktop-project-table .el-table__row')
          .filter({ hasText: projectName })
        await expect(row).toHaveCount(1)
        await row.getByRole('button', { name: '注册审核' }).click()
        const adminPanel = page.locator('.project-registration:visible')
        await adminPanel.getByRole('button', { name: '生成项目注册链接' }).click()
        adminLink = await adminPanel.locator('.link-result input').inputValue()
        expect(adminLink).toContain('/#/join/')
        await screenshotEvidence(page, testInfo, '01-admin-registration-link')
        screenshots.push('01-admin-registration-link.png')

        await login(
          page,
          requiredEnvironment.leaderUsername,
          requiredEnvironment.leaderPassword,
          '/workbench/inspection'
        )
        await selectProject(page, projectName)
        await page.getByRole('button', { name: '注册链接与审核' }).click()
        const leaderPanel = page.locator('.project-registration:visible')
        await leaderPanel.getByRole('button', { name: '生成项目注册链接' }).click()
        leaderLink = await leaderPanel.locator('.link-result input').inputValue()
        expect(leaderLink).toContain('/#/join/')
        expect(leaderLink).not.toBe(adminLink)
        await screenshotEvidence(page, testInfo, '02-leader-registration-link')
        screenshots.push('02-leader-registration-link.png')
      }
    )

    await gateStep(
      'four anonymous applicants apply and cannot log in before approval',
      ['P0-registration-cross-approval'],
      async () => {
        await submitAnonymousApplication(page, adminLink, {
          ...applicants.contractor,
          password: applicantPassword
        })
        await submitAnonymousApplication(page, adminLink, {
          ...applicants.ndt,
          password: applicantPassword
        })
        await submitAnonymousApplication(page, leaderLink, {
          ...applicants.owner,
          password: applicantPassword
        })
        await submitAnonymousApplication(page, leaderLink, {
          ...applicants.inspection,
          password: applicantPassword
        })
        for (const applicant of Object.values(applicants)) {
          await login(page, applicant.username, applicantPassword, applicant.rolePath, false)
        }
        for (const [endpoint, method] of [
          [`/api/projects/${encodeURIComponent(projectId)}/registration-requests`, 'GET'],
          [`/api/projects/${encodeURIComponent(projectId)}/registration-links`, 'POST']
        ] as const) {
          const probe = await browserAnonymousProbe(page, endpoint, method)
          expect(probe.status, `anonymous ${method} ${endpoint} must require authentication`).toBe(
            401
          )
          expect(probe.businessCode).not.toBe(0)
          anonymousManagementProbes.push(probe)
        }
      }
    )

    await gateStep(
      'admin and leader cross-approve applications issued by the other party',
      ['P0-registration-cross-approval'],
      async () => {
        await login(
          page,
          requiredEnvironment.adminUsername,
          requiredEnvironment.adminPassword,
          '/admin'
        )
        await page.goto('/#/admin/projects', { waitUntil: 'domcontentloaded' })
        await page.getByLabel('搜索项目名称、编号或区域').fill(projectName)
        await page.getByRole('button', { name: '查询' }).click()
        const row = page
          .locator('.desktop-project-table .el-table__row')
          .filter({ hasText: projectName })
        await row.getByRole('button', { name: '注册审核' }).click()
        await reviewApplicants(page, [applicants.owner.username, applicants.inspection.username])

        await login(
          page,
          requiredEnvironment.leaderUsername,
          requiredEnvironment.leaderPassword,
          '/workbench/inspection'
        )
        await selectProject(page, projectName)
        await page.getByRole('button', { name: '注册链接与审核' }).click()
        await reviewApplicants(page, [applicants.contractor.username, applicants.ndt.username])
        passGate(
          'P0-registration-cross-approval',
          'four anonymous applications denied preapproval login; admin approved leader-issued requests and leader approved admin-issued requests; anonymous management probes returned 401'
        )
      }
    )

    await gateStep(
      'all approved roles can log in and see the new project',
      ['P0-approved-member-project-access'],
      async () => {
        for (const applicant of Object.values(applicants)) {
          await login(page, applicant.username, applicantPassword, applicant.rolePath)
          await selectProject(page, projectName)
          await expect(page.getByLabel('当前项目')).toContainText(projectName)
        }
        passGate(
          'P0-approved-member-project-access',
          'contractor, NDT, owner, and inspection accounts all selected the newly created project after approval'
        )
      }
    )

    await gateStep(
      'contractor selects fifteen real files in one chooser and uploads once',
      ['P1-contractor-fifteen-file-batch'],
      async () => {
        await login(
          page,
          applicants.contractor.username,
          applicantPassword,
          applicants.contractor.rolePath
        )
        await selectProject(page, projectName)
        const uploadPanel = page.locator('.contractor-upload-panel')
        const chooser = uploadPanel.locator('input[type="file"]')
        await chooser.setInputFiles(contractorFiles)
        await expect(uploadPanel.locator('[aria-label="待上传文件"] li')).toHaveCount(15)
        await expect(uploadPanel).toContainText('已选择 15 个文件')
        await screenshotEvidence(page, testInfo, '03-contractor-fifteen-file-chooser')
        screenshots.push('03-contractor-fifteen-file-chooser.png')
        const uploadSessionResponse = page.waitForResponse(
          (response) =>
            response
              .url()
              .includes(
                `/api/projects/${encodeURIComponent(projectId)}/documents/upload-session`
              ) &&
            !response.url().endsWith('/complete') &&
            response.request().method() === 'POST'
        )
        const completionResponse = page.waitForResponse(
          (response) =>
            response
              .url()
              .includes(
                `/api/projects/${encodeURIComponent(projectId)}/documents/upload-session/`
              ) &&
            response.url().endsWith('/complete') &&
            response.request().method() === 'POST'
        )
        await uploadPanel.getByRole('button', { name: '上传 15 个文件' }).click()
        const uploadSession = await apiJson<{
          uploadUrls: Array<{ documentId: string; documentVersionId: string }>
        }>(await uploadSessionResponse)
        expect(uploadSession.uploadUrls).toHaveLength(15)
        uploadSession.uploadUrls.forEach((target) => contractorDocumentIds.add(target.documentId))
        expect(contractorDocumentIds.size).toBe(15)

        const completed = await apiJson<{ fileCount: number; queuedTasks: unknown[] }>(
          await completionResponse
        )
        expect(completed.fileCount).toBe(15)
        expect(completed.queuedTasks).toBeInstanceOf(Array)
        const contractorPackage = await captureAnyNodeProjectFilesOnReload(page, projectId)
        contractorVisibleDocumentIds = contractorPackage.projectFiles.map((file) => file.id)
        expect(contractorVisibleDocumentIds).toEqual(
          expect.arrayContaining([...contractorDocumentIds])
        )
        await expect(page.locator('.file-library-head-actions')).toContainText('15 / 15 个文件')
        await expect(page.locator('.status-filter-row')).toContainText('全部 15')
        await expect(uploadPanel).toContainText('最近上传：8 个文件')
        await screenshotEvidence(page, testInfo, '04-contractor-upload-complete')
        screenshots.push('04-contractor-upload-complete.png')
        passGate(
          'P1-contractor-fifteen-file-batch',
          'one chooser retained 15, completion returned 15, package/table total was 15; recent widget correctly remained capped at 8'
        )
      }
    )

    await gateStep(
      'NDT cannot see contractor drafts and uploads eight typed files with complete bindings',
      ['P1-ndt-eight-file-bindings'],
      async () => {
        await login(page, applicants.ndt.username, applicantPassword, applicants.ndt.rolePath)
        await selectProject(page, projectName)
        const beforeUpload = await captureAnyNodeProjectFilesOnReload(page, projectId)
        expect(beforeUpload.projectFiles, 'NDT must not receive contractor drafts').toHaveLength(0)

        for (const group of ndtUploadGroups) {
          const checklistRow = page
            .locator('.ndt-checklist-table .el-table__row')
            .filter({ hasText: group.material })
            .first()
          await expect(
            checklistRow,
            `NDT typed upload row ${group.material} must be present in the business UI`
          ).toBeVisible()
          await checklistRow.getByRole('button', { name: '上传文件' }).click()
          const drawer = page.locator('.el-drawer:visible').filter({ hasText: '上传无损检测资料' })
          await expect(drawer).toContainText(group.material)
          for (const nodeId of group.expectedNodes) {
            const checkbox = drawer
              .locator('.el-checkbox')
              .filter({ hasText: ndtRuleNames[nodeId] })
              .first()
            await expect(checkbox, `NDT binding option for node ${nodeId}`).toBeVisible()
            if (!(await checkbox.locator('input').isChecked())) {
              await checkbox.click()
            }
          }
          await drawer.locator('input[type="file"]').setInputFiles(group.files)
          await expect(drawer.locator('[aria-label="待上传文件"] li')).toHaveCount(
            group.files.length
          )
          const completionResponse = page.waitForResponse(
            (response) =>
              response
                .url()
                .includes(
                  `/api/projects/${encodeURIComponent(projectId)}/documents/upload-session/`
                ) &&
              response.url().endsWith('/complete') &&
              response.request().method() === 'POST'
          )
          await drawer.getByRole('button', { name: `上传 ${group.files.length} 个文件` }).click()
          const completed = await apiJson<{
            fileCount: number
            documents: Array<{ documentId: string; bindingIds: string[] }>
          }>(await completionResponse)
          expect(completed.fileCount).toBe(group.files.length)
          expect(completed.documents).toHaveLength(group.files.length)
          for (const document of completed.documents) {
            expect(document.bindingIds).toHaveLength(group.expectedNodes.length)
            ndtDocumentIds.add(document.documentId)
          }
        }
        expect(ndtDocumentIds.size).toBe(8)
        const ndtPackage = await captureAnyNodeProjectFilesOnReload(page, projectId)
        expect(new Set(ndtPackage.projectFiles.map((file) => file.id))).toEqual(ndtDocumentIds)
        for (const group of ndtUploadGroups) {
          for (const filePath of group.files) {
            const uploaded = ndtPackage.projectFiles.find(
              (file) => file.fileName === basename(filePath)
            )
            expect(
              uploaded,
              `uploaded NDT file ${basename(filePath)} must be returned`
            ).toBeTruthy()
            expect(uploaded?.materialTypeName).toBe(group.material)
            expect(new Set((uploaded?.bindings || []).map((binding) => binding.nodeId))).toEqual(
              new Set(group.expectedNodes)
            )
          }
        }
        await expect(page.locator('.ndt-checklist')).toContainText('8 个文件')
        await screenshotEvidence(page, testInfo, '05-ndt-eight-typed-files')
        screenshots.push('05-ndt-eight-typed-files.png')
        passGate(
          'P1-ndt-eight-file-bindings',
          'eight typed NDT documents returned with exact node bindings: certificate 35, personnel 38, plan 36+38'
        )
      }
    )

    await gateStep(
      'contractor and NDT drafts remain isolated and owner has no upload control',
      ['P0-cross-organization-document-isolation', 'P1-owner-upload-denial'],
      async () => {
        await login(
          page,
          applicants.contractor.username,
          applicantPassword,
          applicants.contractor.rolePath
        )
        await selectProject(page, projectName)
        const contractorPackage = await captureAnyNodeProjectFilesOnReload(page, projectId)
        expect(new Set(contractorPackage.projectFiles.map((file) => file.id))).toEqual(
          contractorDocumentIds
        )
        expect(
          contractorPackage.projectFiles.some((file) => ndtDocumentIds.has(file.id)),
          'contractor must not receive NDT drafts'
        ).toBe(false)
        directResourceProbes.push(
          ...(await probeForeignDocument(page, 'contractor', projectId, [...ndtDocumentIds][0]))
        )

        await login(page, applicants.ndt.username, applicantPassword, applicants.ndt.rolePath)
        await selectProject(page, projectName)
        const ndtPackage = await captureAnyNodeProjectFilesOnReload(page, projectId)
        ndtVisibleDocumentIds = ndtPackage.projectFiles.map((file) => file.id)
        expect(new Set(ndtVisibleDocumentIds)).toEqual(ndtDocumentIds)
        expect(
          ndtPackage.projectFiles.some((file) => contractorDocumentIds.has(file.id)),
          'NDT must not receive contractor drafts'
        ).toBe(false)
        directResourceProbes.push(
          ...(await probeForeignDocument(page, 'ndt', projectId, [...contractorDocumentIds][0]))
        )

        await login(page, applicants.owner.username, applicantPassword, applicants.owner.rolePath)
        await selectProject(page, projectName)
        await expect(page.locator('.role-section-card').first()).toContainText('只读模式')
        ownerUploadControls = await page
          .locator('button:visible')
          .filter({ hasText: /上传|选择文件/ })
          .count()
        expect(ownerUploadControls, 'owner must not have any upload affordance').toBe(0)
        directResourceProbes.push(
          ...(await probeForeignDocument(page, 'owner', projectId, [...contractorDocumentIds][0])),
          ...(await probeForeignDocument(page, 'owner', projectId, [...ndtDocumentIds][0]))
        )
        await screenshotEvidence(page, testInfo, '06-owner-upload-denied')
        screenshots.push('06-owner-upload-denied.png')
        passGate(
          'P0-cross-organization-document-isolation',
          `role package lists were disjoint and ${directResourceProbes.length} detail/preview/download/original/office-preview probes returned 403/404`
        )
        passGate(
          'P1-owner-upload-denial',
          'owner displayed zero upload controls and direct IDs denied'
        )
      }
    )

    const readyFiles: ProjectFile[] = []
    await gateStep(
      'wait for OCR, slicing, and vector readiness, then submit both parties files',
      ['P1-processing-readiness-and-submission'],
      async () => {
        await login(
          page,
          applicants.inspection.username,
          applicantPassword,
          applicants.inspection.rolePath
        )
        await page.goto(
          `/#/workbench/inspection?projectId=${encodeURIComponent(projectId)}&nodeId=36&auditItem=ocr&view=list`,
          { waitUntil: 'domcontentloaded' }
        )
        const allDocumentIds = new Set([...contractorDocumentIds, ...ndtDocumentIds])
        const node36Readiness = await waitForFilesReadyThroughBrowser(
          page,
          projectId,
          36,
          allDocumentIds
        )
        readyFiles.push(
          ...node36Readiness.projectFiles.filter((file) => allDocumentIds.has(file.id))
        )

        await login(page, applicants.ndt.username, applicantPassword, applicants.ndt.rolePath)
        await selectProject(page, projectName)
        for (let submitted = 0; submitted < ndtDocumentIds.size; submitted += 1) {
          const button = page
            .locator('#ndt-pending-files')
            .locator('button:enabled')
            .filter({ hasText: '提交审批' })
            .first()
          await expect(button, `enabled NDT submit button ${submitted + 1}/8`).toBeVisible()
          const responsePromise = page.waitForResponse(
            (response) =>
              response
                .url()
                .endsWith(
                  `/api/projects/${encodeURIComponent(projectId)}/ndt/material-submissions`
                ) && response.request().method() === 'POST'
          )
          await button.click()
          expect((await responsePromise).ok()).toBeTruthy()
        }

        await login(
          page,
          applicants.contractor.username,
          applicantPassword,
          applicants.contractor.rolePath
        )
        await selectProject(page, projectName)
        const search = page.getByLabel('搜索项目文件')
        for (const filePath of contractorFiles) {
          const fileName = basename(filePath)
          await search.fill(fileName)
          const row = page
            .locator('.contractor-files-table .el-table__row')
            .filter({ hasText: fileName })
          await expect(row).toHaveCount(1)
          await expect(row).toContainText('上传成功')
          const responsePromise = page.waitForResponse(
            (response) =>
              response
                .url()
                .endsWith(`/api/projects/${encodeURIComponent(projectId)}/submissions`) &&
              response.request().method() === 'POST'
          )
          await row.getByRole('button', { name: '提交', exact: true }).click()
          const confirm = page.locator('.el-message-box:visible')
          await confirm.getByRole('button', { name: '确认提交' }).click()
          expect((await responsePromise).ok()).toBeTruthy()
        }
        await search.clear()
        expect(
          readyFiles,
          'readiness evidence must cover all contractor and NDT files'
        ).toHaveLength(23)
        passGate(
          'P1-processing-readiness-and-submission',
          'node 36 package showed 23/23 files OCR accepted + sliced + vectorized before 8 NDT and 15 contractor submissions'
        )
      }
    )

    await gateStep(
      'inspection confirms every node 36 evidence candidate required for formal review',
      ['P1-evidence-confirmation'],
      async () => {
        await login(
          page,
          applicants.inspection.username,
          applicantPassword,
          applicants.inspection.rolePath
        )
        await page.goto(
          `/#/workbench/inspection?projectId=${encodeURIComponent(projectId)}&nodeId=36&auditItem=evidence&view=list`,
          { waitUntil: 'domcontentloaded' }
        )
        let evidencePackage = await captureNodePackageOnReload(page, projectId, 36)
        let pendingCount = Number(evidencePackage.evidenceReadiness?.pendingCount || 0)
        const candidateCount = evidencePackage.nodeEvidenceLinks?.length || 0
        if (!candidateCount) {
          throw new Error(
            'Formal review gate blocked: node 36 produced no evidence candidates after the NDT plan reached OCR/slice/vector readiness. Check material targeting and submitted bindings.'
          )
        }

        let confirmedCount = 0
        while (pendingCount > 0) {
          const previousPendingCount = pendingCount
          const renderedRows = page.locator('.evidence-confirmation-table .el-table__row')
          const confirmButton = page
            .locator('.evidence-confirmation-table button:enabled')
            .filter({ hasText: /^确认$/ })
            .first()
          try {
            await expect
              .poll(() => renderedRows.count(), {
                timeout: 15_000,
                message: 'wait for evidence confirmation rows to render after package reload'
              })
              .toBeGreaterThan(0)
            await expect(confirmButton, 'wait for an enabled evidence Confirm action').toBeVisible({
              timeout: 15_000
            })
          } catch (cause) {
            throw new Error(
              `Formal review gate blocked: readiness reports ${pendingCount} pending evidence candidates, but the evidence UI exposes no enabled Confirm action. ` +
                `renderedRows=${await renderedRows.count()}, missing=${evidencePackage.evidenceReadiness?.missingCount || 0}, ` +
                `blocking=${JSON.stringify(evidencePackage.evidenceReadiness?.blockingReasons || [])}`,
              { cause }
            )
          }
          const confirmationResponse = page.waitForResponse(
            (response) =>
              response.url().includes('/evidence-links/') &&
              response.url().endsWith('/confirm') &&
              response.request().method() === 'POST'
          )
          await confirmButton.click()
          expect((await confirmationResponse).ok()).toBeTruthy()
          confirmedCount += 1
          evidencePackage = await captureNodePackageOnReload(page, projectId, 36)
          pendingCount = Number(evidencePackage.evidenceReadiness?.pendingCount || 0)
          expect(
            pendingCount,
            `confirming evidence must reduce pending count from ${previousPendingCount}`
          ).toBeLessThan(previousPendingCount)
          if (confirmedCount > candidateCount) {
            throw new Error(
              'Evidence confirmation did not reduce pending candidates; refusing to loop.'
            )
          }
        }

        const missingCount = Number(evidencePackage.evidenceReadiness?.missingCount || 0)
        if (missingCount || evidencePackage.evidenceReadiness?.readyForAiFormal !== true) {
          throw new Error(
            `Formal review gate blocked after evidence confirmation: missing=${missingCount}, pending=${pendingCount}, readyForAiFormal=${String(
              evidencePackage.evidenceReadiness?.readyForAiFormal
            )}, blocking=${JSON.stringify(evidencePackage.evidenceReadiness?.blockingReasons || [])}. ` +
              'Use the evidence panel to bind/confirm the missing node 36 evidence; gap precheck is not accepted.'
          )
        }
        await screenshotEvidence(page, testInfo, '07-node36-evidence-confirmed')
        screenshots.push('07-node36-evidence-confirmed.png')
        passGate(
          'P1-evidence-confirmation',
          `${confirmedCount} pending candidates confirmed through the evidence UI; missing=0, pending=0, readyForAiFormal=true`
        )
      }
    )

    await gateStep(
      'inspection runs formal Temporal review and timeline agrees with result',
      ['P1-formal-ai-result-agreement'],
      async () => {
        await login(
          page,
          applicants.inspection.username,
          applicantPassword,
          applicants.inspection.rolePath
        )
        await page.goto(
          `/#/workbench/inspection?projectId=${encodeURIComponent(projectId)}&nodeId=36&auditItem=ai_review&view=list`,
          { waitUntil: 'domcontentloaded' }
        )
        await page.waitForLoadState('networkidle').catch(() => {})
        const packageBeforeReview = await captureNodePackageOnReload(page, projectId, 36)
        expect(
          packageBeforeReview.businessBasis?.ruleId,
          'fixed rule must be bound to node 36'
        ).toBeTruthy()
        expect(
          packageBeforeReview.businessBasis?.ruleVersion,
          'fixed rule version must be bound'
        ).toBeTruthy()
        expect(
          packageBeforeReview.businessBasis?.referencedStandards?.length,
          'fixed clause/standard references must be bound to the new project'
        ).toBeGreaterThan(0)

        const aiPanel = page.locator('#inspection-audit-panel-ai_review')
        await expect(aiPanel).toBeVisible()
        const formal = aiPanel.getByRole('radio', { name: '正式复核' })
        await expect(
          formal,
          'formal review must be enabled; no deterministic inline fallback'
        ).toBeEnabled()
        await formal.click()
        const reviewResponse = page.waitForResponse(
          (response) =>
            response
              .url()
              .endsWith(
                `/api/projects/${encodeURIComponent(projectId)}/inspection/nodes/36/ai-recheck`
              ) && response.request().method() === 'POST'
        )
        await aiPanel.getByRole('button', { name: '发起正式复核' }).click()
        const createdRun = await apiJson<{
          latestRun: { id: string; reviewRunId?: string }
          dispatch?: { statusReason?: string }
        }>(await reviewResponse)
        expect(createdRun.latestRun.id).toBeTruthy()

        const deadline = Date.now() + 15 * 60_000
        let finalPackage: NodePackage | undefined
        while (Date.now() < deadline) {
          finalPackage = await captureNodePackageOnReload(page, projectId, 36)
          const run = finalPackage.aiRuns?.find((item) => item.id === createdRun.latestRun.id)
          if (run && ['完成', '待人工核验'].includes(run.status) && run.suggestion?.result) break
          if (run?.status === '失败') throw new Error(`Formal AI review ${run.id} failed.`)
          await page.waitForTimeout(5_000)
        }
        const finalRun = finalPackage?.aiRuns?.find((item) => item.id === createdRun.latestRun.id)
        expect(
          finalRun?.suggestion?.result,
          'formal AI run must finish with a suggestion'
        ).toBeTruthy()
        expect(
          finalRun?.suggestion?.confidence,
          'formal AI result must include confidence'
        ).toBeGreaterThanOrEqual(0)
        expect(
          finalRun?.evidenceLinks?.length,
          'formal AI result must retain evidence links'
        ).toBeGreaterThan(0)
        expect(finalRun?.ruleVersion, 'formal AI result must retain its rule version').toBeTruthy()
        const result = String(finalRun?.suggestion?.result || '')
        await expect(page.locator('.ai-outcome-result')).toHaveText(result)
        const timelineItem = page
          .locator('.node-review-timeline .el-timeline-item')
          .filter({ hasText: 'AI' })
          .filter({ hasText: result })
          .first()
        await expect(
          timelineItem,
          `timeline must show the same conclusion as the AI result panel: ${result}`
        ).toBeVisible()
        await screenshotEvidence(page, testInfo, '08-formal-ai-result-and-timeline')
        screenshots.push('08-formal-ai-result-and-timeline.png')
        passGate(
          'P1-formal-ai-result-agreement',
          `formal AI run=${finalRun?.id}, result=${result}, timeline matched, evidence=${finalRun?.evidenceLinks?.length}, ruleVersion=${finalRun?.ruleVersion}`
        )

        const allFiles = readyFiles
        const gateResults: GateResult[] = requiredReleaseGates.map((gate) => ({
          ...gate,
          status: passedGateEvidence.has(gate.id) ? 'passed' : 'open',
          evidence:
            passedGateEvidence.get(gate.id) || 'required gate did not record passing evidence'
        }))
        const openRequiredGateCount = gateResults.filter((gate) => gate.status === 'open').length
        const openP0P1Defects = defectInventory.filter(
          (defect) => defect.status === 'open' && ['P0', 'P1'].includes(defect.severity)
        ).length
        expect(openRequiredGateCount, JSON.stringify(gateResults, null, 2)).toBe(0)
        expect(openP0P1Defects, JSON.stringify(defectInventory, null, 2)).toBe(0)
        const summary: AcceptanceSummary = {
          projectId,
          projectName,
          buildSha: requiredEnvironment.buildSha,
          databaseSchema,
          linkIssuers: [requiredEnvironment.adminUsername, requiredEnvironment.leaderUsername],
          registeredRoles: ['contractor', 'ndt', 'owner', 'inspection'],
          contractorFileCount: contractorDocumentIds.size,
          ndtFileCount: ndtDocumentIds.size,
          isolation: {
            contractorVisibleDocumentIds,
            ndtVisibleDocumentIds,
            ownerUploadControls,
            directResourceProbes,
            anonymousManagementProbes
          },
          readiness: {
            ocr: allFiles.filter((file) =>
              ['已识别', '人工修正', '抽取不完整'].includes(String(file.currentOcrStatus || ''))
            ).length,
            sliced: allFiles.filter((file) => file.sliceStatus === '已切片').length,
            vectorized: allFiles.filter((file) => file.vectorStatus === '已向量化').length,
            total: allFiles.length
          },
          ai: {
            runId: String(finalRun?.id || ''),
            reviewRunId: finalRun?.reviewRunId,
            result,
            confidence: finalRun?.suggestion?.confidence,
            evidenceLinkIds: finalRun?.evidenceLinks?.map((item) => item.id) || [],
            ruleReferences: packageBeforeReview.businessBasis?.referencedStandards || []
          },
          screenshots,
          openRequiredGateCount,
          openP0P1Defects,
          defectInventorySource:
            'defectInventory records are created only by gateStep catches, include severity and error text, and are attached immediately on failure',
          defectInventory,
          gateResults
        }
        await testInfo.attach('acceptance-summary.json', {
          body: Buffer.from(JSON.stringify(summary, null, 2)),
          contentType: 'application/json'
        })
      }
    )
  })
})
