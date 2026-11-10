<script setup lang="ts">
import { computed } from 'vue'
import { ElButton, ElTag } from 'element-plus'
import type { EvidenceLink } from '@/types/aicheck'
import type { ReviewBWorkspace } from '@/types/ai-review-b'
import type { ReviewDocumentSelection } from '@/api/aicheck/reviewDocuments'
import { overviewProgress, overviewResult } from '../workstationOverview'
import { documentPageLabel } from '../documentPageSelection'
import ReviewApprovalChecks from './ReviewApprovalChecks.vue'
import ReviewResultCard from './ReviewResultCard.vue'
import ReviewAutomationLimitations from './ReviewAutomationLimitations.vue'
const props = defineProps<{
  workspace: ReviewBWorkspace | null
  selection: ReviewDocumentSelection | null
  loading: boolean
  stale: boolean
  conflict: boolean
  busy: boolean
  canStart: boolean
  statusLabel: string
  startLabel: string
  error?: string
}>()
const emit = defineEmits<{
  start: []
  navigate: [section: 'documents' | 'rules' | 'handoffs' | 'assistant' | 'human']
  evidence: [evidence: EvidenceLink]
}>()
const result = computed(() => (props.workspace ? overviewResult(props.workspace) : undefined))
const blockers = computed(() => props.workspace?.evidenceReadiness.blockingReasons || [])
const missing = computed(() => props.workspace?.evidenceReadiness.missingRequirements || [])
</script>

<template>
  <section class="node-overview" aria-label="节点待办与结果" :aria-busy="loading">
    <p v-if="loading" role="status">正在加载这个节点的资料…</p>
    <p v-else-if="!workspace">{{ error || '先选择一个节点，就能看到资料和审查结果。' }}</p>
    <template v-else>
      <header class="overview-heading">
        <div
          ><h2>这个节点，接下来做什么</h2><p>{{ statusLabel }}</p></div
        >
        <ElButton
          type="primary"
          :loading="busy"
          :disabled="!canStart || busy || loading"
          @click="emit('start')"
          >{{ startLabel }}</ElButton
        >
      </header>
      <div
        v-if="error || stale || conflict || workspace.activeHumanInputTask"
        class="attention-panel"
        role="status"
      >
        <p v-if="error">{{ error }}</p>
        <p v-if="stale">资料已经变了。下面保留的是上次结果，需要按当前资料重新审查。</p>
        <p v-if="conflict">管线资料有冲突，请先核对冲突明细，再确认判断。</p>
        <p v-if="workspace.activeHumanInputTask">有一项人工待办，需要你处理后才能继续。</p>
        <ElButton
          v-if="workspace.activeHumanInputTask || conflict"
          @click="emit('navigate', 'human')"
          >去处理</ElButton
        >
      </div>
      <section aria-label="最近审查结果">
        <div class="section-heading"
          ><h3>目前的审查结果</h3
          ><ElButton text type="primary" @click="emit('navigate', 'assistant')"
            >有疑问，继续追问</ElButton
          ></div
        >
        <p v-if="workspace.activeReviewRun" class="result-notice" role="status">
          {{ overviewProgress(workspace.activeReviewRun.status) }}
        </p>
        <ReviewAutomationLimitations
          :items="workspace.activeReviewRun?.automationLimitations || []"
        />
        <ReviewApprovalChecks
          :key="workspace.activeReviewRun?.reviewRunId || workspace.activeReviewRun?.id"
          :items="workspace.activeReviewRun?.approvalChecks || []"
          :evidence-links="workspace.evidenceLinks"
          @evidence="emit('evidence', $event)"
        />
        <ReviewResultCard
          v-if="result"
          :key="result.reviewRunId"
          :result="result"
          :evidence-links="workspace.evidenceLinks"
          :source-label="workspace.activeReviewRun ? '节点审查 · 当前任务' : '工程分析 · 最近记录'"
          focus-issues
          @open-evidence="emit('evidence', $event)"
        />
        <p v-else-if="!workspace.activeReviewRun" class="result-notice">
          还没有审查结果。选好资料后，可以从上方发起审查。
        </p>
      </section>
      <section class="overview-section" aria-label="本次资料">
        <div class="section-heading"
          ><h3>本次用哪些资料</h3
          ><ElButton text type="primary" @click="emit('navigate', 'documents')"
            >调整资料</ElButton
          ></div
        >
        <template v-if="selection">
          <p>已选 {{ selection.versions.length }} 个文件版本；下次发起时使用，当前结果不会改变。</p>
          <ul
            ><li v-for="version in selection.versions" :key="version.versionId"
              >{{ version.fileName }}
              <ElTag size="small"
                >{{ version.versionNo || '指定版本' }} · {{ documentPageLabel(version) }}</ElTag
              ></li
            ></ul
          >
        </template>
        <p v-else
          >按节点现有资料发起。当前就绪检查记录
          {{ workspace.evidenceReadiness.supportingDocumentCount }} 份支持文件。</p
        >
        <p v-if="workspace.activeReviewRun?.ruleVersion" class="overview-meta"
          >审查规则：{{ workspace.activeReviewRun.ruleVersion }}</p
        >
        <details v-if="missing.length || blockers.length">
          <summary>看看哪些资料还需要核对（节点现有资料）</summary>
          <ul
            ><li v-for="item in missing" :key="item.id">{{ item.name }}</li
            ><li v-for="(item, index) in blockers" :key="`block-${index}`">{{
              item.message || '还有一项要求需要核对，详见节点资料。'
            }}</li></ul
          >
          <p v-if="selection">这里是节点现有资料的检查结果；你刚选的文件会在发起时重新检查。</p>
        </details>
      </section>
      <footer class="overview-section overview-confirm">
        <ElButton
          :disabled="!workspace.permissions.canSubmitReviewOpinion"
          @click="emit('navigate', 'human')"
          >核对并填写人工结论</ElButton
        >
        <span class="overview-meta">AI 的建议不会自动成为正式结论。</span>
        <p v-if="!workspace.permissions.canSubmitReviewOpinion" class="overview-meta"
          >当前没有保存人工结论的权限。</p
        >
      </footer>
    </template>
  </section>
