<script setup lang="ts">
import { computed } from 'vue'
import { ElTag } from 'element-plus'
import type { EvidenceLink } from '@/types/aicheck'
import type { ReviewBProjectAnalysisResult } from '@/types/ai-review-b'
import {
  projectAnalysisResultTagType,
  resolveProjectAnalysisEvidenceLink
} from '../projectAnalysisConversation'
import ReviewMarkdownText from './ReviewMarkdownText.vue'

const props = defineProps<{
  result?: ReviewBProjectAnalysisResult
  evidenceLinks: EvidenceLink[]
}>()
const emit = defineEmits<{ 'open-evidence': [evidence: EvidenceLink] }>()
const labels: Record<string, string> = {
  supported: '证据支持',
  partially_supported: '部分证据支持',
  insufficient_evidence: '证据不足',
  conflict: '证据冲突',
  mismatch: '不一致'
}
const explanations: Record<string, string> = {
  supported: '现有证据支持这项判断，请看过原文后再确认。',
  partially_supported: '目前只有部分证据能支持判断，还有内容需要你核对。',
  insufficient_evidence: '这次还无法作出明确判断，原因请看下面的说明。',
  conflict: '现有证据有互相矛盾的地方，需要你核对原文。',
  mismatch: '比对结果有不一致的地方，请查看下面的说明。'
}
const findings = computed(() => props.result?.findingDrafts || [])
const label = computed(() => labels[props.result?.reviewResult || ''] || '待人工确认')
const records = (value: unknown): Record<string, unknown>[] =>
  Array.isArray(value)
    ? value.filter(
        (item): item is Record<string, unknown> =>
          !!item && typeof item === 'object' && !Array.isArray(item)
      )
    : []
const severityLabel = (value: unknown) =>
  ({ critical: '严重', high: '高', medium: '中', low: '低', info: '提示' })[String(value)] ||
  '未标注'
const severityType = (value: unknown) =>
  ['critical', 'high'].includes(String(value)) ? 'danger' : value === 'medium' ? 'warning' : 'info'
const evidenceLabel = (evidence: Record<string, unknown>) =>
  [evidence.fileName || '来源文件', evidence.pageNo ? `第 ${evidence.pageNo} 页` : '']
    .filter(Boolean)
    .join(' · ')
const resolveEvidence = (evidence: Record<string, unknown>) =>
  resolveProjectAnalysisEvidenceLink(evidence, props.evidenceLinks)
const openEvidence = (evidence: Record<string, unknown>) => {
  const resolved = resolveEvidence(evidence)
  if (resolved) emit('open-evidence', resolved)
}
</script>

<template>
  <section class="review-result" aria-label="当前节点审查结果">
    <header class="result-heading">
      <div
        ><p class="eyebrow">全工程分析 · 当前节点</p><h3>{{ label }}</h3></div
      >
      <ElTag :type="projectAnalysisResultTagType(result?.reviewResult)" effect="plain"
        >AI 建议 · 待你确认</ElTag
      >
    </header>
    <p class="review-notice">{{
      explanations[result?.reviewResult || ''] || '这次结果还需要你确认，请先看下面的说明和原文。'
    }}</p>
    <div class="finding-heading"
      ><h4>需要你确认的事项</h4><span>共 {{ findings.length }} 项</span></div
    >
    <ol v-if="findings.length" class="finding-list">
      <li v-for="(finding, index) in findings" :key="`${finding.id || 'finding'}-${index}`">
        <div class="finding-title"
          ><span class="finding-number">{{ index + 1 }}</span
          ><h4>{{ finding.title || '待核验事项' }}</h4
          ><ElTag :type="severityType(finding.severity)" size="small"
            >关注程度：{{ severityLabel(finding.severity) }}</ElTag
          ></div
        >
        <p v-if="finding.checklistVerdict" class="verdict"
          >检查项结论：{{ finding.checklistVerdict }}</p
        >
        <p v-if="finding.suggestedAction === 'request_correction'" class="next-step">
          <strong>建议处理</strong>先核对问题和原文，确认后再发起整改。
        </p>
        <details class="finding-detail">
          <summary
            >看看原因和依据<span class="reference-count">{{
              records(finding.evidenceRefs).length
                ? `（${records(finding.evidenceRefs).length} 处引用）`
                : '（暂未附原文）'
            }}</span></summary
          >
          <div class="detail-body">
            <h5>问题说明</h5
            ><ReviewMarkdownText
              :content="String(finding.description || '这项没有附上详细说明，需要你进一步核对。')"
            />
            <h5>证据依据</h5>
            <p v-if="!records(finding.evidenceRefs).length"
              >这项没有附上原文引用，还需要补充或核对依据。</p
            >
            <div
              v-for="(evidence, evidenceIndex) in records(finding.evidenceRefs)"
              :key="evidenceIndex"
              class="evidence-item"
            >
              <button v-if="resolveEvidence(evidence)" type="button" @click="openEvidence(evidence)"
                >{{ evidenceLabel(evidence) }} · 查看原文</button
              >
              <p v-else>{{ evidenceLabel(evidence) }} · 这条引用暂时打不开，请到文件中核对</p>
              <blockquote v-if="evidence.quotedText">{{ evidence.quotedText }}</blockquote>
            </div>
            <template v-if="records(finding.ruleRefs).length"
              ><h5>规则依据</h5
              ><ul
                ><li v-for="(rule, ruleIndex) in records(finding.ruleRefs)" :key="ruleIndex">{{
                  rule.text || rule.ruleCode || rule.source || '规则依据'
                }}</li></ul
              ></template
            >
          </div>
        </details>
      </li>
    </ol>
    <p v-else class="empty-notice">这次没有列出具体事项，但还不能据此认定通过，请你确认。</p>
    <details class="run-details"
      ><summary>查看本次审查记录</summary
      ><dl
        ><dt>完成时间</dt><dd>{{ result?.finishedAt || '未记录' }}</dd
        ><dt>任务编号</dt><dd>{{ result?.reviewRunId || '未记录' }}</dd
        ><dt>原始结果状态</dt><dd>{{ result?.reviewResult || '未记录' }}</dd></dl
      ></details
    >
  </section>
