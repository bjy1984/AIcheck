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
          :class="[
            'audit-workflow-stage',
            `is-${stage.status}`,
            index % 2 === 0 ? 'is-content-below' : 'is-content-above'
          ]"
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
          <template #description>
            <div class="audit-stage-content">
              <p>{{ stage.detail }}</p>
              <ElButton
                v-if="stage.actionKey && stage.actionLabel && stage.actionKey === recommendedAction"
                class="audit-stage-action"
                type="primary"
                :loading="loading"
                @click="emit('action', stage.actionKey)"
              >
                {{ stage.actionLabel }}
              </ElButton>
            </div>
          </template>
        </ElStep>
      </ElSteps>
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
  min-height: 118px;
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

.audit-stage-content {
  min-height: 92px;
  padding: 6px 6px 0;
  text-align: left;
}

.audit-stage-content p {
  min-height: 42px;
}

.audit-workflow-stage.is-active :deep(.el-step__description) {
  color: #294f73;
  background: #f1f7fd;
}

.audit-workflow-stage.is-blocked :deep(.el-step__head.is-wait) {
  color: var(--aicheck-warning, #8a4b00);
  border-color: #d97706;
}

.audit-workflow-stage.is-blocked :deep(.el-step__description) {
  color: var(--aicheck-warning, #8a4b00);
  background: var(--aicheck-warning-bg, #fff7e6);
}

.audit-workflow-stage.is-failed :deep(.el-step__description) {
  color: var(--aicheck-danger, #b42318);
  background: var(--aicheck-danger-bg, #fef3f2);
}

.audit-workflow-stage.is-pending :deep(.el-step__head.is-wait) {
  color: var(--aicheck-text-subtle, #667085);
  border-color: #98a2b3;
}

.audit-workflow-stage.is-pending :deep(.el-step__description) {
  color: var(--aicheck-text-muted, #52647d);
  background: #f8fafc;
}

.audit-stage-action {
  min-width: 96px;
  min-height: 44px;
  margin-top: 8px;
}

@media (width > 900px) {
  .audit-workflow-stage {
    position: relative;
    min-height: 420px;
  }

  .audit-workflow-stage :deep(.el-step__head) {
    position: absolute;
    top: calc(50% - 14px);
    left: 0;
    z-index: 1;
    width: 100%;
  }

  .audit-workflow-stage :deep(.el-step__main) {
    position: absolute;
    left: 0;
    display: flex;
    width: 100%;
    flex-direction: column;
  }

  .audit-workflow-stage :deep(.el-step__description) {
    width: clamp(190px, 155%, 360px);
    max-width: none;
    margin-left: calc((100% - clamp(190px, 155%, 360px)) / 2);
  }

  .audit-workflow-stage:first-child :deep(.el-step__description) {
    margin-left: 0;
  }

  .audit-workflow-stage:last-child :deep(.el-step__description) {
    margin-left: calc(100% - clamp(190px, 155%, 360px));
  }

  .audit-workflow-stage.is-content-below :deep(.el-step__main) {
    top: calc(50% + 26px);
  }

  .audit-workflow-stage.is-content-above :deep(.el-step__main) {
    bottom: calc(50% + 26px);
    flex-direction: column-reverse;
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
    min-height: 118px;
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

  .audit-stage-content {
    min-height: 0;
    padding: 4px 0 18px;
  }

  .audit-workflow-stage :deep(.el-step__description) {
    width: auto;
    max-width: 100%;
    margin-left: 0;
  }

  .audit-stage-content p {
    min-height: 0;
  }
}
</style>
