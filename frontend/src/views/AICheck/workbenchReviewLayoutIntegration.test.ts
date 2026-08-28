import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('./Workbench.vue', import.meta.url), 'utf-8')
const directorySource = readFileSync(
  new URL('./components/AuditItemDirectory.vue', import.meta.url),
  'utf-8'
)
const aiPanelSourceFile = readFileSync(
  new URL('./components/WorkbenchAiReviewPanel.vue', import.meta.url),
  'utf-8'
)
assert.match(
  source,
  /import WorkbenchAiReviewPanel from '.\/components\/WorkbenchAiReviewPanel\.vue'/,
  '完整工作台应使用独立的 AI 过程与结果组件'
)
assert.match(
  source,
  /<AuditItemDirectory[\s\S]*:items="inspectionReviewAuditItems"/,
  '审计目录应只传入 AI复核和人工结论两个标签'
)

const aiPanelPosition = source.indexOf('<WorkbenchAiReviewPanel')
const aiPanelEnd = source.indexOf('/>', aiPanelPosition) + 2
const humanPanelPosition = source.indexOf('<ReviewDecisionPanel')
assert.ok(aiPanelPosition >= 0, '完整工作台必须渲染 AI 审查区')
assert.ok(humanPanelPosition > aiPanelPosition, '人工审查必须排列在 AI 信息之后')
assert.doesNotMatch(
  source.slice(aiPanelPosition, aiPanelEnd),
  /缺项预审|执行过程|推理过程|BatchRecheckPanel|ElRadioGroup/,
  '完整工作台 AI 区只展示本次与历史结果，不保留模式、执行或推理控件'
)
assert.match(source.slice(aiPanelPosition, aiPanelEnd), /:history="workbenchAiHistory"/)

const aiPanelSource = source.slice(aiPanelPosition - 700, aiPanelPosition + 200)
const humanPanelSource = source.slice(humanPanelPosition - 900, humanPanelPosition + 200)
assert.doesNotMatch(
  aiPanelSource,
  /activeInspectionAuditItem === 'ai_review'/,
  'AI 区不能因当前标签不是 AI复核而卸载'
)
assert.doesNotMatch(
  humanPanelSource,
  /activeInspectionAuditItem === 'human_review'/,
  '人工区不能因当前标签不是人工结论而卸载'
)
assert.match(
  humanPanelSource,
  /:show-ai-suggestion="false"/,
  '人工区不应重复渲染上方已经展示的 AI 建议'
)
assert.match(
  directorySource,
  /audit-item-directory__steps\.is-stacked\s*\{[\s\S]*min-width:\s*0/,
  '两个审查标签不应继续使用七阶段目录的固定宽度并产生横向滚动条'
)
assert.match(
  aiPanelSourceFile,
  /class="ai-error-message">\{\{ presentation\.errorMessage \}\}/,
  'AI失败提示必须直接显示后端返回的原因，不能被重试按钮覆盖'
)
assert.doesNotMatch(aiPanelSourceFile, /执行过程|推理过程|deepThink|executionSteps/)
assert.match(aiPanelSourceFile, /历史 AI 复核结果/)

const humanSectionStart = source.indexOf('id="inspection-audit-panel-human_review"')
const humanSectionEnd = source.indexOf('<section v-if="role === \'owner\'"', humanSectionStart)
const humanSectionSource = source.slice(humanSectionStart, humanSectionEnd)
assert.match(humanSectionSource, /class="overall-conclusion"/)
assert.match(humanSectionSource, /<ReviewDecisionPanel/)
assert.doesNotMatch(
  humanSectionSource,
  /reviewConclusionPoints|class="right-card action-card"|<WorkbenchActionBar/,
  '人工审查只保留总体意见和人工审查表单'
)
assert.match(
  source,
  /\.manual-review-grid\s*\{[\s\S]*grid-template-columns:\s*minmax\(0, 1fr\)/,
  '删除办理操作卡后，人工审查表单应占满单栏宽度'
)
