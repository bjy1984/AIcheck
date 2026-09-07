<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { CircleCloseFilled } from '@element-plus/icons-vue'
import { ElButton, ElIcon } from 'element-plus'

import {
  buildWorkbenchAiConclusion,
  workbenchFindingDisplay,
  type WorkbenchAiFinding,
  type WorkbenchAiFindingGroupKey,
  type WorkbenchAiPresentation
} from '../workbenchReviewPresentation'
import AuditStatusTag from './AuditStatusTag.vue'
import CertificateVerificationCard from './CertificateVerificationCard.vue'

const props = withDefaults(
  defineProps<{
    presentation: WorkbenchAiPresentation
    history: WorkbenchAiPresentation[]
    /** 监检可操作（采纳/驳回/其实有依据/补充发现）。施工方与只读视图为 false。 */
    canAct?: boolean
    acting?: boolean
    /** 本次会话里已记录的发现级反馈，键为 findingId 或 `${findingId}::${claim}`。 */
    decisions?: Record<string, 'accept' | 'reject' | 'supported'>
  }>(),
  { canAct: false, acting: false, decisions: () => ({}) }
)

const emit = defineEmits<{
  openFile: [fileId: string]
  findingDecision: [finding: WorkbenchAiFinding, decision: 'accept' | 'reject']
  claimSupported: [finding: WorkbenchAiFinding, claim: string]
  supplementFinding: []
  returnCorrection: [finding: WorkbenchAiFinding]
}>()

/**
 * 结论卡只在"已完成"的运行上推导：分析中/失败时没有可靠的发现集合，
 * 推导出的"未见问题"会误导——那时只显示状态横幅。
 */
const conclusion = computed(() =>
  props.presentation.running || props.presentation.errorMessage
    ? undefined
    : buildWorkbenchAiConclusion({
        findings: props.presentation.findings,
        deterministicResult: props.presentation.deterministicResult
      })
)

const GROUP_META: Record<
  WorkbenchAiFindingGroupKey,
  { title: string; hint: string; tone: 'red' | 'orange' | 'gray' }
> = {
  needAction: { title: '需处理', hint: '通过证据核对，严重度高', tone: 'red' },
  confirm: { title: '待确认', hint: '通过证据核对，需人工判断', tone: 'orange' },
  insufficient: { title: '证据不足', hint: '模型结论未获证据支持，已折叠', tone: 'gray' }
}

const displayGroup = (key: WorkbenchAiFindingGroupKey) =>
  (conclusion.value?.groups[key] || []).map((finding) => ({
    ...workbenchFindingDisplay(finding),
    raw: finding,
    typeLabel: finding.typeLabel,
    actionLabel: finding.actionLabel || '',
    policyPending: finding.policyPending === true,
    policyName: finding.policyName || '',
    unsupportedClaims: finding.unsupportedClaims || [],
    modelTitle: finding.modelTitle || '',
    modelDescription: finding.modelDescription || '',
    unverified: finding.unverified === true,
    /** 正文超过三行（按 90 字估）才给"展开"。 */
    clampable: String(finding.description || '').length > 90
  }))

const needActionFindings = computed(() => displayGroup('needAction'))
const confirmFindings = computed(() => displayGroup('confirm'))
const insufficientFindings = computed(() => displayGroup('insufficient'))

/** 只有当前面板还没形成结论卡（旧路径：自由文本解析）时，才退回平铺列表。 */
const flatFindings = computed(() =>
  conclusion.value ? [] : props.presentation.findings.map(workbenchFindingDisplay)
)

const insufficientOpen = ref(false)
const expandedFindings = ref<Set<string>>(new Set())
const expandedModelText = ref<Set<string>>(new Set())

watch(
  () => props.presentation.runId,
  () => {
    insufficientOpen.value = false
    expandedFindings.value = new Set()
    expandedModelText.value = new Set()
  }
)

