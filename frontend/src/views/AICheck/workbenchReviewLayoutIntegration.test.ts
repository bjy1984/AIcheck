import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('./Workbench.vue', import.meta.url), 'utf-8')
const aiPanelSourceFile = readFileSync(
  new URL('./components/WorkbenchAiReviewPanel.vue', import.meta.url),
  'utf-8'
)
assert.match(
  source,
  /import WorkbenchAiReviewPanel from '.\/components\/WorkbenchAiReviewPanel\.vue'/,
  '完整工作台应使用独立的 AI 过程与结果组件'
)
assert.doesNotMatch(
  source,
  /<AuditItemDirectory/,
  '节点页不再画「AI复核 → 人工结论」步骤条：状态只在页头说一次（2026-11-04 节点页简化）'
)
assert.match(
  source,
  /class="sub node-review-summary"[\s\S]*nodeReviewHeadline\.parts\.join/,
  '页头标题下一行摘要：AI 到哪了、要我确认几条、缺什么'
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
assert.match(aiPanelSourceFile, /<h2>逐条核对<\/h2>/, 'AI 区只回答「要我逐条核对什么」')
assert.doesNotMatch(
  aiPanelSourceFile,
  /一、AI 审查|ai-conclusion-counts|presentation\.summary }}<\/p>/,
  '不再有四格计数、卡中卡和重复的总述'
)
assert.match(aiPanelSourceFile, /AI 运行记录（\{\{ runCount \}\} 次）/, '运行编号与历史收进底部')
assert.match(
  aiPanelSourceFile,
  /class="ai-error-message">\{\{ presentation\.errorMessage \}\}/,
  'AI失败提示必须直接显示后端返回的原因，不能被重试按钮覆盖'
)
assert.doesNotMatch(aiPanelSourceFile, /执行过程|推理过程|deepThink|executionSteps/)
assert.match(aiPanelSourceFile, /历史 AI 复核结果/)
assert.match(
  aiPanelSourceFile,
  /class="ai-status-banner"[\s\S]*class="ai-status-banner__icon"[\s\S]*class="ai-status-banner__content"/,
  '失败态应使用紧凑且分层明确的状态卡，避免整条红色警告占满内容区'
)
assert.match(
  aiPanelSourceFile,
  /:class="\['ai-current-result', `is-\$\{presentation\.statusTone\}`\]"/,
  '本次复核主卡应按状态提供克制的视觉区分'
)
assert.match(
  aiPanelSourceFile,
  /class="ai-history-list ai-history-timeline"/,
  '历史结果应使用轻量时间线层级，避免多个厚重边框卡片堆叠'
)
assert.match(
  aiPanelSourceFile,
  /@media \(width <= 720px\)[\s\S]*\.ai-panel-head[\s\S]*align-items: flex-start/,
  'AI 审查面板在窄屏下应自动改为纵向信息布局'
)

const humanSectionStart = source.indexOf('id="inspection-audit-panel-human_review"')
const humanSectionEnd = source.indexOf('</aside>', humanSectionStart)
const humanSectionSource = source.slice(humanSectionStart, humanSectionEnd)
assert.doesNotMatch(
  humanSectionSource,
  /class="overall-conclusion"|二、人工审查/,
  '「总体意见」那句就是页头摘要，不再单占一张卡'
)
assert.match(humanSectionSource, /<ReviewDecisionPanel/)
assert.match(humanSectionSource, /:satisfied-blocked="!readyForAiFormal"/)
assert.match(humanSectionSource, /@save-and-return="handleSaveAndReturnCorrection"/)
assert.match(
  source,
  /\.node-review-aside \{[\s\S]*position: sticky/,
  '结论固定在右栏，拉到哪都看得到'
)
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
