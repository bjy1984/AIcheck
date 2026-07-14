<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { ElStep, ElSteps } from 'element-plus'
import type {
  InspectionAuditItem,
  InspectionAuditItemKey,
  InspectionAuditItemStatus
} from '@/types/aicheck'

const props = defineProps<{
  items: InspectionAuditItem[]
  modelValue: InspectionAuditItemKey
  loading?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [key: InspectionAuditItemKey]
  select: [item: InspectionAuditItem]
}>()

const directoryRef = ref<HTMLElement>()
const selectedIndex = computed(() =>
  Math.max(
    0,
    props.items.findIndex((item) => item.key === props.modelValue)
  )
)

const elementStepStatus = (status: InspectionAuditItemStatus) => {
  if (status === 'completed') return 'success'
  if (status === 'in_progress') return 'process'
  if (status === 'failed') return 'error'
  return 'wait'
}

const focusItem = async (key: InspectionAuditItemKey) => {
  await nextTick()
  directoryRef.value
    ?.querySelector<HTMLElement>(`[data-audit-item="${key}"]`)
    ?.focus({ preventScroll: true })
  directoryRef.value
    ?.querySelector<HTMLElement>(`[data-audit-item="${key}"]`)
    ?.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'smooth' })
}

const selectItem = (item: InspectionAuditItem) => {
  emit('update:modelValue', item.key)
  emit('select', item)
  void focusItem(item.key)
}

const handleKeydown = (event: KeyboardEvent, index: number) => {
  if (!props.items.length) return
  let targetIndex = index
  if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
    targetIndex = (index + 1) % props.items.length
  } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
    targetIndex = (index - 1 + props.items.length) % props.items.length
  } else if (event.key === 'Home') {
    targetIndex = 0
  } else if (event.key === 'End') {
    targetIndex = props.items.length - 1
  } else if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    selectItem(props.items[index])
    return
  } else {
    return
  }
  event.preventDefault()
  selectItem(props.items[targetIndex])
}
</script>

<template>
  <section
    ref="directoryRef"
    class="audit-item-directory"
    :class="{ 'is-loading': loading }"
    aria-label="审计项目录"
  >
    <div class="audit-item-directory__head">
      <div>
        <h2>审计项目录</h2>
        <p>各审计项独立办理，状态不代表前置顺序，也不会阻塞其他审计项。</p>
      </div>
      <span class="audit-item-directory__legend">当前查看：{{ items[selectedIndex]?.label }}</span>
    </div>

    <div class="audit-item-directory__scroll">
      <ElSteps
        :active="-1"
        direction="horizontal"
        align-center
        class="audit-item-directory__steps"
        role="tablist"
        aria-label="节点审计项"
      >
        <ElStep
          v-for="(item, index) in items"
          :key="item.key"
          :status="elementStepStatus(item.status)"
          :class="[
            'audit-item-directory__item',
            `is-${item.status}`,
            { 'is-selected': item.key === modelValue }
          ]"
          role="tab"
          :tabindex="item.key === modelValue ? 0 : -1"
          :aria-selected="item.key === modelValue"
          :aria-controls="`inspection-audit-panel-${item.key}`"
          :data-audit-item="item.key"
          @click="selectItem(item)"
          @keydown="handleKeydown($event, index)"
        >
          <template #icon>
            <span class="audit-stage-index" aria-hidden="true">{{ index + 1 }}</span>
          </template>
          <template #title>
            <div class="audit-stage-title">
              <strong>{{ item.label }}</strong>
              <span>{{ item.metric }}</span>
              <small class="audit-stage-status">
                <i aria-hidden="true"></i>{{ item.statusLabel }}
                <b v-if="item.issueCount">{{ item.issueCount }}</b>
              </small>
            </div>
          </template>
        </ElStep>
      </ElSteps>
    </div>

    <div v-if="items[selectedIndex]" class="audit-item-directory__summary" aria-live="polite">
      <div>
        <span>{{ items[selectedIndex].statusLabel }}</span>
        <strong>{{ items[selectedIndex].label }} · {{ items[selectedIndex].metric }}</strong>
        <p>{{ items[selectedIndex].summary }}</p>
      </div>
      <time v-if="items[selectedIndex].updatedAt">更新于 {{ items[selectedIndex].updatedAt }}</time>
    </div>
  </section>
</template>