const toggle = (bucket: 'finding' | 'model', id: string) => {
  const target = bucket === 'finding' ? expandedFindings : expandedModelText
  const next = new Set(target.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  target.value = next
}

const decisionLabel = (id: string) => {
  const decision = props.decisions[id]
  return decision === 'accept' ? '已采纳' : decision === 'reject' ? '已驳回' : ''
}

const pageLabel = (pages: number[]) => (pages.length ? `第 ${pages.join('、')} 页` : '')

const ruleLabel = (rule: Record<string, unknown>) =>
  String(rule.text || rule.ruleCode || rule.source || '规则依据')
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

        <!-- 结论卡：要不要管 / 去查哪份 / 做什么，一屏回答（P9 R1，契约 12.3） -->
        <section
          v-if="conclusion"
          :class="['ai-conclusion', `is-${conclusion.tone}`]"
          aria-label="AI 结论卡"
        >
          <div class="ai-conclusion-head">
            <AuditStatusTag :tone="conclusion.tone" round>{{ conclusion.verdict }}</AuditStatusTag>
            <strong class="ai-conclusion-headline">{{ conclusion.headline }}</strong>
            <span class="ai-conclusion-note">AI 建议，未经人工确认</span>
            <span
              v-if="presentation.partialCoverageLabel"
              class="ai-conclusion-note is-partial"
              title="修复与升级模型重试后仍失败的证据分片，这些证据没有被 AI 审到"
            >
              {{ presentation.partialCoverageLabel }}
            </span>
          </div>
          <dl class="ai-conclusion-counts">
            <div class="is-red">
              <dt>需处理</dt>
              <dd>{{ conclusion.counts.needAction }}</dd>
            </div>
            <div class="is-orange">
              <dt>待确认</dt>
              <dd>{{ conclusion.counts.confirm }}</dd>
            </div>
            <div class="is-gray">
              <dt>证据不足</dt>
              <dd>{{ conclusion.counts.insufficient }}</dd>
            </div>
          </dl>
          <ul v-if="conclusion.keyFacts.length" class="ai-conclusion-facts">
            <li v-for="(fact, index) in conclusion.keyFacts" :key="index">
              <span>{{ fact.text }}</span>
              <small v-if="fact.location">{{ fact.location }}</small>
            </li>
          </ul>
          <div class="ai-conclusion-action">
            <span>建议动作</span>
            <strong>{{ conclusion.action }}</strong>
            <small v-if="conclusion.deterministicLabel">{{ conclusion.deterministicLabel }}</small>
            <ElButton
              v-if="canAct"
              size="small"
              text
              bg
              :disabled="acting"
              class="ai-conclusion-supplement"
              @click="emit('supplementFinding')"
            >
              补充 AI 未发现的问题
            </ElButton>
          </div>
        </section>

        <p class="ai-result-summary">{{ presentation.summary }}</p>
        <CertificateVerificationCard
          v-if="presentation.certificateVerification"
          :verification="presentation.certificateVerification"
        />

        <!-- 三组发现：需处理 → 待确认 → 证据不足（折叠） -->
        <template v-if="conclusion && presentation.findings.length">
          <div
            v-for="groupKey in ['needAction', 'confirm'] as const"
            :key="groupKey"
            v-show="(groupKey === 'needAction' ? needActionFindings : confirmFindings).length"
            class="ai-result-findings"
          >
            <div class="ai-result-findings-head">
              <AuditStatusTag :tone="GROUP_META[groupKey].tone" round>
                {{ GROUP_META[groupKey].title }}
              </AuditStatusTag>
              <span>
                {{ (groupKey === 'needAction' ? needActionFindings : confirmFindings).length }} 条
              </span>
              <small>{{ GROUP_META[groupKey].hint }}</small>
            </div>
            <article
              v-for="(finding, findingIndex) in groupKey === 'needAction'
                ? needActionFindings
                : confirmFindings"
              :key="finding.id"
              :class="['ai-finding', `is-${finding.severityTone}`]"
            >
              <div class="ai-finding-head">
                <span class="ai-finding-index">{{ findingIndex + 1 }}</span>
                <h3>{{ finding.title || '审查发现' }}</h3>
                <AuditStatusTag v-if="finding.severityTag" :tone="finding.severityTone" round>
                  {{ finding.severityTag }}
                </AuditStatusTag>
                <span v-if="decisionLabel(finding.id)" class="ai-finding-decision">
                  {{ decisionLabel(finding.id) }}
                </span>
                <span v-if="finding.confidencePercent !== undefined" class="ai-finding-confidence">
                  置信度 {{ finding.confidencePercent }}%
                </span>
              </div>
              <div class="ai-finding-chips">
                <span v-if="finding.typeLabel" class="ai-chip">{{ finding.typeLabel }}</span>
                <span v-if="finding.actionLabel" class="ai-chip is-action">
                  {{ finding.actionLabel }}
                </span>
                <span v-if="finding.policyPending" class="ai-chip is-policy">
                  口径待确认{{ finding.policyName ? `：${finding.policyName}` : '' }}
                </span>
                <span v-if="finding.evidenceCount" class="ai-chip">
                  证据 {{ finding.evidenceCount }}
                </span>
                <span v-if="finding.ruleCount" class="ai-chip">规则 {{ finding.ruleCount }}</span>
              </div>
              <p
                :class="[
                  'ai-finding-description',
                  { 'is-clamped': finding.clampable && !expandedFindings.has(finding.id) }
                ]"
              >
                {{ finding.description }}
              </p>
              <button
                v-if="finding.clampable"
                type="button"
                class="ai-link-button"
                @click="toggle('finding', finding.id)"
              >
                {{ expandedFindings.has(finding.id) ? '收起' : '展开全文' }}
              </button>
              <div v-if="finding.evidenceGroups.length" class="ai-evidence-groups">
                <div
                  v-for="group in finding.evidenceGroups"
                  :key="group.fileId || group.fileName"
                  class="ai-evidence-group"
                >
                  <button
                    type="button"
                    class="ai-evidence-file"
                    @click="emit('openFile', group.fileId)"
                  >
                    <span class="ai-evidence-file-icon" aria-hidden="true">▤</span>
                    <span class="ai-evidence-file-name">{{ group.fileName }}</span>
                    <small v-if="group.pages.length">{{ pageLabel(group.pages) }}</small>
                  </button>
                  <ul v-if="group.quotes.length" class="ai-evidence-quotes">
                    <li v-for="quote in group.quotes" :key="quote">{{ quote }}</li>
                  </ul>
                </div>
              </div>
              <div v-if="finding.ruleRefs.length" class="ai-rule-list">
                <span v-for="(rule, index) in finding.ruleRefs" :key="index">
                  {{ ruleLabel(rule) }}
                </span>
              </div>
              <div v-if="canAct" class="ai-finding-actions">
                <ElButton
                  size="small"
                  :disabled="acting || Boolean(decisionLabel(finding.id))"
                  @click="emit('findingDecision', finding.raw, 'accept')"
                >
                  采纳
                </ElButton>
                <ElButton
                  size="small"
                  :disabled="acting || Boolean(decisionLabel(finding.id))"
                  @click="emit('findingDecision', finding.raw, 'reject')"
                >
                  驳回
                </ElButton>
                <ElButton
                  v-if="groupKey === 'needAction'"
                  size="small"
                  type="warning"
                  plain
                  :disabled="acting"
                  @click="emit('returnCorrection', finding.raw)"
                >
                  据此退回补正
                </ElButton>
              </div>
            </article>
          </div>

          <div v-if="insufficientFindings.length" class="ai-result-findings ai-insufficient">
            <button
              type="button"
              class="ai-result-findings-head ai-insufficient-toggle"
              :aria-expanded="insufficientOpen"
              @click="insufficientOpen = !insufficientOpen"
            >
              <AuditStatusTag tone="gray" round>{{ GROUP_META.insufficient.title }}</AuditStatusTag>
              <span>{{ insufficientFindings.length }} 条</span>
              <small>
                待核对 {{ conclusion.insufficientClaims.length }} 项 ·
                {{ GROUP_META.insufficient.hint }}
              </small>
              <span class="ai-insufficient-caret">{{ insufficientOpen ? '收起' : '展开' }}</span>
            </button>
            <template v-if="insufficientOpen">
              <ul v-if="conclusion.insufficientClaims.length" class="ai-claim-list">
                <li v-for="item in conclusion.insufficientClaims" :key="item.claim">
                  <span>{{ item.text }}</span>
                  <span
                    v-if="decisions[`${item.findingId}::${item.claim}`] === 'supported'"
                    class="ai-finding-decision"
                  >
                    已标记有依据
                  </span>
                  <ElButton
                    v-else-if="canAct"
                    size="small"
                    text
                    bg
                    :disabled="acting"
                    @click="
                      emit(
                        'claimSupported',
                        insufficientFindings.find((f) => f.id === item.findingId)?.raw ||
                          insufficientFindings[0].raw,
                        item.claim
                      )
                    "
                  >
                    其实有依据
                  </ElButton>
                </li>
              </ul>
              <article
                v-for="finding in insufficientFindings"
                :key="finding.id"
                class="ai-finding is-gray"
              >
                <div class="ai-finding-head">
                  <h3>{{ finding.modelTitle || finding.title || '证据不足，需人工确认' }}</h3>
                  <span v-if="finding.unverified" class="ai-chip is-unverified">未经证据核实</span>
                  <span v-if="finding.typeLabel" class="ai-chip">{{ finding.typeLabel }}</span>
                </div>
                <p class="ai-finding-description">{{ finding.description }}</p>
                <template v-if="finding.modelDescription">
                  <button type="button" class="ai-link-button" @click="toggle('model', finding.id)">
                    {{ expandedModelText.has(finding.id) ? '收起模型原文' : '查看模型原文' }}
                  </button>
                  <blockquote
                    v-if="expandedModelText.has(finding.id)"
                    class="ai-model-text"
                    aria-label="模型原文，未经证据核实"
                  >
                    <span class="ai-chip is-unverified">未经证据核实，不可直接采信</span>
                    <p>{{ finding.modelDescription }}</p>
                  </blockquote>
                </template>
              </article>
            </template>
          </div>
        </template>

        <!-- 旧路径（无结论卡）：平铺列表 -->
        <div v-else-if="flatFindings.length" class="ai-result-findings">
          <div class="ai-result-findings-head">
            <span>审查发现</span>
            <small>{{ flatFindings.length }} 条 · 均需人工确认</small>
          </div>
          <article
            v-for="(finding, findingIndex) in flatFindings"
            :key="finding.id"
            :class="['ai-finding', `is-${finding.severityTone}`]"
          >
            <div class="ai-finding-head">
              <span class="ai-finding-index">{{ findingIndex + 1 }}</span>
              <h3>{{ finding.title || '审查发现' }}</h3>
              <AuditStatusTag v-if="finding.severityTag" :tone="finding.severityTone" round>
                {{ finding.severityTag }}
              </AuditStatusTag>
            </div>
            <p class="ai-finding-description">{{ finding.description }}</p>
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
  box-shadow: 0 6px 18px rgb(31 72 125 / 6%);
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

