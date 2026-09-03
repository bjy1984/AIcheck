import assert from 'node:assert/strict'

import type { InspectionAuditItem } from '@/types/aicheck'
import {
  buildWorkbenchAiHistory,
  buildWorkbenchAiPresentation,
  buildWorkbenchHumanAiContext,
  inspectionReviewDirectoryItems,
  inspectionReviewDirectoryItemsWithAiStatus,
  projectAnalysisExecutionStepStatus,
  selectWorkbenchAiPresentation,
  workbenchEvidenceGroups,
  workbenchFindingDisplay,
  workbenchReviewSectionOrder
} from './workbenchReviewPresentation'

const auditItems = [
  'submission',
  'ocr',
  'evidence',
  'ai_review',
  'human_review',
  'report',
  'archive'
].map(
  (key) =>
    ({
      key,
      label: key,
      status: 'not_started',
      statusLabel: '未开始',
      metric: '-',
      summary: '-',
      issueCount: 0,
      issues: [],
      sourceRefs: [],
      availableActions: []
    }) as InspectionAuditItem
)

assert.deepEqual(
  inspectionReviewDirectoryItems(auditItems).map((item) => item.key),
  ['ai_review', 'human_review'],
  '完整工作台目录只保留 AI复核和人工结论两个标签'
)
assert.deepEqual(
  workbenchReviewSectionOrder,
  ['ai_review', 'human_review'],
  'AI 信息必须排在人工审查之前'
)

const completed = buildWorkbenchAiPresentation({
  run: {
    projectAnalysisRunId: 'PARUN-1',
    phase: 'waiting_human_review',
    status: 'waiting_human_review',
    estimatedInputTokens: 75853,
    validatedFindingCount: 1,
    persistedNodeCount: 42,
    finishedAt: '2026-08-27 20:10:00'
  },
  nodeReview: {
    reviewRunId: 'RRUN-PA-1',
    projectAnalysisRunId: 'PARUN-1',
    triggerType: 'manual_full_project_analysis',
    reviewResult: 'partially_supported',
    status: 'waiting_human_review',
    findingDrafts: [
      {
        id: 'FND-1',
        findingType: 'license_scope',
        severity: 'high',
        title: '许可范围需要人工确认',
        description: '现有证据不足以确认许可范围完全覆盖。',
        confidence: 0.72,
        evidenceRefs: [{ fileId: 'DOC-1' }],
        ruleRefs: [{ source: 'criteria', text: '规则原文' }]
      }
    ],
    finishedAt: '2026-08-27 20:10:00'
  }
})

assert.equal(completed.sourceLabel, '全工程一键分析')
assert.equal(completed.runId, 'PARUN-1')
assert.equal(completed.statusLabel, 'AI 已完成，等待人工确认')
assert.equal(completed.resultLabel, '部分证据支持')
assert.equal(completed.findings.length, 1)
assert.deepEqual(completed.findings[0], {
  id: 'FND-1',
  typeLabel: 'license_scope',
  severity: 'high',
  severityLabel: '高',
  title: '许可范围需要人工确认',
  description: '现有证据不足以确认许可范围完全覆盖。',
  confidence: 0.72,
  evidenceCount: 1,
  ruleCount: 1,
  evidenceRefs: [{ fileId: 'DOC-1' }],
  ruleRefs: [{ source: 'criteria', text: '规则原文' }]
})
assert.equal(completed.canRetry, false)
assert.deepEqual(workbenchFindingDisplay(completed.findings[0]), {
  id: 'FND-1',
  title: '许可范围需要人工确认',
  description: '现有证据不足以确认许可范围完全覆盖。',
  evidenceCount: 1,
  ruleCount: 1,
  evidenceRefs: [{ fileId: 'DOC-1' }],
  ruleRefs: [{ source: 'criteria', text: '规则原文' }],
  severityTag: '重要',
  severityTone: 'orange',
  confidencePercent: 72,
  evidenceGroups: [{ fileId: 'DOC-1', fileName: 'DOC-1', pages: [], quotes: [] }]
})
assert.deepEqual(
  workbenchEvidenceGroups([
    { fileId: 'DOC-9', fileName: '焊工证.pdf', pageNo: 2, quotedText: '姓名 姜军' },
    { fileId: 'DOC-9', fileName: '焊工证.pdf', pageNo: 1, quotedText: ' 姓名  姜军 ' },
    { fileId: 'DOC-9', fileName: '焊工证.pdf', pageNo: null, quotedText: '有效期至 2029-09-30' },
    { fileId: 'DOC-8', fileName: '工艺卡.pdf' }
  ]),
  [
    {
      fileId: 'DOC-9',
      fileName: '焊工证.pdf',
      pages: [1, 2],
      quotes: ['姓名 姜军', '有效期至 2029-09-30']
    },
    { fileId: 'DOC-8', fileName: '工艺卡.pdf', pages: [], quotes: [] }
  ],
  '同一文件的引用合并成一组，页码排序、引用原文去重'
)
assert.deepEqual(buildWorkbenchHumanAiContext(completed), {
  overall: '当前节点形成 1 条审查发现，所有结果均需人工确认。',
  ruleConclusion: '部分证据支持',
  ruleDescription: '当前节点形成 1 条审查发现，所有结果均需人工确认。',
  manualConfirmItems: ['许可范围需要人工确认']
})

