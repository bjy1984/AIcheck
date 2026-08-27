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
const projectAnalysisControlSource = readFileSync(
  new URL('./components/ProjectAnalysisControl.vue', import.meta.url),
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
const aiPanelEnd = source.indexOf('</WorkbenchAiReviewPanel>', aiPanelPosition)
const humanPanelPosition = source.indexOf('<ReviewDecisionPanel')
assert.ok(aiPanelPosition >= 0, '完整工作台必须渲染 AI 审查区')
assert.ok(humanPanelPosition > aiPanelPosition, '人工审查必须排列在 AI 信息之后')
assert.doesNotMatch(
  source.slice(aiPanelPosition, aiPanelEnd),
  /<NodeReviewTimeline/,
  '旧审查历史不能铺在当前 AI 过程和结果之前'
)

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
assert.match(
  projectAnalysisControlSource,
  /defineExpose\(\{ open \}\)/,
  '一键分析控件应向工作台暴露打开抽屉的方法'
)
assert.match(
  source,
  /@retry="handleWorkbenchAiRetry"/,
  '全工程分析失败后的重试必须回到一键分析入口，不能误发节点复核'
)
assert.match(
  source,
  /:retry-label="projectAnalysisIsDisplayed \? '查看一键分析状态' : '重新发起 AI 审查'"/,
  '同一快照不能伪装成可直接重试；全工程失败时应引导用户回到一键分析状态入口'
)