</template>

<style scoped>
/* 悬浮助手里这页原来是五张带边框的白卡，每张「标题 + 一段说明 + 按钮」，
   其中「按什么规则审」「最后，由你确认」两张的按钮和上面工具行里的同名按钮是同一件事。
   现在：去掉重复的卡，其余平铺成小节，只用细线隔开。 */
.node-overview {
  display: grid;
  gap: 14px;
  color: var(--el-text-color-primary);
  overflow-wrap: anywhere;
}

h2,
h3,
p {
  margin: 0;
}

h2 {
  font-size: 16px;
  font-weight: 600;
}

h3 {
  font-size: 14px;
  font-weight: 600;
}

p,
li {
  font-size: 13px;
  line-height: 1.7;
}

p {
  margin-top: 6px;
}

ul {
  padding-left: 22px;
}

.overview-heading,
.section-heading,
.overview-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}

.overview-heading,
.section-heading {
  justify-content: space-between;
}

.overview-section {
  padding: 12px 0 0;
  border-top: 1px solid var(--el-border-color-lighter);
}

.overview-meta {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.overview-confirm {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
  align-items: center;
}

.overview-confirm .overview-meta {
  margin: 0;
}

.attention-panel {
  padding: 16px;
  background: var(--el-color-warning-light-9);
  border-left: 4px solid var(--el-color-warning);
  border-radius: 8px;
}

.result-notice {
  padding: 8px 0;
}

summary {
  min-height: 44px;
  padding: 12px 0;
  font-size: 13px;
  cursor: pointer;
  box-sizing: border-box;
}

:deep(.el-button) {
  min-height: 44px;
  margin-left: 0;
  white-space: normal;
}

summary:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: 3px;
}
</style>
