<script setup lang="ts">
import { CircleCloseFilled } from '@element-plus/icons-vue'
import { ElIcon, ElTag } from 'element-plus'

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
      <div v-if="presentation.errorMessage" class="ai-status-banner" role="alert">
        <div class="ai-status-banner__icon" aria-hidden="true">
          <ElIcon><CircleCloseFilled /></ElIcon>
        </div>
        <div class="ai-status-banner__content">
          <strong>{{ presentation.statusLabel }}</strong>
          <p class="ai-error-message">{{ presentation.errorMessage }}</p>
        </div>
      </div>

      <article
        :class="['ai-current-result', `is-${presentation.statusTone}`]"
        aria-label="本次 AI 复核结果"
      >
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
        <div v-if="history.length" class="ai-history-list ai-history-timeline">
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
  overflow: hidden;
  border-color: var(--aicheck-border-soft, #e5ecf6);
  border-radius: 12px;
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

.ai-panel-head {
  min-height: 62px;
  padding: 14px 20px;
  background: linear-gradient(105deg, #f8fbff 0%, #f3f7fd 100%);
}

.ai-panel-head h2 {
  margin: 0;
  font-size: 18px;
  line-height: 26px;
  color: var(--aicheck-text-strong, #172033);
}

.ai-panel-head .sub {
  margin-top: 2px;
  font-size: 12px;
  color: var(--aicheck-text-muted, #52647d);
}

.ai-run-meta {
  display: flex;
  max-width: 52%;
  gap: 6px;
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
  padding: 18px 20px 20px;
  gap: 14px;
}

.ai-status-banner {
  display: grid;
  min-height: 58px;
  padding: 11px 14px;
  color: var(--aicheck-danger, #b42318);
  background: linear-gradient(100deg, #fff5f4 0%, #fffafa 100%);
  border: 1px solid #f2d2cf;
  border-radius: 10px;
  box-shadow: inset 3px 0 0 var(--aicheck-danger, #b42318);
  grid-template-columns: 30px minmax(0, 1fr);
  align-items: start;
  gap: 10px;
}

.ai-status-banner__icon {
  display: grid;
  width: 28px;
  height: 28px;
  margin-top: 1px;
  font-size: 18px;
  color: #fff;
  background: var(--aicheck-danger, #b42318);
  border-radius: 50%;
  place-items: center;
}

.ai-status-banner__content {
  min-width: 0;
}

.ai-status-banner__content strong {
  display: block;
  font-size: 14px;
  line-height: 22px;
}

.ai-error-message {
  margin: 2px 0 0;
  font-size: 13px;
  line-height: 20px;
  color: #8f352e;
}

.ai-current-result {
  --ai-result-accent: var(--aicheck-primary, #1f66d8);

  padding: 20px;
  background: linear-gradient(135deg, #f7faff 0%, #fff 58%);
  border: 1px solid #dbe6f4;
  border-radius: 12px;
  box-shadow:
    inset 3px 0 0 var(--ai-result-accent),
    0 6px 18px rgb(31 72 125 / 6%);
}

.ai-current-result.is-red {
  --ai-result-accent: var(--aicheck-danger, #b42318);

  background: linear-gradient(135deg, #fff9f8 0%, #fff 58%);
  border-color: #ecd9d7;
}

.ai-current-result.is-orange {
  --ai-result-accent: var(--aicheck-warning, #b45309);

  background: linear-gradient(135deg, #fffaf2 0%, #fff 58%);
  border-color: #eee0c8;
}

.ai-current-result.is-green {
  --ai-result-accent: var(--aicheck-success, #16803c);

  background: linear-gradient(135deg, #f6fcf8 0%, #fff 58%);
  border-color: #d9eade;
}

.ai-current-result.is-gray {
  --ai-result-accent: var(--aicheck-text-subtle, #667085);

  background: linear-gradient(135deg, #f8fafc 0%, #fff 58%);
}

.ai-current-result-head > div,
.ai-history-item-head > div {
  display: grid;
  gap: 3px;
}

.ai-current-result-head span {
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0.02em;
  color: var(--aicheck-text-subtle, #667085);
}

.ai-current-result-head strong {
  font-size: 16px;
  line-height: 24px;
  color: var(--aicheck-text-strong, #172033);
}

.ai-result-summary {
  max-width: 960px;
  margin: 13px 0 0;
  font-size: 14px;
  line-height: 1.75;
  color: #27364b;
}

.ai-result-findings {
  display: grid;
  margin-top: 16px;
  border-top: 1px solid #e3ebf5;
}

.ai-result-findings > article {
  padding: 16px 2px;
  border-bottom: 1px solid #e8eef6;
}

.ai-result-findings > article:last-child {
  padding-bottom: 0;
  border-bottom: 0;
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
  padding: 3px 7px;
  font-size: 12px;
  color: var(--aicheck-primary, #1f66d8);
  cursor: pointer;
  background: #eef5ff;
  border: 0;
  border-radius: 6px;
}

.ai-rule-list span {
  padding: 3px 8px;
  font-size: 12px;
  color: #52647a;
  background: #edf2f8;
  border-radius: 999px;
}

.ai-history {
  padding: 17px 4px 0;
  margin-top: 2px;
  border-top: 1px solid var(--aicheck-border-soft, #e5ecf6);
}

.ai-history-head h3,
.ai-history-head p,
.ai-history-item p {
  margin: 0;
}

.ai-history-head h3 {
  font-size: 14px;
  font-weight: 600;
  line-height: 22px;
  color: var(--aicheck-text-strong, #172033);
}

.ai-history-head p {
  margin-top: 2px;
  font-size: 12px;
}

.ai-history-head > span {
  padding: 2px 8px;
  font-size: 12px;
  color: #52647a;
  background: #f0f4f9;
  border-radius: 999px;
}

.ai-history-list {
  display: grid;
  margin: 10px 0 0 5px;
}

.ai-history-timeline {
  padding-left: 16px;
  border-left: 1px solid #dce5f0;
}

.ai-history-item {
  position: relative;
  padding: 13px 10px 14px 2px;
  background: transparent;
  border-bottom: 1px solid #e8eef5;
}

.ai-history-item::before {
  position: absolute;
  top: 20px;
  left: -21px;
  width: 9px;
  height: 9px;
  background: #fff;
  border: 2px solid #9db5d3;
  border-radius: 50%;
  content: '';
}

.ai-history-item:last-child {
  padding-bottom: 4px;
  border-bottom: 0;
}

.ai-history-item p {
  margin-top: 6px;
  font-size: 13px;
  line-height: 1.7;
  color: #48566a;
}

.ai-history-item small {
  overflow: hidden;
  font-size: 12px;
  line-height: 18px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ai-history-empty {
  padding: 15px;
  margin: 10px 0 0;
  color: var(--aicheck-text-subtle, #667085);
  text-align: center;
  background: #f8fafc;
  border-radius: 10px;
}

@media (width <= 720px) {
  .ai-panel-head,
  .ai-current-result-head,
  .ai-history-item-head {
    align-items: flex-start;
    flex-direction: column;
  }

  .ai-run-meta {
    max-width: 100%;
    align-items: flex-start;
  }

  .ai-run-meta small {
    overflow-wrap: anywhere;
  }

  .ai-panel-body {
    padding: 14px;
  }

  .ai-current-result {
    padding: 16px;
  }

  .ai-history-item-head {
    gap: 8px;
  }
}
</style>