const failed = buildWorkbenchAiPresentation({
  run: {
    projectAnalysisRunId: 'PARUN-FAILED',
    phase: 'failed',
    status: 'failed',
    errorCode: 'LLM_OUTPUT_INVALID_JSON',
    errorMessage: '模型输出不是合法 JSON'
  },
  nodeReview: null
})

assert.equal(failed.statusLabel, 'AI 结果生成失败')
assert.equal(failed.resultLabel, '未产出结论')
assert.equal(failed.errorMessage, '模型输出不是合法 JSON')
assert.equal(failed.findings.length, 0)
assert.equal(failed.canRetry, true)

const stalled = buildWorkbenchAiPresentation({
  run: {
    projectAnalysisRunId: 'PARUN-STALLED',
    phase: 'failed',
    status: 'failed',
    errorCode: 'PROJECT_ANALYSIS_RUN_STALLED',
    errorMessage: '本次工程 AI 分析长时间没有进展，未形成可展示结果；请重新发起分析。'
  },
  nodeReview: null
})
assert.equal(stalled.statusLabel, 'AI 执行已中断')
assert.equal(stalled.canRetry, true)
const failedDirectoryItems = inspectionReviewDirectoryItemsWithAiStatus(auditItems, stalled)
assert.deepEqual(
  failedDirectoryItems.map((item) => [item.key, item.status, item.statusLabel]),
  [
    ['ai_review', 'failed', 'AI 执行已中断'],
    ['human_review', 'not_started', '未开始']
  ]
)

const validating = buildWorkbenchAiPresentation({
  run: {
    projectAnalysisRunId: 'PARUN-VALIDATING',
    phase: 'validating_output',
    status: 'validating_output',
    validatedFindingCount: 0
  },
  nodeReview: null
})
assert.equal(validating.statusLabel, '正在校验 AI 结果')
assert.equal(validating.summary, '模型调用已经完成，正在校验结果结构、节点覆盖和证据引用。')

const nodeRun = {
  id: 'AIRUN-NEWER',
  projectId: 'P-1',
  nodeId: 1,
  subject: '节点复核',
  model: 'review-chat',
  promptVersion: 'review@1',
  ruleVersion: 'rule@1',
  status: '完成' as const,
  suggestion: {
    id: 'SUG-1',
    result: '需补正' as const,
    opinionDraft: '节点复核发现一项需要补正的问题。',
    confidence: 0.88,
    manualConfirmItems: ['核对许可证范围']
  },
  evidenceLinks: [],
  finishedAt: '2026-08-28 09:00:00'
}
const newestNodeRun = selectWorkbenchAiPresentation({
  projectAnalysis: completed,
  projectAnalysisFinishedAt: '2026-08-27 20:10:00',
  nodeRun,
  nodeFindings: [],
  nodeOutputText: '节点复核发现一项需要补正的问题。'
})

assert.equal(newestNodeRun.sourceLabel, '节点 AI 复核')
assert.equal(newestNodeRun.runId, 'AIRUN-NEWER')
assert.equal(newestNodeRun.resultLabel, '需补正')
assert.equal(newestNodeRun.summary, '节点复核发现一项需要补正的问题。')

