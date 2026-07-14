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
        <div class="audit-item-directory__heading">
          <h2>审计项导航</h2>
          <span>{{ items.length }} 项</span>
        </div>
        <p>选择审计项查看详情，各项独立办理、互不阻塞。</p>
      </div>
      <span class="audit-item-directory__legend">
        <small>当前查看</small>
        <strong>{{ items[selectedIndex]?.label }}</strong>
      </span>
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
          :aria-label="`${item.label}，${item.metric}，${item.statusLabel}`"
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
                <i aria-hidden="true"></i>
                <span>{{ item.statusLabel }}</span>
                <b v-if="item.issueCount">{{ item.issueCount }}</b>
              </small>
            </div>
          </template>
        </ElStep>
      </ElSteps>
    </div>

    <div
      v-if="items[selectedIndex]"
      :class="['audit-item-directory__summary', `is-${items[selectedIndex].status}`]"
      aria-live="polite"
    >
      <span class="audit-item-directory__summary-status">
        <i aria-hidden="true"></i>
        {{ items[selectedIndex].statusLabel }}
      </span>
      <div class="audit-item-directory__summary-content">
        <strong>
          {{ items[selectedIndex].label }}
          <small>{{ items[selectedIndex].metric }}</small>
        </strong>
        <p>{{ items[selectedIndex].summary }}</p>
      </div>
      <time v-if="items[selectedIndex].updatedAt">更新于 {{ items[selectedIndex].updatedAt }}</time>
    </div>
  </section>
</template>

