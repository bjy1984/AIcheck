<script setup lang="ts">
import { computed } from 'vue'
import { useMediaQuery } from '@vueuse/core'
import { ElButton, ElStep, ElSteps } from 'element-plus'

export type AuditWorkflowStage = {
  key: string
  label: string
  status: 'completed' | 'active' | 'blocked' | 'pending' | 'failed'
  metric: string
  detail: string
  actionKey?: string
  actionLabel?: string
}

const props = defineProps<{
  stages: AuditWorkflowStage[]
  recommendedAction?: string
  loading?: boolean
}>()

const emit = defineEmits<{
  action: [actionKey: string]
}>()

const isCompactViewport = useMediaQuery('(max-width: 900px)')
const stepsDirection = computed(() => (isCompactViewport.value ? 'vertical' : 'horizontal'))
const activeStep = computed(() => {
  const activeIndex = props.stages.findIndex((stage) => stage.status === 'active')
  if (activeIndex >= 0) return activeIndex
  const openIndex = props.stages.findIndex((stage) => stage.status !== 'completed')
  return openIndex >= 0 ? openIndex : props.stages.length
})
const focusedStage = computed(
  () =>
    props.stages.find((stage) => stage.actionKey && stage.actionKey === props.recommendedAction) ||
    props.stages[activeStep.value] ||
    props.stages.at(-1)
)

const elementStepStatus = (status: AuditWorkflowStage['status']) => {
  if (status === 'completed') return 'success'
  if (status === 'active') return 'process'
  if (status === 'failed') return 'error'
  return 'wait'
}
</script>

<template>
  <section class="audit-workflow" aria-label="审计办理进度">
    <div class="audit-workflow-head">
      <div>
        <h2>办理进度</h2>
        <p>状态来自实际资料、OCR 产物、证据确认和审查记录。</p>
      </div>
      <span class="audit-workflow-legend">当前节点</span>
    </div>
    <div class="audit-workflow-steps">
      <ElSteps
        :active="activeStep"
        :direction="stepsDirection"
        finish-status="success"
        process-status="process"
        :align-center="!isCompactViewport"
        aria-label="审计业务阶段"
      >
        <ElStep
          v-for="(stage, index) in stages"
          :key="stage.key"
          :class="['audit-workflow-stage', `is-${stage.status}`]"
          :status="elementStepStatus(stage.status)"
        >
          <template #icon>
            <span class="audit-stage-index" aria-hidden="true">{{ index + 1 }}</span>
          </template>
          <template #title>
            <div class="audit-stage-title">
              <strong>{{ stage.label }}</strong>
              <span>{{ stage.metric }}</span>
            </div>
          </template>
        </ElStep>
      </ElSteps>
    </div>
    <div v-if="focusedStage" :class="['audit-workflow-focus', `is-${focusedStage.status}`]">
      <div>
        <span>当前关注</span>
        <strong>{{ focusedStage.label }} · {{ focusedStage.metric }}</strong>
        <p>{{ focusedStage.detail }}</p>
      </div>
      <ElButton
        v-if="
          focusedStage.actionKey &&
          focusedStage.actionLabel &&
          focusedStage.actionKey === recommendedAction
        "
        class="audit-stage-action"
        type="primary"
        :loading="loading"
        @click="emit('action', focusedStage.actionKey)"
      >
        {{ focusedStage.actionLabel }}
      </ElButton>
    </div>
  </section>
</template>

<style scoped>
.audit-workflow {
  padding: 16px 20px 18px;
  color: var(--aicheck-text, #26364e);
  background: var(--aicheck-surface, #fff);
  border-block: 1px solid var(--aicheck-border, #d4deeb);
}

.audit-workflow-head,
.audit-stage-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.audit-workflow-head h2,
.audit-workflow-head p,
.audit-stage-content p {
  margin: 0;
}

.audit-workflow-head h2 {
  font-size: 16px;
  font-weight: 600;
  line-height: 24px;
  color: var(--aicheck-text-strong, #172033);
}

.audit-workflow-head p,
.audit-stage-content p {
  margin-top: 4px;
  font-size: 13px;
  font-weight: 400;
  line-height: 20px;
  color: var(--aicheck-text-muted, #52647d);
}

.audit-workflow-legend {
  font-size: 12px;
  font-weight: 500;
  color: var(--aicheck-text-muted, #52647d);
}

.audit-workflow-steps {
  margin: 16px 0 0;
  overflow: hidden;
}

.audit-workflow-steps > :deep(.el-steps) {
  width: 100%;
  min-width: 0;
}

.audit-workflow-stage {
  min-width: 0;
  min-height: 76px;
}

.audit-stage-index {
  display: grid;
  width: 28px;
  height: 28px;
  font-size: 12px;
  font-weight: 600;
  color: inherit;
  place-items: center;
}

.audit-stage-title {
  display: grid;
  gap: 3px;
  align-items: flex-start;
  justify-content: center;
  min-width: 0;
  padding: 0 4px;
  text-align: center;
}

.audit-stage-title strong {
  font-size: 14px;
  font-weight: 600;
  line-height: 20px;
  color: var(--aicheck-text, #26364e);
}

.audit-stage-title span {
  font-size: 12px;
  font-weight: 500;
  line-height: 18px;
  color: var(--aicheck-text-muted, #52647d);
  font-variant-numeric: tabular-nums;
  text-align: center;
}

.audit-workflow-stage.is-blocked :deep(.el-step__head.is-wait) {
  color: var(--aicheck-warning, #8a4b00);
  border-color: #d97706;
}

.audit-workflow-stage.is-pending :deep(.el-step__head.is-wait) {
  color: var(--aicheck-text-subtle, #667085);
  border-color: #98a2b3;
}

.audit-stage-action {
  min-width: 96px;
  min-height: 44px;
}

.audit-workflow-focus {
  display: flex;
  min-height: 72px;
  padding: 12px 14px;
  margin-top: 8px;
  background: #f8fafc;
  border: 1px solid var(--aicheck-border, #d4deeb);
  border-radius: 6px;
  gap: 16px;
  align-items: center;
  justify-content: space-between;
}

.audit-workflow-focus > div {
  min-width: 0;
}

.audit-workflow-focus span,
.audit-workflow-focus strong {
  display: block;
}

.audit-workflow-focus span {
  font-size: 12px;
  color: var(--aicheck-text-muted, #52647d);
}

.audit-workflow-focus strong {
  margin-top: 2px;
  font-size: 14px;
  color: var(--aicheck-text-strong, #172033);
}

.audit-workflow-focus p {
  margin: 3px 0 0;
  font-size: 13px;
  line-height: 20px;
  color: var(--aicheck-text-muted, #52647d);
}

.audit-workflow-focus.is-blocked {
  background: var(--aicheck-warning-bg, #fff7e6);
  border-color: #f2c98a;
}

.audit-workflow-focus.is-failed {
  background: var(--aicheck-danger-bg, #fef3f2);
  border-color: #f6b9b3;
}

@media (width > 900px) {
  .audit-workflow-stage {
    min-height: 76px;
  }
}

@media (width <= 900px) {
  .audit-workflow {
    padding-inline: 14px;
  }

  .audit-workflow-steps {
    overflow-x: visible;
  }

  .audit-workflow-steps > :deep(.el-steps) {
    min-width: 0;
  }

  .audit-workflow-stage {
    min-height: 92px;
  }

  .audit-stage-title {
    display: flex;
    justify-content: space-between;
    padding: 0;
    text-align: left;
  }

  .audit-stage-title span {
    text-align: right;
  }

  .audit-workflow-focus {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
