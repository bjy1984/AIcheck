import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import {
  buildImportResults,
  hasDuplicateImportNames,
  getImportSkippedFromError
} from './knowledgeImportResults'

const require = createRequire(import.meta.url)
const ts = require('typescript') as typeof import('typescript')
const source = readFileSync(new URL('./KnowledgeOverview.vue', import.meta.url), 'utf8')
const script = source.split('<script setup lang="ts">')[1].split('</script>')[0]
const ast = ts.createSourceFile('KnowledgeOverview.ts', script, ts.ScriptTarget.Latest, true)
// Exercise the production SFC functions with controlled API promises, without mounting Element Plus.
const instantiate = (names: string[], bindings: Record<string, unknown>) => {
  const declarations = ast.statements.flatMap((statement) => {
    if (ts.isFunctionDeclaration(statement) && names.includes(statement.name?.text || ''))
      return [statement.getText(ast)]
    if (ts.isVariableStatement(statement)) {
      return statement.declarationList.declarations
        .filter(
          (declaration) =>
            ts.isIdentifier(declaration.name) && names.includes(declaration.name.text)
        )
        .map((declaration) => `const ${declaration.getText(ast)};`)
    }
    return []
  })
  const js = ts.transpileModule(declarations.join('\n'), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None }
  }).outputText
  return new Function(...Object.keys(bindings), `${js}; return {${names.join(',')}}`)(
    ...Object.values(bindings)
  )
}
const computed = (fn: () => unknown) => ({
  get value() {
    return fn()
  }
})
const deferred = () => {
  let resolve!: (value: unknown) => void
  const promise = new Promise((done) => {
    resolve = done
  })
  return { promise, resolve }
}
const checks: Array<[string, () => Promise<void>]> = [
  [
    'partial knowledge upload retains failed file metadata and lists successes',
    async () => {
      const good = {
        fileName: 'good.pdf',
        relativePath: 'folder/good.pdf',
        contextDescription: 'good',
        file: {}
      }
      const bad = {
        fileName: 'bad.pdf',
        relativePath: 'folder/bad.pdf',
        contextDescription: 'keep this context',
        file: {}
      }
      const sourceUploadFiles = { value: [good, bad] }
      const sourceDialogVisible = { value: true }
      const sourceImportResults = { value: [] as unknown[] }
      const { handleSaveSource } = instantiate(['handleSaveSource'], {
        sourceUploadFiles,
        sourceDialogVisible,
        sourceImportResults,
        sourceDialogContext: { value: 'standard-file' },
        sourceDialogMode: { value: 'create' },
        sourceForm: { name: '标准库', sourceType: 'standard', version: 'v1' },
        sourceUploadProjectId: { value: '' },
        actionLoading: { value: '' },
        clearOperationIssue: () => {},
        setOperationIssue: (_key: unknown, _title: unknown, error: unknown) => {
          throw error
        },
        ElMessage: { success: () => {}, warning: () => {} },
        importKnowledgeFilesApi: async () => ({
          data: {
            files: [{ fileName: 'good.pdf' }],
            skipped: [{ fileName: 'bad.pdf', reason: '空文件' }]
          }
        }),
        refreshKnowledgeState: async () => {},
        buildOperationFailureMessage: () => '',
        buildImportResults,
        hasDuplicateImportNames,
        DEFAULT_STANDARD_SOURCE_ID: 'KS-STANDARD-RULES',
        DEFAULT_STANDARD_SOURCE_NAME: '标准库',
        DEFAULT_STANDARD_SOURCE_VERSION: 'v1'
      })
      await handleSaveSource()
      assert.equal(sourceDialogVisible.value, true)
      assert.deepEqual(sourceUploadFiles.value, [bad])
      assert.equal(sourceImportResults.value.length, 2)
    }
  ],
  [
    'same-name uploads are rejected before a partial retry can become ambiguous',
    async () => {
      assert.equal(
        hasDuplicateImportNames([{ name: 'same.pdf' }, { name: 'same.pdf' }], (row) => row.name),
        true
      )
      assert.deepEqual(
        buildImportResults(
          [{ name: 'a.pdf' }, { name: 'b.pdf' }],
          [{ fileName: 'b.pdf', reason: '空文件' }],
          (row) => row.name
        ).map((row) => row.status),
        ['已导入', '未导入']
      )
    }
  ],

  [
    'unknown summary values are not inferred from a single task page',
    async () => {
      const { knowledgeTopStats } = instantiate(['knowledgeTopStats'], {
        computed,
        getOverviewMetricNumber: () => undefined,
        knowledgeTopTaskCounts: { vectorLoaded: false, failedLoaded: false },
        tasks: { value: [{ taskType: 'vector', status: '成功' }] },
        sources: { value: [] },
        sourcePagination: { total: 0 }
      })
      assert.deepEqual(
        knowledgeTopStats.value.map((stat: { value: unknown }) => stat.value),
        ['未取得', '未取得', '未取得']
      )
    }
  ],
  [
    'rollback candidates load independently and exclude drafts and later publications',
    async () => {
      const rollbackCandidates = { value: [] as any[] }
      const source = { id: 'active', ruleKey: 'RULE-A', publishedAt: '2026-10-20' }
      const { loadRollbackCandidates } = instantiate(['loadRollbackCandidates'], {
        rollbackSource: { value: source },
        rollbackRequest: 0,
        rollbackLoading: { value: false },
        rollbackIssue: { value: undefined },
        rollbackSelectedId: { value: '' },
        rollbackCandidates,
        rollbackPagination: { page: 2, pageSize: 20, total: 0 },
        assertApiResponse: (res: unknown) => res,
        getErrorMessage: String,
        applyPagination: (_state: unknown, data: any) => data.items,
        listKnowledgeRuleVersionsApi: async (params: any) => {
          assert.equal(params.page, 2)
          assert.equal(params.keyword, 'RULE-A')
          assert.equal(params.status, undefined)
          return {
            data: {
              items: [
                { id: 'draft', ruleKey: 'RULE-A', status: '草稿' },
                { id: 'later', ruleKey: 'RULE-A', status: '已发布', publishedAt: '2026-10-25' },
                { id: 'other', ruleKey: 'RULE-B', status: '已回滚' },
                { id: 'older', ruleKey: 'RULE-A', status: '已回滚', publishedAt: '2026-10-10' }
              ]
            }
          }
        }
      })
      await loadRollbackCandidates()
      assert.deepEqual(
        rollbackCandidates.value.map((row) => row.id),
        ['older']
      )
    }
  ],
  [
    'compare history requests later pages and keeps the server total',
    async () => {
      const compareRuns = { value: [] as unknown[] }
      const comparePagination = { page: 2, pageSize: 20, total: 0 }
      const { loadCompareRuns } = instantiate(['loadCompareRuns'], {
        compareRuns,
        comparePagination,
        loadSection: async (
          _key: string,
          _title: string,
          loader: (current: () => boolean) => Promise<void>
        ) => loader(() => true),
        assertApiResponse: (res: unknown) => res,
        applyPagination: (state: typeof comparePagination, data: any) => {
          state.total = data.total
          return data.items
        },
        listLlmCompareRunsApi: async (params: any) => {
          assert.deepEqual(params, { page: 2, pageSize: 20 })
          return { data: { items: [{ runId: 'older-run' }], total: 41 } }
        }
      })
      await loadCompareRuns()
      assert.equal(comparePagination.total, 41)
      assert.deepEqual(compareRuns.value, [{ runId: 'older-run' }])
    }
  ],
  [
    'returning to config keeps unsaved settings',
    async () => {
      let loads = 0
      const knowledgeConfig = { topKDefault: 9 }
      const { loadKnowledgeConfig } = instantiate(['loadKnowledgeConfig'], {
        knowledgeConfigDirty: { value: true },
        knowledgeConfig,
        knowledgeConfigSaved: { value: '{}' },
        loadSection: async (
          _key: string,
          _title: string,
          loader: (current: () => boolean) => Promise<void>
        ) => loader(() => true),
        getKnowledgeConfigApi: async () => {
          loads++
          return { data: { config: { topKDefault: 3 } } }
        },
        assertApiResponse: (res: unknown) => res
      })
      await loadKnowledgeConfig()
      assert.equal(loads, 0)
      assert.equal(knowledgeConfig.topKDefault, 9)
    }
  ],
  [
    'task detail requests the deep-linked ID even when it is not listed',
    async () => {
      const taskDetail = { value: undefined as unknown }
      const taskDetailLoading = { value: false }
      const taskDetailVisible = { value: false }
      const { loadTaskDetail } = instantiate(['loadTaskDetail'], {
        taskDetail,
        taskDetailLoading,
        taskDetailVisible,
        taskDetailId: { value: '' },
        taskDetailIssue: { value: undefined },
        taskDetailRequest: 0,
        assertApiResponse: (res: unknown) => res,
        getErrorMessage: String,
        getKnowledgeTaskApi: async (id: string) => {
          assert.equal(id, 'KT-outside-page')
          return { data: { task: { id } } }
        }
      })
      await loadTaskDetail('KT-outside-page')
      assert.deepEqual(taskDetail.value, { id: 'KT-outside-page' })
      assert.equal(taskDetailVisible.value, true)
      assert.equal(taskDetailLoading.value, false)
    }
  ],

  [
    'task deep link loads the specified task outside the current page',
    async () => {
      let detailLoads = 0
      const bindings = Object.fromEntries(
        [
          'loadTasks',
          'loadSources',
          'loadStandardFiles',
          'loadFiles',
          'loadRuleVersions',
          'loadKnowledgeConfig',
          'loadKnowledgeAuditLogs',
          'loadReasoningLogs',
          'loadCompareRuns',
          'loadPageIndexNodes',
          'loadOverview',
          'loadProjectOptions'
        ].map((name) => [name, async () => {}])
      )
      const { loadKnowledgeTabData } = instantiate(['loadKnowledgeTabData'], {
        ...bindings,
        loadTaskFromRoute: async () => {
          detailLoads++
        }
      })
      await loadKnowledgeTabData('tasks')
      assert.equal(detailLoads, 1)
    }
  ],
  [
    'partial rule import retains only failed files and shows per-file outcomes',
    async () => {
      const good = { name: 'good.md' },
        bad = { name: 'bad.md' }
      const knowledgeImportFiles = { value: [good, bad] }
      const knowledgeImportVisible = { value: true }
      const knowledgeImportResults = { value: [] as unknown[] }
      const { handleImportKnowledgeFiles } = instantiate(['handleImportKnowledgeFiles'], {
        knowledgeImportFiles,
        knowledgeImportVisible,
        knowledgeImportResults,
        actionLoading: { value: '' },
        businessRuleImportVersion: { value: 'v1' },
        clearOperationIssue: () => {},
        setOperationIssue: () => {},
        ElMessage: { success: () => {}, warning: () => {} },
        importBusinessRulesApi: async () => ({
          data: { importedRules: [{}], skipped: [{ fileName: 'bad.md', reason: '无法解析规则' }] }
        }),
        loadRuleVersions: async () => {},
        loadKnowledgeAuditLogs: async () => {},
        buildOperationFailureMessage: () => '',
        buildImportResults,
        hasDuplicateImportNames,
        getImportSkippedFromError
      })
      await handleImportKnowledgeFiles()
      assert.equal(knowledgeImportVisible.value, true)
      assert.deepEqual(knowledgeImportFiles.value, [bad])
      assert.equal(knowledgeImportResults.value.length, 2)
    }
  ],
  [
    'overview and files load their own dependencies',
    async () => {
      const calls: string[] = []
      const bindings = Object.fromEntries(
        [
          'loadSources',
          'loadStandardFiles',
          'loadFiles',
          'loadTasks',
          'loadRuleVersions',
          'loadKnowledgeConfig',
          'loadKnowledgeAuditLogs',
          'loadReasoningLogs',
          'loadCompareRuns',
          'loadPageIndexNodes',
          'loadOverview',
          'loadProjectOptions'
        ].map((name) => [
          name,
          async () => {
            calls.push(name)
          }
        ])
      )
      const { loadKnowledgeTabData } = instantiate(['loadKnowledgeTabData'], bindings)
      await loadKnowledgeTabData('overview')
      assert.ok(calls.includes('loadSources'), 'overview must request its visible sources')
      calls.length = 0
      await loadKnowledgeTabData('files')
      assert.ok(calls.includes('loadProjectOptions'), 'navigation must load all eligible projects')
    }
  ],
  [
    'old file request cannot overwrite a newer filter result',
    async () => {
      const first = deferred(),
        second = deferred()
      let request = 0
      const files = { value: [] as Array<{ id: string }> }
      const fileFilters = { keyword: 'old', projectId: '', nodeId: undefined, status: '' }
      const pagination = { page: 1, pageSize: 10, total: 0 }
      const sectionLoading: Record<string, boolean> = {},
        sectionLoaded: Record<string, boolean> = {}
      const { loadFiles } = instantiate(['loadSection', 'loadFiles'], {
        sectionRequests: {},
        sectionLoading,
        sectionLoaded,
        clearSectionIssue: () => {},
        setSectionIssue: () => {},
        files,
        fileFilters,
        filePagination: pagination,
        assertApiResponse: (res: unknown) => res,
        applyPagination: (state: typeof pagination, payload: any) => {
          state.total = payload.total
          return payload.items
        },
        listKnowledgeProjectFilesApi: () => (++request === 1 ? first.promise : second.promise)
      })
      const pendingOld = loadFiles()
      fileFilters.keyword = 'new'
      const pendingNew = loadFiles()
      second.resolve({ data: { items: [{ id: 'new' }], total: 1 } })
      await pendingNew
      first.resolve({ data: { items: [{ id: 'old' }], total: 1 } })
      await pendingOld
      assert.equal(files.value[0].id, 'new')
      assert.equal(sectionLoading.files, false)
    }
  ],
  [
    'overview failure keeps independent tabs available',
    async () => {
      const { canShowKnowledgeContent } = instantiate(['canShowKnowledgeContent'], {
        computed,
        pageIssue: { value: { type: 'error', title: '总览请求失败' } }
      })
      assert.equal(canShowKnowledgeContent.value, true)
    }
  ],
  [
    'cancel standard reset sends no mutation',
    async () => {
      let mutations = 0
      const { handleImportRulesStandards } = instantiate(['handleImportRulesStandards'], {
        actionLoading: { value: '' },
        clearOperationIssue: () => {},
        ElMessageBox: {
          confirm: async () => {
            throw 'cancel'
          }
        },
        ElMessage: { success: () => {} },
        setOperationIssue: () => {},
        importRulesStandardsApi: async () => {
          mutations++
          return { data: {} }
        },
        refreshKnowledgeState: async () => {},
        buildOperationFailureMessage: () => '',
        DEFAULT_STANDARD_SOURCE_ID: 'KS-STANDARD-RULES',
        DEFAULT_STANDARD_SOURCE_NAME: '标准规范库',
        DEFAULT_STANDARD_SOURCE_VERSION: 'v1'
      })
      await handleImportRulesStandards()
      assert.equal(mutations, 0, 'reset must require explicit confirmation')
    }
  ]
]
let failures = 0
for (const [name, check] of checks) {
  try {
    await check()
    console.log(`PASS ${name}`)
  } catch (error) {
    failures++
    console.error(`FAIL ${name}`, error)
  }
}
assert.equal(failures, 0, `${failures} knowledge recovery checks failed`)
