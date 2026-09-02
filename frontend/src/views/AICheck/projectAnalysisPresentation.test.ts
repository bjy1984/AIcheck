import assert from 'node:assert/strict'

import * as presentation from './projectAnalysisPresentation'
import type { ProjectAnalysisStatus } from '@/api/aicheck/projectAnalysis'

const { projectAnalysisProgressView, projectAnalysisRequestFailure } =
  presentation as typeof presentation & {
    projectAnalysisRequestFailure?: (error: unknown) => { terminal: boolean; message: string }
  }
const projectAnalysisBannerState = (
  presentation as typeof presentation & {
    projectAnalysisBannerState?: (
      status?: ProjectAnalysisStatus
    ) => { tone: 'running' | 'success' | 'failure'; label: string } | undefined
  }
).projectAnalysisBannerState

assert.equal(typeof projectAnalysisRequestFailure, 'function')
assert.deepEqual(
  projectAnalysisRequestFailure?.({ response: { data: { data: { reason: 'NOT_FOUND' } } } }),
  { terminal: true, message: '分析任务不存在或已失效，请重新发起。' }
)
assert.deepEqual(projectAnalysisRequestFailure?.(new Error('network')), {
  terminal: true,
  message: '全工程分析状态刷新失败，请稍后重试。'
})

// 机器可读错误码必须译成人话——空范围这种错误照抄兜底文案会骗用户去「稍后重试」
assert.deepEqual(
  projectAnalysisRequestFailure?.({
    response: { data: { message: 'PROJECT_ANALYSIS_EMPTY_SCOPE' } }
  }),
  {
    terminal: true,
    message:
      '当前项目还没有可分析的节点资料：请先在节点上挂接有效资料（且未被驳回），再发起一键分析。'
  }
)
assert.deepEqual(
  projectAnalysisRequestFailure?.({
    response: { data: { message: 'PROJECT_ANALYSIS_CONTEXT_LIMIT_EXCEEDED' } }
  }),
  {
    terminal: true,
    message: '项目资料总量超出模型可处理上限，请减少纳入分析的资料后重试。'
  }
)
assert.deepEqual(
  projectAnalysisRequestFailure?.({
    response: { data: { data: { currentSnapshotHash: 'sha256:new' } } }
  }),
  {
    terminal: true,
    message: '项目资料在预览后发生了变化，请刷新预览确认范围后重新发起。'
  }
)

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

assert.equal(typeof projectAnalysisBannerState, 'function')
assert.deepEqual(projectAnalysisBannerState?.(status({ phase: 'queued' })), {
  tone: 'running',
  label: 'AI一键分析正在运行'
})
assert.deepEqual(projectAnalysisBannerState?.(status({ phase: 'model_running' })), {
  tone: 'running',
  label: 'AI一键分析正在运行'
})
assert.deepEqual(projectAnalysisBannerState?.(status({ phase: 'failed' }), true), {
  tone: 'running',
  label: 'AI一键分析正在运行'
})
assert.deepEqual(projectAnalysisBannerState?.(status({ phase: 'waiting_human_review' })), {
  tone: 'success',
  label: 'AI分析完成'
})
assert.deepEqual(projectAnalysisBannerState?.(status({ phase: 'partial_failure' })), {
  tone: 'failure',
  label: 'AI分析失败'
})
assert.deepEqual(projectAnalysisBannerState?.(status({ phase: 'failed' })), {
  tone: 'failure',
  label: 'AI分析失败'
})
assert.equal(projectAnalysisBannerState?.(), undefined)

// 超限提示必须可执行：带前三大文件与 token 占用，而不是一句「减少资料」
assert.deepEqual(
  projectAnalysisRequestFailure?.({
    response: {
      data: {
        message: 'PROJECT_ANALYSIS_CONTEXT_LIMIT_EXCEEDED',
        data: {
          topCorpusFiles: [
            { fileName: 'RT检测报告R2.pdf', estimatedTokens: 41200 },
            { fileName: '质量证明书.pdf', estimatedTokens: 12600 }
          ]
        }
      }
    }
  }),
  {
    terminal: true,
    message:
      '项目资料总量超出模型可处理上限，请减少纳入分析的资料后重试。占用最大的资料：RT检测报告R2.pdf（约 41.2k tokens）、质量证明书.pdf（约 12.6k tokens）。'
  }
)

// 分批运行的进度文案带批次；单批不带（与分批前一致）
assert.equal(
  projectAnalysisProgressView(
    status({
      phase: 'model_running',
      batchCount: 4,
      currentBatchIndex: 1,
      progressMode: 'indeterminate'
    })
  ).label,
  '大模型正在进行全工程分析（第 2/4 批）'
)
assert.equal(
  projectAnalysisProgressView(status({ phase: 'model_running', progressMode: 'indeterminate' }))
    .label,
  '大模型正在进行全工程分析'
)

// run 列表原始项没有 percent：已完成的分析打开抽屉时不能显示成 0%
assert.deepEqual(
  projectAnalysisProgressView(
    status({ phase: 'waiting_human_review', progressMode: 'determinate', percent: undefined })
  ),
  { mode: 'determinate', percent: 100, label: '全工程分析完成，等待人工确认' }
)
