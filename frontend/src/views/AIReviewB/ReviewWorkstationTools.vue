<script setup lang="ts">
import { ref } from 'vue'
import { ElButton } from 'element-plus'
import type { ReviewDocumentSelection } from '@/api/aicheck/reviewDocuments'
import type { EvidenceLink } from '@/types/aicheck'
import ProjectRuleEditor from './ProjectRuleEditor.vue'
import ReviewDocumentPicker from './ReviewDocumentPicker.vue'
import ReviewHandoffPanel from './ReviewHandoffPanel.vue'

defineProps<{
  projectId: string
  nodeId: number
  runId: string
  projectEtag?: string
  evidenceLinks?: EvidenceLink[]
  selection: ReviewDocumentSelection | null
  documentsDisabled: boolean
}>()
const emit = defineEmits<{
  change: [selection: ReviewDocumentSelection | null]
  bound: []
  evidence: [value: EvidenceLink]
}>()
const toolRoot = ref<HTMLElement>()
const focusTool = (section: 'documents' | 'rules' | 'handoffs') => {
  const index = { documents: 0, rules: 1, handoffs: 2 }[section]
  const buttons = toolRoot.value?.querySelectorAll<HTMLButtonElement>(
    '.workstation-tools__actions > button'
  )
  buttons?.[index]?.scrollIntoView({ block: 'nearest' })
  buttons?.[index]?.focus()
}
defineExpose({ focusTool })
const enabled = import.meta.env.VITE_AICHECK_WORKSTATIONS_ENABLED === 'true'
</script>

<template>
  <section v-if="enabled" ref="toolRoot" class="workstation-tools" aria-label="当前节点审查工具">
    <div class="workstation-tools__context">
      <strong>资料与审查协作</strong>
      <p>为当前节点选择资料、调整工程规则并核验交接。</p>
    </div>
    <div class="workstation-tools__actions" role="group" aria-label="节点工具">
      <ReviewDocumentPicker
        :project-id="projectId"
        :node-id="nodeId"
        :selection="selection"
        :project-etag="projectEtag"
        :disabled="documentsDisabled"
        @change="emit('change', $event)"
        @bound="emit('bound')"
      />
      <ProjectRuleEditor
        :project-id="projectId"
        :node-id="nodeId"
        :review-run-id="runId"
        :apply-disabled="documentsDisabled"
        @apply-mapping="!documentsDisabled && emit('change', $event)"
      />
      <ReviewHandoffPanel
        :project-etag="projectEtag"
        :evidence-links="evidenceLinks"
        :project-id="projectId"
        :run-id="runId"
        @evidence="emit('evidence', $event)"
      />
    </div>
    <p v-if="selection?.conditionObjectMapping" role="status" class="workstation-tools__hint">
      下次审查对象：{{ selection.conditionObjectMapping.selection.subject.objectId }}，按规则修订
      {{ selection.conditionObjectMapping.ruleRevision }}
      的已试跑版本选择原文。调整文件后需要重新选择对象。
      <ElButton
        :disabled="documentsDisabled"
        @click="emit('change', { versions: selection.versions, reviewMode: selection.reviewMode })"
        >移除对象选择</ElButton
      >
    </p>
    <p v-if="!runId" class="workstation-tools__hint">发起审查后，可核验该任务收到的工位交接。</p>
  </section>
</template>

<style scoped>
.workstation-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 16px;
  align-items: center;
  justify-content: space-between;
  padding: 16px;
  margin-top: 16px;
  color: var(--el-text-color-primary);
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-light);
  border-radius: var(--el-border-radius-base);
}

.workstation-tools__context {
  min-width: 0;
}

.workstation-tools__context strong {
  font-size: 15px;
}

.workstation-tools__context p,
.workstation-tools__hint {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--el-text-color-regular);
  overflow-wrap: anywhere;
}

.workstation-tools__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.workstation-tools__actions :deep(> .el-button) {
  min-height: 44px;
  margin-left: 0;
}

.workstation-tools__hint {
  flex-basis: 100%;
}
</style>