.ai-conclusion {
  /* 结论卡 */

  --ai-conclusion-accent: #667085;

  display: grid;
  padding: 14px 16px;
  margin-top: 14px;
  background: #fff;
  border: 1px solid #dfe7f2;
  border-left: 4px solid var(--ai-conclusion-accent);
  border-radius: 10px;
  gap: 10px;
}

.ai-conclusion.is-red {
  --ai-conclusion-accent: var(--aicheck-danger, #b42318);
}

.ai-conclusion.is-orange {
  --ai-conclusion-accent: var(--aicheck-warning, #b45309);
}

.ai-conclusion.is-green {
  --ai-conclusion-accent: var(--aicheck-success, #16803c);
}

.ai-conclusion-head {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.ai-conclusion-headline {
  flex: 1 1 260px;
  min-width: 0;
  font-size: 15px;
  line-height: 22px;
  color: var(--aicheck-text-strong, #172033);
}

.ai-conclusion-note {
  padding: 2px 8px;
  font-size: 12px;
  color: #7a4b00;
  background: #fff5e0;
  border: 1px solid #f3dfb0;
  border-radius: 999px;
}

.ai-conclusion-note.is-partial {
  color: var(--aicheck-danger, #b42318);
  background: #fff5f4;
  border-color: #f2d2cf;
}

.ai-conclusion-counts {
  display: grid;
  margin: 0;
  gap: 8px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.ai-conclusion-counts > div {
  display: flex;
  gap: 8px;
  align-items: baseline;
  padding: 6px 10px;
  background: #f8fafc;
  border-radius: 8px;
}

.ai-conclusion-counts dt {
  font-size: 12px;
  color: var(--aicheck-text-subtle, #667085);
}

.ai-conclusion-counts dd {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  line-height: 24px;
}

.ai-conclusion-counts > .is-red dd {
  color: var(--aicheck-danger, #b42318);
}

.ai-conclusion-counts > .is-orange dd {
  color: var(--aicheck-warning, #b45309);
}

.ai-conclusion-counts > .is-gray dd {
  color: var(--aicheck-text-subtle, #667085);
}

.ai-conclusion-facts {
  display: grid;
  padding: 0;
  margin: 0;
  list-style: none;
  gap: 4px;
}

.ai-conclusion-facts li {
  display: flex;
  gap: 10px;
  align-items: baseline;
  font-size: 13px;
  line-height: 20px;
  color: #27364b;
}

.ai-conclusion-facts li::before {
  color: var(--ai-conclusion-accent);
  content: '•';
}

.ai-conclusion-facts small {
  color: var(--aicheck-text-subtle, #667085);
  white-space: nowrap;
}

.ai-conclusion-action {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  font-size: 13px;
}

.ai-conclusion-action > span {
  color: var(--aicheck-text-subtle, #667085);
}

.ai-conclusion-action > strong {
  color: var(--aicheck-text-strong, #172033);
}

.ai-conclusion-action > small {
  color: var(--aicheck-text-subtle, #667085);
}

.ai-conclusion-supplement {
  margin-left: auto;
}

.ai-result-summary {
  max-width: 960px;
  margin: 13px 0 0;
  font-size: 14px;
  line-height: 1.75;
  color: #27364b;
}

.ai-result-findings {
  /* 发现分组 */

  display: grid;
  margin-top: 16px;
  gap: 10px;
}

.ai-result-findings-head {
  display: flex;
  gap: 10px;
  align-items: center;
  padding-top: 14px;
  border-top: 1px solid #e3ebf5;
}

.ai-result-findings-head > span {
  font-size: 13px;
  font-weight: 600;
  color: var(--aicheck-text-strong, #172033);
}

.ai-result-findings-head > small {
  font-size: 12px;
  color: var(--aicheck-text-subtle, #667085);
}

.ai-insufficient-toggle {
  width: 100%;
  font: inherit;
  text-align: left;
  cursor: pointer;
  background: transparent;
  border-right: 0;
  border-bottom: 0;
  border-left: 0;
}

.ai-insufficient-caret {
  margin-left: auto;
  font-size: 12px;
  color: var(--aicheck-primary, #1f66d8);
}

.ai-claim-list {
  display: grid;
  padding: 10px 12px;
  margin: 0;
  list-style: none;
  background: #f8fafc;
  border: 1px dashed #d5dfeb;
  border-radius: 8px;
  gap: 6px;
}

.ai-claim-list li {
  display: flex;
  gap: 10px;
  align-items: center;
  font-size: 13px;
  line-height: 20px;
  color: #34445a;
}

.ai-claim-list li > span:first-child {
  flex: 1 1 auto;
  min-width: 0;
}

.ai-finding {
  --ai-finding-accent: #9db5d3;

  padding: 14px 16px;
  background: #fff;
  border: 1px solid #e3ebf5;
  border-radius: 10px;
}

.ai-finding.is-blue {
  --ai-finding-accent: var(--aicheck-primary, #1f66d8);
}

.ai-finding.is-orange {
  --ai-finding-accent: var(--aicheck-warning, #b45309);
}

.ai-finding.is-red {
  --ai-finding-accent: var(--aicheck-danger, #b42318);
}

.ai-finding.is-gray {
  background: #fbfcfe;
}

.ai-finding-head {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.ai-finding-head h3 {
  flex: 1 1 240px;
  min-width: 0;
  margin: 0;
  font-size: 15px;
  line-height: 22px;
  color: var(--aicheck-text-strong, #172033);
}

.ai-finding-index {
  display: inline-grid;
  width: 22px;
  height: 22px;
  font-size: 12px;
  font-weight: 600;
  color: #fff;
  background: var(--ai-finding-accent);
  border-radius: 50%;
  place-items: center;
}

.ai-finding-confidence {
  font-size: 12px;
  color: var(--aicheck-text-subtle, #667085);
}

.ai-finding-decision {
  padding: 1px 8px;
  font-size: 12px;
  color: #0f5132;
  background: #e6f4ea;
  border-radius: 999px;
}

.ai-finding-chips {
  display: flex;
  gap: 6px;
  margin-top: 8px;
  flex-wrap: wrap;
}

.ai-chip {
  padding: 2px 8px;
  font-size: 12px;
  line-height: 18px;
  color: #52647a;
  background: #edf2f8;
  border-radius: 999px;
}

.ai-chip.is-action {
  color: #1f4f9a;
  background: #e6efff;
}

.ai-chip.is-policy {
  color: #1f4f9a;
  background: #e6efff;
  border: 1px dashed #9fbdf0;
}

.ai-chip.is-unverified {
  color: #7a4b00;
  background: #fff5e0;
}

.ai-finding-description {
  margin: 8px 0 0;
  font-size: 13.5px;
  line-height: 1.75;
  color: #34445a;
}

.ai-finding-description.is-clamped {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  line-clamp: 3;
}

.ai-link-button {
  padding: 0;
  margin-top: 4px;
  font-size: 12px;
  color: var(--aicheck-primary, #1f66d8);
  cursor: pointer;
  background: transparent;
  border: 0;
}

.ai-model-text {
  padding: 10px 12px;
  margin: 8px 0 0;
  background: #fffaf0;
  border: 1px dashed #e8d3a3;
  border-radius: 8px;
}

.ai-model-text p {
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.7;
  color: #5c4a1f;
  user-select: none;
}

.ai-finding-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  flex-wrap: wrap;
}

.ai-evidence-groups {
  display: grid;
  margin-top: 12px;
  gap: 8px;
}

.ai-evidence-group {
  padding: 8px 10px;
  background: #f6f9fd;
  border: 1px dashed #d5e1f0;
  border-radius: 8px;
}

.ai-evidence-file {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  max-width: 100%;
  padding: 0;
  font-size: 13px;
  color: var(--aicheck-primary, #1f66d8);
  cursor: pointer;
  background: transparent;
  border: 0;
}

.ai-evidence-file:hover .ai-evidence-file-name {
  text-decoration: underline;
}

.ai-evidence-file-icon {
  font-size: 12px;
  opacity: 0.7;
}

.ai-evidence-file-name {
  overflow: hidden;
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ai-evidence-file small {
  font-size: 12px;
  color: var(--aicheck-text-subtle, #667085);
}

.ai-evidence-quotes {
  display: flex;
  gap: 6px;
  padding: 0;
  margin: 6px 0 0;
  list-style: none;
  flex-wrap: wrap;
}

.ai-evidence-quotes li {
  max-width: 100%;
  padding: 2px 8px;
  overflow: hidden;
  font-size: 12px;
  line-height: 20px;
  color: #3f5068;
  text-overflow: ellipsis;
  white-space: nowrap;
  background: #fff;
  border: 1px solid #dfe8f3;
  border-radius: 999px;
}

.ai-evidence-quotes li::before {
  color: #9db5d3;
  content: '“';
}

.ai-evidence-quotes li::after {
  color: #9db5d3;
  content: '”';
}

.ai-rule-list {
  display: flex;
  gap: 8px;
  margin-top: 10px;
  flex-wrap: wrap;
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

  .ai-conclusion-counts {
    grid-template-columns: 1fr;
  }

  .ai-history-item-head {
    gap: 8px;
  }
}
</style>