</template>

<style scoped>
.review-result {
  padding: 20px;
  color: var(--el-text-color-primary);
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color);
  border-radius: 12px;
  overflow-wrap: anywhere;
}

.result-heading,
.finding-heading,
.finding-title {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}

.result-heading,
.finding-heading {
  justify-content: space-between;
}

h3,
h4,
h5,
p {
  margin: 0;
}

h3 {
  margin-top: 6px;
  font-size: 22px;
}

h4 {
  font-size: 15px;
}

h5 {
  margin: 16px 0 8px;
  font-size: 14px;
}

.eyebrow,
.finding-heading > span {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.review-notice {
  margin: 12px 0 24px;
  font-size: 14px;
  line-height: 1.6;
  color: var(--el-text-color-regular);
}

.finding-list {
  display: grid;
  gap: 12px;
  padding: 0;
  margin: 12px 0;
  list-style: none;
}

.finding-list > li {
  padding: 16px;
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
}

.finding-title h4 {
  flex: 1;
  min-width: 120px;
  line-height: 1.6;
}

.finding-number {
  display: grid;
  width: 28px;
  height: 28px;
  font-size: 13px;
  background: var(--el-fill-color);
  border-radius: 50%;
  place-items: center;
}

.next-step,
.verdict {
  margin-top: 12px;
  font-size: 14px;
  line-height: 1.7;
}

.next-step strong {
  margin-right: 12px;
}

summary,
button {
  min-height: 44px;
  font: inherit;
  font-size: 14px;
  cursor: pointer;
}

summary {
  padding: 12px 0;
  box-sizing: border-box;
}

summary:focus-visible,
button:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: 3px;
}

.finding-detail {
  margin-top: 8px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.detail-body {
  font-size: 14px;
  line-height: 1.75;
  color: var(--el-text-color-regular);
}

.detail-body > h5:first-child {
  margin-top: 0;
}

.evidence-item {
  margin-top: 8px;
}

button {
  padding: 8px 12px;
  color: var(--el-color-primary);
  text-align: left;
  background: var(--el-color-primary-light-9);
  border: 1px solid var(--el-color-primary-light-7);
  border-radius: 6px;
  overflow-wrap: anywhere;
}

blockquote {
  padding-left: 12px;
  margin: 8px 0;
  white-space: pre-wrap;
  border-left: 3px solid var(--el-border-color);
}

.run-details {
  margin-top: 16px;
  color: var(--el-text-color-secondary);
  border-top: 1px solid var(--el-border-color-lighter);
}

dl {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 8px 16px;
  font-size: 13px;
}

dd {
  margin: 0;
}

.empty-notice {
  padding: 16px 0;
  line-height: 1.7;
}
</style>
