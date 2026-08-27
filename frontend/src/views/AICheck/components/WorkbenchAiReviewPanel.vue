<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElAlert, ElButton, ElCollapse, ElCollapseItem, ElTag } from 'element-plus'

import type { WorkbenchAiFinding, WorkbenchAiPresentation } from '../workbenchReviewPresentation'
import AuditStatusTag from './AuditStatusTag.vue'

type ExecutionStep = {
  title: string
  input: string
  feedback: string
  tools: string[]
  status: string
}

const props = defineProps<{
  presentation: WorkbenchAiPresentation
  executionSummary: string
  executionSteps: ExecutionStep[]
  reasoningText?: string
  deepThinkText?: string
  loading?: boolean
  retryLabel?: string
}>()

const emit = defineEmits<{
  retry: []
  openFile: [fileId: string]
}>()

const executionExpanded = ref(false)
const technicalPanels = ref<string[]>([])
const recentSteps = computed(() => props.executionSteps.slice(-3))

const severityType = (finding: WorkbenchAiFinding) => {
  if (finding.severity === 'critical' || finding.severity === 'high') return 'danger'
  if (finding.severity === 'medium') return 'warning'
  return 'info'
}

const evidenceLabel = (evidence: Record<string, unknown>) =>
  [evidence.fileName || evidence.fileId, evidence.pageNo ? `第 ${evidence.pageNo} 页` : '']
    .filter(Boolean)
    .join(' · ')

const ruleLabel = (rule: Record<string, unknown>) => String(rule.text || rule.source || '规则依据')
</script>

<template>
  <section id="inspection-audit-panel-ai_review" class="card workbench-ai-review-panel">
    <div class="card-head ai-panel-head">
      <div>
        <h2>一、AI 审查</h2>
        <div class="sub">AI 执行过程、模型结果及证据依据</div>
      </div>
      <div class="ai-run-meta">
        <AuditStatusTag :tone="presentation.statusTone" round>
          {{ presentation.statusLabel }}
        </AuditStatusTag>
        <small v-if="presentation.meta">{{ presentation.meta }}</small>
      </div>
    </div>

    <div class="card-body ai-panel-body">
      <slot name="actions"></slot>

      <ElAlert
        v-if="presentation.errorMessage"
        type="error"
        :closable="false"
        show-icon
        :title="presentation.statusLabel"
      >
        <p class="ai-error-message">{{ presentation.errorMessage }}</p>
        <ElButton
          v-if="presentation.canRetry"
          :loading="loading"
          type="danger"
          plain
          @click="emit('retry')"
        >
          {{ retryLabel || '重新发起 AI 审查' }}
        </ElButton>
      </ElAlert>

      <slot name="alerts"></slot>

      <section :class="['ai-execution-activity', { 'is-active': presentation.running }]">
        <button
          type="button"
          class="ai-execution-summary"
          :aria-expanded="executionExpanded"
          @click="executionExpanded = !executionExpanded"
        >
          <span class="ai-execution-state" aria-hidden="true">
            <span v-if="presentation.running" class="ai-execution-spinner"></span>
            <span v-else>✓</span>
          </span>
          <span class="ai-execution-copy">
            <strong>执行过程</strong>
            <small>{{ executionSummary }}</small>
          </span>
          <span :class="['ai-execution-chevron', { 'is-open': executionExpanded }]">⌄</span>
        </button>

        <ol v-if="!executionExpanded && presentation.running" class="ai-execution-preview">
          <li v-for="step in recentSteps" :key="step.title">
            {{ step.title }} · {{ step.feedback }}
          </li>
        </ol>

        <ol v-if="executionExpanded" class="ai-execution-steps">
          <li v-for="(step, index) in executionSteps" :key="step.title">
            <span class="ai-step-index">{{ index + 1 }}</span>
            <div>
              <div class="ai-step-head">
                <strong>{{ step.title }}</strong>
                <ElTag size="small" effect="plain">{{ step.status }}</ElTag>
              </div>
              <p><b>输入：</b>{{ step.input }}</p>
              <p><b>反馈：</b>{{ step.feedback }}</p>
              <div v-if="step.tools.length" class="ai-step-tools">
                <span v-for="tool in step.tools" :key="tool">{{ tool }}</span>
              </div>
            </div>
          </li>
        </ol>
      </section>

      <article class="ai-assistant-message" aria-label="AI 审查结果">
        <div class="ai-assistant-avatar" aria-hidden="true">AI</div>
        <div class="ai-assistant-body">
          <div class="ai-result-head">
            <div>
              <strong>{{ presentation.sourceLabel }}</strong>
              <small>所有 AI 结果均需人工确认</small>
            </div>
            <AuditStatusTag :tone="presentation.statusTone" round>
              {{ presentation.resultLabel }}
            </AuditStatusTag>
          </div>
          <p class="ai-result-summary">{{ presentation.summary }}</p>

          <div v-if="presentation.findings.length" class="ai-result-findings">
            <article v-for="finding in presentation.findings" :key="finding.id">
              <div class="ai-finding-head">
                <ElTag size="small" effect="plain">{{ finding.typeLabel }}</ElTag>
                <ElTag v-if="finding.severityLabel" size="small" :type="severityType(finding)">
                  严重度 {{ finding.severityLabel }}
                </ElTag>
                <span v-if="finding.confidence !== undefined">
                  置信度 {{ Math.round(finding.confidence * 100) }}%
                </span>
              </div>
              <h3>{{ finding.title || '审查发现' }}</h3>
              <p>{{ finding.description }}</p>
              <div v-if="finding.evidenceRefs.length" class="ai-reference-row">
                <button
                  v-for="(evidence, index) in finding.evidenceRefs"
                  :key="String(evidence.fileId || index)"
                  type="button"
                  @click="emit('openFile', String(evidence.fileId || ''))"
                >
                  {{ evidenceLabel(evidence) }}
                </button>
              </div>
              <div v-if="finding.ruleRefs.length" class="ai-rule-list">
                <span v-for="(rule, index) in finding.ruleRefs" :key="index">
                  {{ ruleLabel(rule) }}
                </span>
              </div>
            </article>
          </div>

          <ElCollapse
            v-if="reasoningText || deepThinkText"
            v-model="technicalPanels"
            class="ai-technical-details"
          >
            <ElCollapseItem name="reasoning" title="查看推理过程与模型执行详情">
              <section v-if="reasoningText">
                <strong>推理过程</strong>
                <pre>{{ reasoningText }}</pre>
              </section>
              <section v-if="deepThinkText">
                <strong>DeepThink 内容</strong>
                <pre>{{ deepThinkText }}</pre>
              </section>
            </ElCollapseItem>
          </ElCollapse>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.workbench-ai-review-panel {
  scroll-margin-top: 190px;
}