<style scoped>
.audit-item-directory {
  --audit-item-color: var(--aicheck-text-subtle, #667085);

  padding: 18px 20px 16px;
  color: var(--aicheck-text, #26364e);
  background: var(--aicheck-surface, #fff);
  border: 1px solid var(--aicheck-border, #d4deeb);
  border-radius: 12px;
  box-shadow: 0 1px 2px rgb(15 23 42 / 4%);
}

.audit-item-directory__head {
  display: flex;
  gap: 16px;
  align-items: center;
  justify-content: space-between;
}

.audit-item-directory__head p,
.audit-item-directory__summary p {
  margin: 0;
}

.audit-item-directory__heading {
  display: flex;
  gap: 8px;
  align-items: center;
}

.audit-item-directory__head h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 650;
  line-height: 24px;
  color: var(--aicheck-text-strong, #172033);
}

.audit-item-directory__heading > span {
  padding: 1px 7px;
  font-size: 11px;
  font-weight: 650;
  line-height: 18px;
  color: var(--aicheck-text-muted, #52647d);
  background: var(--aicheck-surface-muted, #f2f6fb);
  border: 1px solid var(--aicheck-border-soft, #e5ecf6);
  border-radius: 999px;
  font-variant-numeric: tabular-nums;
}

.audit-item-directory__head p {
  margin-top: 2px;
  font-size: 12px;
  line-height: 18px;
  color: var(--aicheck-text-muted, #52647d);
}

.audit-item-directory__legend {
  display: inline-flex;
  flex: none;
  min-height: 32px;
  padding: 4px 5px 4px 10px;
  font-size: 12px;
  font-weight: 650;
  color: var(--aicheck-text-muted, #52647d);
  background: var(--aicheck-surface-soft, #f8fbff);
  border: 1px solid var(--aicheck-border-soft, #e5ecf6);
  border-radius: 999px;
  align-items: center;
  gap: 8px;
}

.audit-item-directory__legend small {
  font-size: 11px;
  font-weight: 500;
  color: var(--aicheck-text-subtle, #667085);
}

.audit-item-directory__legend strong {
  padding: 2px 9px;
  font-size: 12px;
  font-weight: 650;
  line-height: 20px;
  color: var(--aicheck-primary-strong, #174fa8);
  background: var(--aicheck-surface, #fff);
  border-radius: 999px;
  box-shadow: 0 1px 2px rgb(15 23 42 / 8%);
}

.audit-item-directory__scroll {
  padding: 9px 8px 7px;
  margin-top: 12px;
  overflow: auto hidden;
  background: var(--aicheck-surface-soft, #f8fbff);
  border: 1px solid var(--aicheck-border-soft, #e5ecf6);
  border-radius: 10px;
  scrollbar-width: thin;
  scroll-snap-type: x proximity;
}

.audit-item-directory__steps {
  min-width: 940px;
  padding: 2px 0;
}

.audit-item-directory__item {
  --audit-item-color: var(--aicheck-text-subtle, #667085);

  min-width: 134px;
  min-height: 112px;
  padding: 5px 7px 8px;
  cursor: pointer;
  background: color-mix(in srgb, var(--audit-item-color) 2%, var(--aicheck-surface, #fff));
  border: 1px solid color-mix(in srgb, var(--audit-item-color) 16%, transparent);
  border-radius: 10px;
  outline: none;
  scroll-snap-align: center;
  transition:
    border-color 180ms ease-out,
    background-color 180ms ease-out,
    box-shadow 180ms ease-out,
    transform 180ms ease-out;
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
  background: color-mix(in srgb, var(--audit-item-color) 5%, var(--aicheck-surface, #fff));
  border-color: color-mix(in srgb, var(--audit-item-color) 38%, transparent);
  transform: translateY(-1px);
}

.audit-item-directory__item.is-selected {
  background: var(--aicheck-surface, #fff);
  border-color: color-mix(in srgb, var(--audit-item-color) 68%, var(--aicheck-surface, #fff));
  transform: translateY(-1px);
  box-shadow:
    0 6px 18px color-mix(in srgb, var(--audit-item-color) 12%, transparent),
    inset 0 3px 0 color-mix(in srgb, var(--audit-item-color) 88%, transparent);
}

.audit-item-directory__item:focus-visible {
  box-shadow:
    0 0 0 2px var(--aicheck-surface, #fff),
    0 0 0 4px color-mix(in srgb, var(--audit-item-color) 70%, transparent);
}

.audit-item-directory__item :deep(.el-step__head) {
  color: var(--audit-item-color) !important;
  border-color: var(--audit-item-color) !important;
}

.audit-item-directory__item :deep(.el-step__line) {
  top: 15px;
  height: 1px;
  background-color: var(--aicheck-border-strong, #c2d1e3) !important;
}

.audit-item-directory__item :deep(.el-step__line-inner) {
  width: 0 !important;
  border-width: 0 !important;
}

.audit-item-directory__item :deep(.el-step__icon) {
  width: 30px;
  height: 30px;
  background: var(--aicheck-surface, #fff);
  border: 1.5px solid var(--audit-item-color);
  border-radius: 50%;
  box-shadow: 0 0 0 4px var(--aicheck-surface-soft, #f8fbff);
}

.audit-item-directory__item :deep(.el-step__main) {
  padding: 0 2px;
}

.audit-stage-index {
  position: relative;
  z-index: 1;
  display: grid;
  width: 27px;
  height: 27px;
  font-size: 11px;
  font-weight: 750;
  color: var(--audit-item-color);
  background: var(--aicheck-surface, #fff);
  border-radius: 50%;
  place-items: center;
  transition:
    color 180ms ease-out,
    background-color 180ms ease-out;
}

.is-selected .audit-stage-index {
  color: var(--aicheck-surface, #fff);
  background: var(--audit-item-color);
}

.is-selected .audit-stage-index::after {
  position: absolute;
  z-index: -1;
  width: 30px;
  height: 30px;
  pointer-events: none;
  border: 1.5px solid var(--audit-item-color);
  border-radius: 50%;
  content: '';
  animation: audit-item-ripple 1.45s ease-out 2;
}

.audit-stage-title {
  display: grid;
  min-width: 0;
  margin-top: 7px;
  text-align: center;
  gap: 3px;
}

.audit-stage-title strong {
  font-size: 14px;
  font-weight: 650;
  line-height: 20px;
  color: var(--aicheck-text-strong, #172033);
  transition: color 180ms ease-out;
}

.is-selected .audit-stage-title strong {
  color: var(--audit-item-color);
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
  min-height: 22px;
  padding: 1px 7px;
  margin: 2px auto 0;
  font-size: 11px;
  font-weight: 650;
  line-height: 18px;
  color: var(--audit-item-color);
  background: color-mix(in srgb, var(--audit-item-color) 7%, var(--aicheck-surface, #fff));
  border: 1px solid color-mix(in srgb, var(--audit-item-color) 22%, transparent);
  border-radius: 999px;
  align-items: center;
  gap: 4px;
}

.audit-stage-status i {
  width: 5px;
  height: 5px;
  background: currentcolor;
  border-radius: 50%;
}

.audit-stage-status b {
  min-width: 16px;
  padding: 0 4px;
  font-size: 10px;
  line-height: 14px;
  color: var(--aicheck-surface, #fff);
  background: var(--audit-item-color);
  border-radius: 999px;
}

.audit-item-directory__summary {
  --audit-item-color: var(--aicheck-text-subtle, #667085);

  display: grid;
  min-height: 62px;
  padding: 10px 12px;
  margin-top: 10px;
  background: color-mix(in srgb, var(--audit-item-color) 4%, var(--aicheck-surface, #fff));
  border: 1px solid color-mix(in srgb, var(--audit-item-color) 20%, var(--aicheck-border, #d4deeb));
  border-left: 3px solid var(--audit-item-color);
  border-radius: 8px;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
}

.audit-item-directory__summary.is-in_progress {
  --audit-item-color: var(--aicheck-primary, #2563eb);
}

.audit-item-directory__summary.is-needs_attention {
  --audit-item-color: var(--aicheck-warning, #b45309);
}

.audit-item-directory__summary.is-failed {
  --audit-item-color: var(--aicheck-danger, #dc2626);
}

.audit-item-directory__summary.is-completed {
  --audit-item-color: var(--aicheck-success, #16803c);
}

.audit-item-directory__summary-status {
  display: inline-flex;
  min-height: 24px;
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 650;
  line-height: 18px;
  color: var(--audit-item-color);
  background: var(--aicheck-surface, #fff);
  border: 1px solid color-mix(in srgb, var(--audit-item-color) 28%, transparent);
  border-radius: 999px;
  align-items: center;
  gap: 5px;
}

.audit-item-directory__summary-status i {
  width: 5px;
  height: 5px;
  background: currentcolor;
  border-radius: 50%;
}

.audit-item-directory__summary-content {
  min-width: 0;
}

.audit-item-directory__summary strong {
  display: flex;
  gap: 8px;
  align-items: baseline;
  font-size: 14px;
  font-weight: 650;
  color: var(--aicheck-text-strong, #172033);
}

.audit-item-directory__summary strong small {
  font-size: 11px;
  font-weight: 600;
  color: var(--aicheck-text-muted, #52647d);
  font-variant-numeric: tabular-nums;
}

.audit-item-directory__summary p {
  margin-top: 2px;
  overflow: hidden;
  font-size: 12px;
  line-height: 18px;
  color: var(--aicheck-text-muted, #52647d);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.audit-item-directory__summary time {
  flex: none;
  font-size: 11px;
  color: var(--aicheck-text-muted, #52647d);
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
    padding-block: 14px;
    padding-inline: 14px;
  }

  .audit-item-directory__head {
    align-items: flex-start;
    flex-direction: column;
    gap: 8px;
  }

  .audit-item-directory__legend {
    align-self: stretch;
    justify-content: space-between;
  }

  .audit-item-directory__steps {
    min-width: 966px;
  }

  .audit-item-directory__summary {
    grid-template-columns: auto minmax(0, 1fr);
  }

  .audit-item-directory__summary time {
    grid-column: 2;
  }

  .audit-item-directory__summary time {
    justify-self: start;
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
    transform: none;
  }
}
</style>
