import assert from 'node:assert/strict'

import type { InspectionAuditItem } from '@/types/aicheck'
import {
  buildWorkbenchAiHistory,
  buildWorkbenchAiPresentation,
  buildWorkbenchHumanAiContext,
  inspectionReviewDirectoryItems,
  humanizeFindingText,
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
  typeLabel: '许可范围',
  severity: 'high',
  severityLabel: '高',
  title: '许可范围需要人工确认',
  description: '现有证据不足以确认许可范围完全覆盖。',
  confidence: 0.72,
  evidenceCount: 1,
  ruleCount: 1,
  evidenceRefs: [{ fileId: 'DOC-1' }],
  ruleRefs: [{ source: 'criteria', text: '规则原文' }],
  // P9 R1 契约字段：没有守卫信息时按"通过守卫、无待核对项"处理
  findingType: 'license_scope',
  groundingStatus: '',
  unsupportedClaims: [],
  rawUnsupportedClaims: [],
  suggestedAction: '',
  actionLabel: '',
  modelTitle: '',
  modelDescription: '',
  unverified: false,
  policyPending: false,
  policyName: ''
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
assert.equal(
  humanizeFindingText('certificateVerification.result为passed，证书X持证人为姜军。'),
  '服务端证照核验结论为「核验通过」，证书X持证人为姜军。'
)
assert.equal(
  humanizeFindingText(
    'certificateVerification.result为evidence_insufficient；证书为evidence_insufficient'
  ),
  '服务端证照核验结论为「证据不足」；证书为证据不足'
)
assert.equal(humanizeFindingText('依据 certificateVerification 判断'), '依据 证照核验 判断')
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

// 节点级运行的发现必须直接来自落库的 findings 数组，而不是从自由文本解析：
// 2026-09-06 登录实测节点 2 库里 13 条、面板 0 张卡，就是因为只解析 llmResultText。
{
  const { nodeRunFindingViews } = await import('./workbenchReviewPresentation')
  const views = nodeRunFindingViews({
    findings: [
      {
        id: 'FND-1',
        findingType: '资质不匹配',
        severity: 'high',
        title: '许可证有效期覆盖施工计划工期存疑',
        description: '许可证有效期至 2026-12-25，施工计划工期未提取到。',
        confidence: 0.62,
        evidenceRefs: [{ documentVersionId: 'DV-1', pageNo: 1, quotedText: '有效期至 2026-12-25' }],
        ruleRefs: [{ ruleCode: 'engineering-inspection-r02' }]
      },
      null,
      'not-an-object'
    ] as unknown as Array<Record<string, unknown>>
  })
  assert.equal(views.length, 1)
  assert.equal(views[0].id, 'FND-1')
  assert.equal(views[0].severityLabel, '高')
  assert.equal(views[0].evidenceCount, 1)
  assert.equal(views[0].ruleCount, 1)
  assert.equal(views[0].confidence, 0.62)
  assert.deepEqual(nodeRunFindingViews(null), [])
  assert.deepEqual(nodeRunFindingViews({}), [])
}

// P9 R1：结论卡只由 12.3 的决策表推导；三组排序；证据不足折叠为去重待核对项。
{
  const { buildWorkbenchAiConclusion, nodeRunFindingViews, describeUnsupportedClaim } =
    await import('./workbenchReviewPresentation')
  const claims = [{ claim: 'TS9999999-2030', reason: 'not_present_in_supplied_evidence' }]
  const downgraded = (id: string, extra: Record<string, unknown> = {}) => ({
    id,
    findingType: 'missing_evidence',
    severity: 'medium',
    title: '证据不足，需人工确认',
    description: '模型给出的业务结论缺少证据支持，已整条丢弃并降级为待人工确认。',
    groundingStatus: 'insufficient_evidence',
    unsupportedClaims: claims,
    unverified: true,
    evidenceRefs: [],
    ruleRefs: [],
    ...extra
  })
  const grounded = (id: string, severity: string, title: string) => ({
    id,
    findingType: 'qualification_mismatch',
    severity,
    title,
    description: '许可证许可范围为 GC2，本工程为 GC1，范围不覆盖。',
    groundingStatus: 'grounded',
    suggestedAction: 'request_correction',
    evidenceRefs: [{ fileName: '安装许可证.pdf', pageNo: 2, quotedText: '许可范围 GC2' }],
    ruleRefs: [{ ruleCode: 'AC-R01-01' }]
  })

  assert.equal(
    describeUnsupportedClaim({
      claim: 'TS9999999-2030',
      reason: 'not_present_in_supplied_evidence'
    }),
    '「TS9999999-2030」在已提交资料中未找到'
  )
  assert.equal(
    describeUnsupportedClaim({
      claim: 'positive_business_conclusion',
      reason: 'positive_claim_without_specific_evidence_token'
    }),
    '肯定结论没有指向任何具体证据'
  )

  // 全部降级：结论「证据不足」，两条同断言集合的降级条目只剩一个待核对项
  const allDowngraded = buildWorkbenchAiConclusion({
    findings: nodeRunFindingViews({ findings: [downgraded('F1'), downgraded('F2')] }),
    deterministicResult: 'passed'
  })
  assert.equal(allDowngraded.verdict, '证据不足')
  assert.equal(allDowngraded.tone, 'gray')
  assert.deepEqual(allDowngraded.counts, { needAction: 0, confirm: 0, insufficient: 2, passed: 0 })
  assert.equal(allDowngraded.insufficientClaims.length, 1)
  assert.equal(allDowngraded.insufficientClaims[0].findingId, 'F1')
  assert.equal(allDowngraded.action, '要求补资料')
  assert.equal(allDowngraded.headline, '2 条发现证据不足，待核对 1 项')

  // 混合：high 通过守卫 → 需处理；medium → 待确认；降级 → 证据不足；关键事实带证据位置
  const mixed = buildWorkbenchAiConclusion({
    findings: nodeRunFindingViews({
      findings: [
        downgraded('F1'),
        grounded('F2', 'medium', '施工日期早于许可证有效期起始日，需核对'),
        grounded('F3', 'high', '安装许可证许可范围 GC2 不覆盖本工程 GC1 管道')
      ]
    }),
    deterministicResult: 'failed'
  })
  assert.equal(mixed.verdict, '需处理')
  assert.equal(mixed.tone, 'red')
  assert.deepEqual(
    mixed.groups.needAction.map((item) => item.id),
    ['F3']
  )
  assert.deepEqual(
    mixed.groups.confirm.map((item) => item.id),
    ['F2']
  )
  assert.deepEqual(
    mixed.groups.insufficient.map((item) => item.id),
    ['F1']
  )
  assert.equal(mixed.keyFacts[0].text, '安装许可证许可范围 GC2 不覆盖本工程 GC1 管道')
  assert.equal(mixed.keyFacts[0].location, '安装许可证.pdf 第 2 页')
  assert.equal(mixed.action, '要求补资料')
  assert.equal(mixed.deterministicLabel, '确定性核验未通过')
  assert.equal(mixed.groups.needAction[0].typeLabel, '资质不匹配')
  assert.equal(mixed.groups.needAction[0].actionLabel, '要求补资料')

  // 只有 medium/low 通过守卫 → 待确认
  const confirmOnly = buildWorkbenchAiConclusion({
    findings: nodeRunFindingViews({ findings: [grounded('F2', 'low', '合同工期未提取到')] }),
    deterministicResult: 'passed'
  })
  assert.equal(confirmOnly.verdict, '待确认')
  assert.equal(confirmOnly.action, '人工确认')

  // 全部通过：确定性 passed 且无发现 → 未见问题；无确定性结果也无发现 → 证据不足（不敢说未见问题）
  const clean = buildWorkbenchAiConclusion({ findings: [], deterministicResult: 'passed' })
  assert.equal(clean.verdict, '未见问题')
  assert.equal(clean.tone, 'green')
  assert.equal(buildWorkbenchAiConclusion({ findings: [] }).verdict, '证据不足')

  // 确定性 failed 但没有任何发现，仍是需处理（规则结果优先）
  assert.equal(
    buildWorkbenchAiConclusion({ findings: [], deterministicResult: 'failed' }).verdict,
    '需处理'
  )
}

// P8 H4：修复与升级都失败的分片要让人看见——结果只覆盖了部分证据。
{
  const { partialCoverageLabel } = await import('./workbenchReviewPresentation')
  assert.equal(partialCoverageLabel(null), undefined)
  assert.equal(partialCoverageLabel({ failedEvidenceShardIds: [] }), undefined)
  assert.equal(
    partialCoverageLabel({
      failedEvidenceShardIds: ['ESHARD-2'],
      evidenceCoverage: { expectedShardCount: 9 }
    }),
    '部分分片未完成 1/9'
  )
  assert.equal(partialCoverageLabel({ failedEvidenceShardIds: ['A', 'B'] }), '部分分片未完成 2 片')
}

// 逐项核查结果要带出来，通过项也要——只列问题时，「没报问题」和「压根没查」看起来一样。
{
  const { workbenchCheckOutcomes, CHECK_OUTCOME_LABELS } = await import(
    './workbenchReviewPresentation'
  )
  assert.deepEqual(workbenchCheckOutcomes(undefined), [])
  assert.deepEqual(workbenchCheckOutcomes({ atomicCheckOutcomes: '不是数组' }), [])
  assert.deepEqual(
    workbenchCheckOutcomes({
      atomicCheckOutcomes: [
        {
          atomicCheckId: 'AC-R25-01',
          name: '焊接（粘接）工艺文件·WPS/PQR审批与对应',
          result: 'passed'
        },
        { atomicCheckId: 'AC-R25-02', result: 'evidence_insufficient', ruleCode: 'r25' },
        { atomicCheckId: '', name: '没有 id 的不要', result: 'passed' }
      ]
    }),
    [
      {
        atomicCheckId: 'AC-R25-01',
        name: '焊接（粘接）工艺文件·WPS/PQR审批与对应',
        result: 'passed',
        ruleCode: undefined,
        unscoredFacts: [],
        checks: [],
        reason: '',
        facts: []
      },
      {
        atomicCheckId: 'AC-R25-02',
        name: 'AC-R25-02',
        result: 'evidence_insufficient',
        ruleCode: 'r25',
        unscoredFacts: [],
        checks: [],
        reason: '',
        facts: []
      }
    ]
  )
  assert.equal(CHECK_OUTCOME_LABELS.passed, '通过')
  assert.equal(CHECK_OUTCOME_LABELS.not_applicable, '不适用')
}

// 两条取数路径都要带上：一键分析读 nodeReview，节点复核读 run 本身。
{
  const { buildWorkbenchAiPresentation, selectWorkbenchAiPresentation } = await import(
    './workbenchReviewPresentation'
  )
  const fromProjectAnalysis = buildWorkbenchAiPresentation({
    run: { projectAnalysisRunId: 'PARUN-9', status: '已完成', finishedAt: '2026-09-11 10:00:00' },
    nodeReview: {
      deterministicResult: 'passed',
      atomicCheckOutcomes: [
        { atomicCheckId: 'AC-R28-01', name: '管道组对·组对实测值', result: 'passed' }
      ]
    }
  } as never)
  assert.deepEqual(
    fromProjectAnalysis.checkOutcomes.map((item) => [item.atomicCheckId, item.result]),
    [['AC-R28-01', 'passed']]
  )
  assert.deepEqual(buildWorkbenchAiPresentation(null).checkOutcomes, [])

  const fromNodeRun = selectWorkbenchAiPresentation({
    projectAnalysis: buildWorkbenchAiPresentation(null),
    nodeRun: {
      id: 'AIRUN-1',
      status: '完成',
      finishedAt: '2026-09-11 11:00:00',
      atomicCheckOutcomes: [
        { atomicCheckId: 'AC-R24-01', name: '焊工持证项目覆盖', result: 'failed' }
      ]
    } as never,
    nodeFindings: [],
    nodeOutputText: ''
  })
  assert.deepEqual(
    fromNodeRun.checkOutcomes.map((item) => [item.atomicCheckId, item.result]),
    [['AC-R24-01', 'failed']]
  )
}

// 界面上不许出现 material_coverage、EVIDENCE_FILE_OUTSIDE_NODE 这种生码。
{
  const { findingTypeLabel, describeUnsupportedClaim } = await import(
    './workbenchReviewPresentation'
  )
  // findingType 是模型自由填的：同一个意思生产里有四副面孔。
  assert.equal(findingTypeLabel('missing_evidence'), '缺少证据')
  assert.equal(findingTypeLabel('evidence_missing'), '缺少证据')
  assert.equal(findingTypeLabel('MissingEvidence'), '缺少证据')
  assert.equal(findingTypeLabel('证据缺失'), '证据缺失')
  assert.equal(findingTypeLabel('material_coverage'), '母材覆盖范围')
  assert.equal(findingTypeLabel('standard-version-mismatch'), '标准版本不一致')
  // 认不出来的英文 token 退回中文通称，不把原码甩到界面上。
  assert.equal(findingTypeLabel('some_type_nobody_declared'), '审查发现')
  assert.equal(findingTypeLabel(''), '审查发现')
  assert.equal(findingTypeLabel(null), '审查发现')

  assert.equal(
    describeUnsupportedClaim({ claim: 'EVIDENCE_FILE_OUTSIDE_NODE', reason: '' }),
    '引用的文件不属于本节点'
  )
  assert.equal(
    describeUnsupportedClaim({ claim: 'EVIDENCE_REFS_MISSING', reason: '' }),
    '这条结论没有给出证据出处'
  )
  // 真正的资料原文照旧带出来，不能被当成码吃掉。
  assert.equal(describeUnsupportedClaim({ claim: '持证项目', reason: '' }), '「持证项目」待核对')
  assert.equal(
    describeUnsupportedClaim({ claim: '焊接方法', reason: 'not_present_in_supplied_evidence' }),
    '「焊接方法」在已提交资料中未找到'
  )
}

// 模型角色别名是库里的路由键，界面上不该直接印 review-chat。
{
  const { friendlyModelAlias } = await import('./components/auditLabels')
  assert.equal(friendlyModelAlias('review-chat'), '审查模型')
  assert.equal(friendlyModelAlias('project-review-large'), '全工程分析模型')
  // 认不出的别名原样显示：多半是环境里换了模型，原样比猜一个中文名诚实。
  assert.equal(friendlyModelAlias('some-new-model'), 'some-new-model')
  assert.equal(friendlyModelAlias(''), '')
  assert.equal(friendlyModelAlias(null), '')
}

// 后端文案改了，但历史留痕里还存着字段名——展示侧要兜住。
{
  const { withoutFieldNames } = await import('./workbenchReviewPresentation')
  assert.equal(
    withoutFieldNames(
      '模型给出的业务结论缺少证据支持。具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件。'
    ),
    '模型给出的业务结论缺少证据支持。具体是哪些断言没有依据，见本条下方列出的待核对项；请核对原件。'
  )
  assert.equal(withoutFieldNames('没有字段名的正常描述'), '没有字段名的正常描述')
}

// 历史项的摘要也走同一层兜底（节点 29 线上实测：字段名出现在 summary 而不是 description）。
{
  const { selectWorkbenchAiPresentation, buildWorkbenchAiPresentation } = await import(
    './workbenchReviewPresentation'
  )
  const presentation = selectWorkbenchAiPresentation({
    projectAnalysis: buildWorkbenchAiPresentation(null),
    nodeRun: {
      id: 'AIRUN-29',
      status: '完成',
      finishedAt: '2026-09-03 13:55:11',
      suggestion: {
        opinionDraft: '具体是哪些断言没有依据，见本条的 unsupportedClaims；请核对原件。'
      }
    } as never,
    nodeFindings: [],
    nodeOutputText: ''
  })
  assert.ok(!presentation.summary.includes('unsupportedClaims'), presentation.summary)
  assert.ok(presentation.summary.includes('见本条下方列出的待核对项'))
}

// 逐项核查要把「引擎没给分」的事实和它引用的字段带出来，界面才有东西让人核。
{
  const { workbenchCheckOutcomes } = await import('./workbenchReviewPresentation')
  const [outcome] = workbenchCheckOutcomes({
    atomicCheckOutcomes: [
      {
        atomicCheckId: 'AC-R01-02',
        name: '设计许可范围',
        result: 'human_review_required',
        unscoredFacts: [
          {
            factId: 'certificate-1',
            label: 'design_license TS1844171-2028',
            value: 'TS1844171-2028',
            documentVersionId: 'DV-1',
            factPath: 'designDocument.designSealOrganization',
            fields: [
              {
                fieldName: '许可证编号',
                documentVersionId: 'DV-1',
                documentId: 'DOC-1',
                quotedText: 'TS1844171-2028',
                humanCorrected: false
              },
              {
                fieldName: '',
                documentVersionId: 'DV-1',
                documentId: 'DOC-1',
                quotedText: '',
                humanCorrected: false
              }
            ]
          }
        ]
      },
      { atomicCheckId: 'AC-R01-03', name: '有效期', result: 'evidence_insufficient' }
    ]
  })
  assert.equal(outcome.unscoredFacts.length, 1)
  assert.equal(outcome.unscoredFacts[0].fields.length, 1, '没有 fieldName 的条目不显示按钮')
  assert.equal(outcome.unscoredFacts[0].fields[0].documentId, 'DOC-1')
  assert.equal(outcome.unscoredFacts[0].factPath, 'designDocument.designSealOrganization')
  const [, second] = workbenchCheckOutcomes({
    atomicCheckOutcomes: [
      { atomicCheckId: 'AC-R01-02', name: 'x', result: 'passed' },
      { atomicCheckId: 'AC-R01-03', name: 'y', result: 'evidence_insufficient' }
    ]
  })
  assert.deepEqual(second.unscoredFacts, [])
}

// 通过/不通过/需人工都要列出依据与证据：检查码、原因码翻成人话，引文带文件与页码。
{
  const { workbenchCheckOutcomes } = await import('./workbenchReviewPresentation')
  const { friendlyCheckCode, friendlyCheckReason } = await import('./components/auditLabels')
  const [passed, insufficient] = workbenchCheckOutcomes({
    atomicCheckOutcomes: [
      {
        atomicCheckId: 'AC-R01-03',
        name: '有效期',
        result: 'passed',
        checks: [
          {
            tool: 'check_certificate_validity',
            code: 'TS1844171-2028:not_expired_on_reference_date',
            passed: true,
            actual: '2028-01-17',
            expected: '2026-09-12'
          },
          {
            tool: 'check_certificate_validity',
            code: 'TS1844171-2028:scope_covers_required',
            passed: false,
            actual: ['', 'GB1', 'GC1'],
            expected: ['GC2']
          }
        ],
        reason: '',
        facts: [
          {
            factId: 'certificate-1',
            label: 'design_license TS1844171-2028',
            value: 'TS1844171-2028',
            scored: true,
            evidence: [
              {
                evidenceRefId: 'CERTEV-1',
                documentVersionId: 'DV-1',
                fileName: '设计资质.png',
                pageNo: 1,
                quotedText: 'TS1844171-2028',
                source: 'ocr_field',
                confidence: 0,
                confidenceUnavailable: true,
                humanCorrected: false
              },
              {
                evidenceRefId: 'CERTEV-2',
                documentVersionId: 'DV-1',
                fileName: '',
                pageNo: 0,
                quotedText: '平台登记单位：广东政和工程有限公司',
                source: 'cnse_platform',
                confidence: 1,
                confidenceUnavailable: false,
                humanCorrected: false
              },
              {
                evidenceRefId: 'CERTEV-3',
                documentVersionId: 'DV-1',
                fileName: '',
                pageNo: null,
                quotedText: '',
                source: ''
              }
            ]
          }
        ]
      },
      {
        atomicCheckId: 'AC-R01-04',
        name: '范围',
        result: 'evidence_insufficient',
        reason: 'required_pipeline_grades_missing'
      }
    ]
  })
  assert.equal(passed.checks.length, 2)
  assert.equal(passed.checks[0].label, 'TS1844171-2028：证书在参考日未过期')
  assert.equal(passed.checks[1].actual, 'GB1、GC1', '空串去掉，数组用顿号')
  assert.equal(passed.checks[1].expected, 'GC2')
  assert.equal(passed.reason, '')
  assert.equal(passed.facts[0].evidence.length, 2, '没有引文也没有文件名的证据不显示')
  assert.equal(passed.facts[0].evidence[1].source, 'cnse_platform')
  assert.equal(insufficient.reason, '未抽到管道级别（GC1/GC2…）')
  assert.deepEqual(insufficient.checks, [])
  assert.deepEqual(insufficient.facts, [])
  assert.equal(friendlyCheckReason('checkCount=0'), '规则跑了，但节点没有可检的资料')
  assert.equal(friendlyCheckReason('foo_bar_missing'), '缺少 foo_bar', '认不出的码按后缀兜底')
  assert.equal(friendlyCheckCode('scope_covers_GC2'), '许可范围覆盖 GC2')
  assert.equal(friendlyCheckCode('fact_2_confidence'), '事实 2：置信度达标')
  assert.equal(friendlyCheckCode('all_values_equal'), '三处单位名一致')
}

// 符合项要单独成「通过」组并计数：2026-09-12 用户在一键分析节点上看不到任何通过项，
// 因为 document_exist 这类发现被按严重度塞进了「待确认」。
{
  const { buildWorkbenchAiConclusion, workbenchFindingGroup, isPassedFinding } = await import(
    './workbenchReviewPresentation'
  )
  const base = {
    id: 'F-1',
    title: '',
    description: '',
    severity: 'medium',
    severityTone: 'orange',
    severityTag: '',
    typeLabel: '',
    evidenceRefs: [],
    ruleRefs: [],
    unsupportedClaims: [],
    groundingStatus: 'supported'
  }
  const passed = {
    ...base,
    id: 'F-P',
    title: '设计文件已提供',
    findingType: 'document_exist'
  } as never
  const passedCjk = { ...base, id: 'F-C', title: '资质符合', findingType: '符合要求' } as never
  const issue = {
    ...base,
    id: 'F-I',
    title: '缺少方案',
    findingType: 'missing_evidence',
    severity: 'high'
  } as never
  const weak = {
    ...base,
    id: 'F-W',
    title: '已提供',
    findingType: 'document_exist',
    groundingStatus: 'insufficient_evidence'
  } as never
  assert.equal(isPassedFinding(passed), true)
  assert.equal(workbenchFindingGroup(passed), 'passed')
  assert.equal(workbenchFindingGroup(passedCjk), 'passed')
  assert.equal(workbenchFindingGroup(issue), 'needAction')
  assert.equal(workbenchFindingGroup(weak), 'insufficient', '证据不足的「符合」不算通过')
  const onlyPassed = buildWorkbenchAiConclusion({ findings: [passed, passedCjk] })
  assert.equal(onlyPassed.verdict, '未见问题')
  assert.equal(onlyPassed.counts.passed, 2)
  assert.equal(onlyPassed.headline, '2 项核查通过：设计文件已提供')
  assert.equal(onlyPassed.keyFacts[0].text, '设计文件已提供', '只有通过项时关键事实列通过项')
  const mixed = buildWorkbenchAiConclusion({ findings: [passed, issue] })
  assert.equal(mixed.verdict, '需处理')
  assert.deepEqual(mixed.counts, { needAction: 1, confirm: 0, insufficient: 0, passed: 1 })
  assert.equal(mixed.keyFacts[0].text, '缺少方案', '有问题时关键事实先列问题')
}