<style scoped>
.audit-item-directory {
  --audit-item-color: var(--aicheck-text-subtle, #667085);

  padding: 16px 20px 18px;
  color: var(--aicheck-text, #26364e);
  background: var(--aicheck-surface, #fff);
  border-block: 1px solid var(--aicheck-border, #d4deeb);
}

.audit-item-directory__head,
.audit-item-directory__summary {
  display: flex;
  gap: 16px;
  align-items: center;
  justify-content: space-between;
}

.audit-item-directory__head h2,
.audit-item-directory__head p,
.audit-item-directory__summary p {
  margin: 0;
}

.audit-item-directory__head h2 {
  font-size: 16px;
  font-weight: 600;
  line-height: 24px;
  color: var(--aicheck-text-strong, #172033);
}

.audit-item-directory__head p {
  margin-top: 4px;
  font-size: 13px;
  line-height: 20px;
  color: var(--aicheck-text-muted, #52647d);
}

.audit-item-directory__legend {
  flex: none;
  font-size: 12px;
  font-weight: 600;
  color: var(--aicheck-text-muted, #52647d);
}

.audit-item-directory__scroll {
  margin-top: 16px;
  overflow: auto hidden;
  scrollbar-width: thin;
  scroll-snap-type: x proximity;
}

.audit-item-directory__steps {
  min-width: 910px;
  padding: 3px 2px 7px;
}

.audit-item-directory__item {
  --audit-item-color: var(--aicheck-text-subtle, #667085);

  min-width: 130px;
  min-height: 104px;
  cursor: pointer;
  border-radius: 8px;
  outline: none;
  scroll-snap-align: center;
  transition:
    background-color 180ms ease-out,
    box-shadow 180ms ease-out;
}

.audit-item-directory__item.is-in_progress {
  --audit-item-color: var(--aicheck-primary, #2563eb);
}

.audit-item-directory__item.is-needs_attention {
  --audit-item-color: var(--aicheck-warning, #b45309);
}

.audit-item-directory__item.is-failed {
  --audit-item-color: var(--aicheck-danger, #dc2626);
}

.audit-item-directory__item.is-completed {
  --audit-item-color: var(--aicheck-success, #16803c);
}

.audit-item-directory__item:hover {
  background: color-mix(in srgb, var(--audit-item-color) 7%, transparent);
}

.audit-item-directory__item.is-selected {
  background: color-mix(in srgb, var(--audit-item-color) 9%, transparent);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--audit-item-color) 42%, transparent);
}

.audit-item-directory__item:focus-visible {
  box-shadow:
    0 0 0 2px var(--aicheck-surface, #fff),
    0 0 0 4px var(--audit-item-color);
}

.audit-item-directory__item :deep(.el-step__head) {
  color: var(--audit-item-color) !important;
  border-color: var(--audit-item-color) !important;
}

.audit-item-directory__item :deep(.el-step__line) {
  background-color: var(--aicheck-border, #d4deeb) !important;
}

.audit-item-directory__item :deep(.el-step__line-inner) {
  width: 0 !important;
  border-width: 0 !important;
}

.audit-item-directory__item :deep(.el-step__icon) {
  width: 32px;
  height: 32px;
  background: var(--aicheck-surface, #fff);
  border: 2px solid var(--audit-item-color);
}

.audit-item-directory__item :deep(.el-step__main) {
  padding: 0 4px;
}

.audit-stage-index {
  position: relative;
  z-index: 1;
  display: grid;
  width: 28px;
  height: 28px;
  font-size: 12px;
  font-weight: 700;
  color: var(--audit-item-color);
  background: var(--aicheck-surface, #fff);
  border-radius: 50%;
  place-items: center;
}

.is-selected .audit-stage-index::after {
  position: absolute;
  z-index: -1;
  width: 28px;
  height: 28px;
  pointer-events: none;
  border: 2px solid var(--audit-item-color);
  border-radius: 50%;
  content: '';
  animation: audit-item-ripple 1.5s ease-out infinite;
}

.audit-stage-title {
  display: grid;
  min-width: 0;
  margin-top: 3px;
  text-align: center;
  gap: 2px;
}

.audit-stage-title strong {
  font-size: 14px;
  font-weight: 600;
  line-height: 20px;
  color: var(--aicheck-text, #26364e);
}

.audit-stage-title > span {
  overflow: hidden;
  font-size: 12px;
  font-weight: 500;
  line-height: 18px;
  color: var(--aicheck-text-muted, #52647d);
  text-overflow: ellipsis;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.audit-stage-status {
  display: inline-flex;
  min-height: 18px;
  margin: 0 auto;
  font-size: 12px;
  font-weight: 600;
  line-height: 18px;
  color: var(--audit-item-color);
  align-items: center;
  gap: 4px;
}

.audit-stage-status i {
  width: 6px;
  height: 6px;
  background: currentcolor;
  border-radius: 50%;
}

.audit-stage-status b {
  min-width: 18px;
  padding: 0 5px;
  font-size: 12px;
  line-height: 16px;
  color: var(--aicheck-surface, #fff);
  background: var(--audit-item-color);
  border-radius: 9px;
}

.audit-item-directory__summary {
  min-height: 72px;
  padding: 12px 14px;
  margin-top: 8px;
  background: var(--aicheck-bg-subtle, #f8fafc);
  border: 1px solid var(--aicheck-border, #d4deeb);
  border-radius: 6px;
}

.audit-item-directory__summary > div {
  min-width: 0;
}

.audit-item-directory__summary span,
.audit-item-directory__summary strong {
  display: block;
}

.audit-item-directory__summary span,
.audit-item-directory__summary time {
  font-size: 12px;
  color: var(--aicheck-text-muted, #52647d);
}

.audit-item-directory__summary strong {
  margin-top: 2px;
  font-size: 14px;
  color: var(--aicheck-text-strong, #172033);
}

.audit-item-directory__summary p {
  margin-top: 3px;
  font-size: 13px;
  line-height: 20px;
  color: var(--aicheck-text-muted, #52647d);
}

.audit-item-directory__summary time {
  flex: none;
  font-variant-numeric: tabular-nums;
}

.audit-item-directory.is-loading {
  pointer-events: none;
  opacity: 0.72;
}

@keyframes audit-item-ripple {
  from {
    opacity: 0.44;
    transform: scale(1);
  }

  to {
    opacity: 0;
    transform: scale(1.9);
  }
}

@media (width <= 900px) {
  .audit-item-directory {
    padding-inline: 14px;
  }

  .audit-item-directory__head,
  .audit-item-directory__summary {
    align-items: flex-start;
    flex-direction: column;
    gap: 6px;
  }

  .audit-item-directory__steps {
    min-width: 980px;
  }

  .audit-item-directory__summary time {
    align-self: flex-end;
  }
}

@media (prefers-reduced-motion: reduce) {
  .audit-item-directory__item,
  .is-selected .audit-stage-index::after {
    animation: none;
    transition: none;
  }

  .audit-item-directory__item {
    scroll-behavior: auto;
  }
}
</style>