const newerProjectResult = selectWorkbenchAiPresentation({
  projectAnalysis: completed,
  projectAnalysisFinishedAt: '2026-08-27 20:10:00',
  nodeRun: {
    ...nodeRun,
    id: 'AIRUN-OLD-FAILED',
    status: '失败',
    finishedAt: undefined,
    updatedAt: undefined,
    createdAt: undefined
  },
  nodeFindings: [],
  nodeOutputText: '旧节点运行失败'
})
assert.equal(newerProjectResult.sourceLabel, '全工程一键分析')
assert.equal(newerProjectResult.resultLabel, '部分证据支持')
assert.deepEqual(
  [1, 3, 4, 6].map((target) =>
    projectAnalysisExecutionStepStatus('failed', target, 'validating_output')
  ),
  ['完成', '完成', '异常', '待执行']
)

const runningNodeRun = selectWorkbenchAiPresentation({
  projectAnalysis: buildWorkbenchAiPresentation(null),
  nodeRun: { ...nodeRun, id: 'AIRUN-RUNNING', status: '推理中', finishedAt: undefined },
  nodeFindings: [],
  nodeOutputText: '正在等待模型输出。'
})
assert.equal(runningNodeRun.sourceLabel, '节点 AI 复核')
assert.equal(runningNodeRun.statusLabel, 'AI 正在分析')

const structuredNodeRun = selectWorkbenchAiPresentation({
  projectAnalysis: buildWorkbenchAiPresentation(null),
  nodeRun,
  nodeFindings: [completed.findings[0]],
  nodeOutputText: '{"findings":[{"title":"许可范围需要人工确认"}]}'
})
assert.equal(structuredNodeRun.summary, '节点复核发现一项需要补正的问题。')

const olderNodeRun = {
  ...nodeRun,
  id: 'AIRUN-OLDER',
  finishedAt: '2026-08-26 09:00:00',
  suggestion: {
    ...nodeRun.suggestion,
    result: '满足要求' as const,
    opinionDraft: '历史复核认为满足要求。'
  }
}
const history = buildWorkbenchAiHistory({
  current: newestNodeRun,
  projectAnalysis: completed,
  nodeRuns: [nodeRun, olderNodeRun]
})
assert.deepEqual(
  history.map((item) => [item.runId, item.resultLabel, item.summary]),
  [
    ['PARUN-1', '部分证据支持', '当前节点形成 1 条审查发现，所有结果均需人工确认。'],
    ['AIRUN-OLDER', '满足要求', '历史复核认为满足要求。']
  ],
  '历史 AI 结果应排除当前运行并按时间倒序展示'
)

const failedHistory = buildWorkbenchAiHistory({
  current: newestNodeRun,
  projectAnalysis: buildWorkbenchAiPresentation(null),
  nodeRuns: [
    {
      ...olderNodeRun,
      id: 'AIRUN-FAILED-HISTORY',
      status: '失败',
      failure: {
        kind: 'orchestration',
        reason: '编排服务连接失败，本次审查没有开始执行。',
        nextStep: '检查编排服务后重试。',
        retryable: true,
        detail: 'connection refused',
        detailRecorded: true
      }
    }
  ]
})
assert.equal(failedHistory[0].summary, '编排服务连接失败，本次审查没有开始执行。')

// 证照核验块要原样带到展示模型：监检看卡片就能知道「证还有效吗」，不必翻 finding 文字
{
  const { workbenchCertificateVerification } = await import('./workbenchReviewPresentation')
  const block = workbenchCertificateVerification({
    result: 'passed',
    certificateType: 'design_license',
    period: { start: null, end: null, referenceDate: '2026-09-03' },
    certificates: [
      {
        label: 'TS1',
        holder: '广东政和工程有限公司',
        certificateNo: 'TS1844171-2028',
        validFrom: null,
        validUntil: '2028-01-17',
        scopes: ['GC1'],
        result: 'passed'
      }
    ],
    warnings: ['construction_period_missing_using_reference_date']
  })
  assert.equal(block?.result, 'passed')
  assert.equal(block?.certificates[0].validUntil, '2028-01-17')
  assert.deepEqual(block?.certificates[0].scopes, ['GC1'])
  assert.equal(workbenchCertificateVerification(null), undefined)
  assert.equal(workbenchCertificateVerification('x'), undefined)
}
