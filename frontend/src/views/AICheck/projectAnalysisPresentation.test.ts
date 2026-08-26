import assert from 'node:assert/strict'

import { projectAnalysisProgressView } from './projectAnalysisPresentation'
import type { ProjectAnalysisStatus } from '@/api/aicheck/projectAnalysis'

const status = (values: Partial<ProjectAnalysisStatus>): ProjectAnalysisStatus =>
  ({
    projectAnalysisRunId: 'PARUN-1',
    projectId: 'P-1',
    status: 'preparing_snapshot',
    phase: 'preparing_snapshot',
    includedNodeCount: 42,
    uniqueFileCount: 16,
    fileReferenceCount: 68,
    estimatedInputTokens: 90000,
    preparedNodeCount: 0,
    loadedFileCount: 0,
    totalFindingCount: 0,
    validatedFindingCount: 0,
    persistedNodeCount: 0,
    progressMode: 'determinate',
    percent: 0,
    ...values
  }) as ProjectAnalysisStatus

assert.deepEqual(
  projectAnalysisProgressView(status({ phase: 'preparing_snapshot', preparedNodeCount: 12 })),
  { mode: 'determinate', percent: 0, label: '正在收集节点 12/42' }
)
assert.deepEqual(
  projectAnalysisProgressView(status({ phase: 'building_prompt', loadedFileCount: 9 })),
  { mode: 'determinate', percent: 0, label: '正在拼接 OCR 9/16 · 预计 90,000 tokens' }
)
assert.deepEqual(
  projectAnalysisProgressView(status({ phase: 'model_running', progressMode: 'indeterminate' })),
  { mode: 'indeterminate', label: '大模型正在进行全工程分析' }
)
assert.deepEqual(
  projectAnalysisProgressView(
    status({ phase: 'validating_output', totalFindingCount: 10, validatedFindingCount: 6 })
  ),
  { mode: 'determinate', percent: 0, label: '正在校验分析结果 6/10' }
)
assert.deepEqual(
  projectAnalysisProgressView(status({ phase: 'persisting_results', persistedNodeCount: 20 })),
  { mode: 'determinate', percent: 0, label: '正在回挂节点结果 20/42' }
)
assert.deepEqual(
  projectAnalysisProgressView(
    status({ phase: 'waiting_human_review', progressMode: 'determinate', percent: 100 })
  ),
  { mode: 'determinate', percent: 100, label: '全工程分析完成，等待人工确认' }
)