.ai-panel-head,
.ai-run-meta,
.ai-result-head,
.ai-step-head {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
}

.ai-run-meta {
  align-items: flex-end;
  flex-direction: column;
}

.ai-run-meta small,
.ai-result-head small {
  color: var(--aicheck-text-subtle, #667085);
}

.ai-panel-body {
  display: grid;
  gap: 16px;
}

.ai-error-message {
  margin: 0 0 10px;
  line-height: 1.6;
}

.ai-execution-activity,
.ai-assistant-message {
  border: 1px solid var(--aicheck-border, #dce5f2);
  border-radius: 12px;
}

.ai-execution-activity.is-active {
  border-color: color-mix(in srgb, var(--aicheck-primary, #1f66d8) 45%, white);
}

.ai-execution-summary {
  display: flex;
  width: 100%;
  padding: 14px 16px;
  color: inherit;
  text-align: left;
  cursor: pointer;
  background: transparent;
  border: 0;
  align-items: center;
  gap: 12px;
}

.ai-execution-state {
  display: grid;
  width: 28px;
  height: 28px;
  color: #fff;
  background: var(--aicheck-primary, #1f66d8);
  border-radius: 50%;
  place-items: center;
}

.ai-execution-spinner {
  width: 13px;
  height: 13px;
  border: 2px solid rgb(255 255 255 / 45%);
  border-top-color: #fff;
  border-radius: 50%;
  animation: ai-spin 0.8s linear infinite;
}

.ai-execution-copy {
  display: grid;
  flex: 1;
  gap: 2px;
}

.ai-execution-copy small {
  color: var(--aicheck-text-subtle, #667085);
}

.ai-execution-chevron {
  transition: transform 0.2s ease;
}

.ai-execution-chevron.is-open {
  transform: rotate(180deg);
}

.ai-execution-preview,
.ai-execution-steps {
  padding: 0 16px 14px 56px;
  margin: 0;
}

.ai-execution-preview li {
  margin-top: 5px;
  color: var(--aicheck-text-subtle, #667085);
}

.ai-execution-steps {
  display: grid;
  gap: 12px;
  list-style: none;
}

.ai-execution-steps > li {
  display: grid;
  grid-template-columns: 28px 1fr;
  gap: 10px;
}

.ai-step-index {
  display: grid;
  width: 24px;
  height: 24px;
  color: var(--aicheck-primary, #1f66d8);
  background: #eaf2ff;
  border-radius: 50%;
  place-items: center;
}

.ai-execution-steps p {
  margin: 6px 0 0;
  line-height: 1.6;
}

.ai-step-tools,
.ai-reference-row,
.ai-rule-list,
.ai-finding-head {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.ai-step-tools span,
.ai-rule-list span {
  padding: 3px 8px;
  font-size: 12px;
  color: #52647a;
  background: #f3f6fa;
  border-radius: 999px;
}

.ai-assistant-message {
  display: grid;
  padding: 18px;
  background: linear-gradient(135deg, #f8fbff, #fff);
  grid-template-columns: 38px 1fr;
  gap: 12px;
}

.ai-assistant-avatar {
  display: grid;
  width: 36px;
  height: 36px;
  font-size: 12px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(145deg, #4f8df7, #1f66d8);
  border-radius: 10px;
  place-items: center;
}

.ai-assistant-body {
  min-width: 0;
}

.ai-result-head > div {
  display: grid;
  gap: 2px;
}

.ai-result-summary {
  margin: 12px 0 0;
  line-height: 1.75;
}

.ai-result-findings {
  display: grid;
  gap: 12px;
  margin-top: 14px;
}

.ai-result-findings > article {
  padding: 14px;
  background: #fff;
  border: 1px solid #e2e9f3;
  border-radius: 10px;
}

.ai-result-findings h3,
.ai-result-findings p {
  margin: 8px 0 0;
}

.ai-finding-head {
  align-items: center;
}

.ai-finding-head > span {
  font-size: 12px;
  color: var(--aicheck-text-subtle, #667085);
}

.ai-reference-row,
.ai-rule-list {
  margin-top: 10px;
}

.ai-reference-row button {
  padding: 3px 0;
  color: var(--aicheck-primary, #1f66d8);
  cursor: pointer;
  background: transparent;
  border: 0;
}

.ai-technical-details {
  margin-top: 14px;
}

.ai-technical-details section + section {
  margin-top: 12px;
}

.ai-technical-details pre {
  max-height: 260px;
  padding: 12px;
  overflow: auto;
  line-height: 1.65;
  white-space: pre-wrap;
  background: #f7f9fc;
  border-radius: 8px;
}

@keyframes ai-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
