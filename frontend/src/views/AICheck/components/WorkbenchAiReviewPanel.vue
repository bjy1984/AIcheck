<script setup lang="ts">
import { ElAlert, ElTag } from 'element-plus'

import type { WorkbenchAiFinding, WorkbenchAiPresentation } from '../workbenchReviewPresentation'
import AuditStatusTag from './AuditStatusTag.vue'

defineProps<{
  presentation: WorkbenchAiPresentation
  history: WorkbenchAiPresentation[]
}>()

const emit = defineEmits<{
  openFile: [fileId: string]
}>()

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
        <div class="sub">本次及历史 AI 复核结果</div>
      </div>
      <div class="ai-run-meta">
        <AuditStatusTag :tone="presentation.statusTone" round>
          {{ presentation.statusLabel }}
        </AuditStatusTag>
        <small v-if="presentation.meta">{{ presentation.meta }}</small>
      </div>
    </div>

    <div class="card-body ai-panel-body">
      <ElAlert
        v-if="presentation.errorMessage"
        type="error"
        :closable="false"
        show-icon
        :title="presentation.statusLabel"
      >
        <p class="ai-error-message">{{ presentation.errorMessage }}</p>
      </ElAlert>

      <article class="ai-current-result" aria-label="本次 AI 复核结果">
        <div class="ai-current-result-head">
          <div>
            <span>本次复核</span>
            <strong>{{ presentation.sourceLabel }}</strong>
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
      </article>

      <section class="ai-history" aria-label="历史 AI 复核结果">
        <div class="ai-history-head">
          <div>
            <h3>历史 AI 复核结果</h3>
            <p>按复核时间倒序排列</p>
          </div>
          <span>{{ history.length }} 次</span>
        </div>
        <div v-if="history.length" class="ai-history-list">
          <article v-for="item in history" :key="item.runId" class="ai-history-item">
            <div class="ai-history-item-head">
              <div>
                <strong>{{ item.sourceLabel }}</strong>
                <small>{{ item.meta || item.activityAt }}</small>
              </div>
              <AuditStatusTag :tone="item.statusTone" round>
                {{ item.resultLabel }}
              </AuditStatusTag>
            </div>
            <p>{{ item.summary }}</p>
          </article>
        </div>
        <p v-else class="ai-history-empty">暂无更早的 AI 复核结果</p>
      </section>
    </div>
  </section>
</template>

<style scoped>
.workbench-ai-review-panel {
  scroll-margin-top: 190px;
}

.ai-panel-head,
.ai-current-result-head,
.ai-history-head,
.ai-history-item-head {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
}

.ai-run-meta {
  display: flex;
  gap: 5px;
  align-items: flex-end;
  flex-direction: column;
}

.ai-run-meta small,
.ai-history-item small,
.ai-history-head p {
  color: var(--aicheck-text-subtle, #667085);
}

.ai-panel-body {
  display: grid;
  gap: 18px;
}

.ai-error-message {
  margin: 0;
  line-height: 1.6;
}

.ai-current-result {
  padding: 18px 20px;
  background: linear-gradient(135deg, #f5f9ff, #fff);
  border: 1px solid #dce7f6;
  border-radius: 12px;
}

.ai-current-result-head > div,
.ai-history-item-head > div {
  display: grid;
  gap: 3px;
}

.ai-current-result-head span {
  font-size: 12px;
  color: var(--aicheck-text-subtle, #667085);
}

.ai-result-summary {
  margin: 14px 0 0;
  font-size: 15px;
  line-height: 1.8;
  color: #27364b;
}

.ai-result-findings {
  display: grid;
  margin-top: 16px;
  border-top: 1px solid #e3ebf5;
}

.ai-result-findings > article {
  padding: 15px 0;
  border-bottom: 1px solid #e8eef6;
}

.ai-result-findings h3,
.ai-result-findings p {
  margin: 8px 0 0;
}

.ai-finding-head,
.ai-reference-row,
.ai-rule-list {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
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

.ai-rule-list span {
  padding: 3px 8px;
  font-size: 12px;
  color: #52647a;
  background: #edf2f8;
  border-radius: 999px;
}

.ai-history {
  padding-top: 2px;
}

.ai-history-head h3,
.ai-history-head p,
.ai-history-item p {
  margin: 0;
}

.ai-history-head h3 {
  font-size: 15px;
}

.ai-history-head p {
  margin-top: 2px;
  font-size: 12px;
}

.ai-history-head > span {
  padding: 2px 9px;
  font-size: 12px;
  color: #52647a;
  background: #f0f4f9;
  border-radius: 999px;
}

.ai-history-list {
  display: grid;
  gap: 10px;
  margin-top: 12px;
}

.ai-history-item {
  padding: 13px 15px;
  background: #fff;
  border: 1px solid #e2e9f3;
  border-radius: 10px;
}

.ai-history-item p {
  margin-top: 8px;
  line-height: 1.65;
  color: #48566a;
}

.ai-history-empty {
  padding: 18px;
  margin: 12px 0 0;
  color: var(--aicheck-text-subtle, #667085);
  text-align: center;
  background: #f8fafc;
  border-radius: 10px;
}
</style>
