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
  const target = directoryRef.value?.querySelector<HTMLElement>(`[data-audit-item="${key}"]`)
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  target?.focus({ preventScroll: true })
  target?.scrollIntoView({
    block: 'nearest',
    inline: 'center',
    behavior: reduceMotion ? 'auto' : 'smooth'
  })
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
  <div ref="directoryRef" class="audit-item-directory" :class="{ 'is-loading': loading }">
    <div class="audit-item-directory__head">
      <div>
        <div class="audit-item-directory__heading">
          <h2>审计项</h2>
          <span>{{ items.length }} 项</span>
        </div>
        <p>选择一项查看详情，各项可独立处理。</p>
      </div>
      <span class="audit-item-directory__legend">
        <small>正在查看</small>
        <strong>{{ items[selectedIndex]?.label }}</strong>
      </span>
    </div>

    <div class="audit-item-directory__scroll" role="region" aria-label="审计项目录">
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
      <div class="audit-item-directory__summary-content">
        <strong>
          {{ items[selectedIndex].label }}
          <small>{{ items[selectedIndex].metric }}</small>
        </strong>
        <p>{{ items[selectedIndex].summary }}</p>
      </div>
      <span class="audit-item-directory__summary-status">
        <i aria-hidden="true"></i>
        {{ items[selectedIndex].statusLabel }}
      </span>
      <time v-if="items[selectedIndex].updatedAt">更新于 {{ items[selectedIndex].updatedAt }}</time>
    </div>
  </div>
</template>

<style scoped>
.audit-item-directory {
  --audit-item-color: var(--aicheck-text-subtle, #667085);
  --audit-directory-sky: #f4f8ff;
  --audit-directory-mint: #f2faf6;
  --audit-directory-text: #29374a;
  --audit-directory-muted: #53657a;

  display: contents;
  color: var(--aicheck-text, #26364e);
}

.audit-item-directory__head {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px 10px;
  background: linear-gradient(
    100deg,
    var(--aicheck-surface, #fff) 0%,
    var(--audit-directory-sky) 100%
  );
  border-radius: 12px 12px 0 0;
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
  font-size: 15px;
  font-weight: 600;
  line-height: 22px;
  color: var(--audit-directory-text);
}

.audit-item-directory__heading > span {
  padding: 1px 7px;
  font-size: 12px;
  font-weight: 500;
  line-height: 18px;
  color: var(--audit-directory-muted);
  background: color-mix(in srgb, var(--aicheck-primary, #1f66d8) 6%, transparent);
  border-radius: 999px;
  font-variant-numeric: tabular-nums;
}

.audit-item-directory__head p {
  margin-top: 2px;
  font-size: 12px;
  font-weight: 400;
  line-height: 18px;
  color: var(--audit-directory-muted);
}

.audit-item-directory__legend {
  display: inline-flex;
  flex: none;
  min-height: 30px;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 500;
  color: var(--audit-directory-muted);
  background: color-mix(in srgb, var(--aicheck-primary, #1f66d8) 6%, var(--aicheck-surface, #fff));
  border-radius: 999px;
  align-items: center;
  gap: 8px;
}

.audit-item-directory__legend small {
  font-size: 12px;
  font-weight: 400;
  color: var(--audit-directory-muted);
}

.audit-item-directory__legend strong {
  padding: 0;
  font-size: 12px;
  font-weight: 600;
  line-height: 18px;
  color: var(--aicheck-primary-strong, #174fa8);
}

.audit-item-directory__scroll {
  position: sticky;
  top: 0;
  z-index: 20;
  padding: 8px 8px 6px;
  overflow: auto hidden;
  background: linear-gradient(110deg, var(--audit-directory-sky), var(--audit-directory-mint));
  border-radius: 12px;
  box-shadow: 0 4px 14px rgb(36 51 73 / 6%);
  isolation: isolate;
  scrollbar-width: thin;
  scroll-snap-type: x proximity;
}

.audit-item-directory__steps {
  min-width: 896px;
  padding: 2px 0;
}

.audit-item-directory__item {
  --audit-item-color: var(--aicheck-text-subtle, #667085);

  min-width: 128px;
  min-height: 98px;
  padding: 4px 6px 7px;
  cursor: pointer;
  background: transparent;
  border-radius: 12px;
  outline: none;
  scroll-snap-align: center;
  touch-action: manipulation;
  transition:
    background-color 180ms ease-out,
    box-shadow 180ms ease-out,
    transform 120ms ease-out;
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
  background: color-mix(in srgb, var(--audit-item-color) 3%, var(--aicheck-surface, #fff));
}

.audit-item-directory__item.is-selected {
  background: color-mix(in srgb, var(--audit-item-color) 5%, var(--aicheck-surface, #fff));
  box-shadow: 0 3px 10px color-mix(in srgb, var(--audit-item-color) 8%, transparent);
}

.audit-item-directory__item:active {
  transform: scale(0.99);
}

.audit-item-directory__item:focus-visible {
  box-shadow:
    0 0 0 2px var(--aicheck-surface, #fff),
    0 0 0 4px color-mix(in srgb, var(--audit-item-color) 70%, transparent);
}

.audit-item-directory__item :deep(.el-step__head) {
  color: var(--audit-item-color) !important;
}

.audit-item-directory__item :deep(.el-step__line) {
  top: 14px;
  height: 1px;
  background-color: #d9e2ec !important;
}

.audit-item-directory__item :deep(.el-step__line-inner) {
  width: 0 !important;
  border-width: 0 !important;
}

.audit-item-directory__item :deep(.el-step__icon) {
  width: 28px;
  height: 28px;
  background: color-mix(in srgb, var(--audit-item-color) 10%, var(--aicheck-surface, #fff));
  border: 0;
  border-radius: 50%;
}

.audit-item-directory__item :deep(.el-step__main) {
  padding: 0 2px;
}

.audit-stage-index {
  position: relative;
  z-index: 1;
  display: grid;
  width: 25px;
  height: 25px;
  font-size: 12px;
  font-weight: 600;
  color: var(--audit-item-color);
  background: transparent;
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
  width: 28px;
  height: 28px;
  pointer-events: none;
  background: color-mix(in srgb, var(--audit-item-color) 16%, transparent);
  border-radius: 50%;
  content: '';
  animation: audit-item-ripple 1.1s cubic-bezier(0.2, 0.7, 0.2, 1) 1;
}

.audit-stage-title {
  display: grid;
  min-width: 0;
  margin-top: 5px;
  text-align: center;
  gap: 2px;
}

.audit-stage-title strong {
  font-size: 13px;
  font-weight: 600;
  line-height: 19px;
  color: var(--audit-directory-text);
  transition: color 180ms ease-out;
}

.is-selected .audit-stage-title strong {
  color: var(--audit-item-color);
}

.audit-stage-title > span {
  overflow: hidden;
  font-size: 12px;
  font-weight: 400;
  line-height: 17px;
  color: var(--audit-directory-muted);
  text-overflow: ellipsis;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.audit-stage-status {
  display: inline-flex;
  min-height: 20px;
  padding: 1px 6px;
  margin: 1px auto 0;
  font-size: 12px;
  font-weight: 500;
  line-height: 17px;
  color: var(--audit-item-color);
  background: transparent;
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
  min-width: 18px;
  padding: 0 5px;
  font-size: 12px;
  font-weight: 600;
  line-height: 16px;
  color: var(--aicheck-surface, #fff);
  background: var(--audit-item-color);
  border-radius: 999px;
}

.is-in_progress .audit-stage-status,
.is-completed .audit-stage-status {
  background: color-mix(in srgb, var(--audit-item-color) 4%, var(--aicheck-surface, #fff));
}

.is-needs_attention .audit-stage-status,
.is-failed .audit-stage-status {
  background: color-mix(in srgb, var(--audit-item-color) 6%, var(--aicheck-surface, #fff));
}

.audit-item-directory__summary {
  --audit-item-color: var(--aicheck-text-subtle, #667085);

  display: grid;
  min-height: 54px;
  padding: 8px 12px;
  margin: 8px 0 14px;
  background: color-mix(in srgb, var(--audit-item-color) 4%, var(--aicheck-surface, #fff));
  border-radius: 10px;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 10px;
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
  min-height: 22px;
  padding: 2px 7px;
  font-size: 12px;
  font-weight: 500;
  line-height: 17px;
  color: var(--audit-item-color);
  background: color-mix(in srgb, var(--aicheck-surface, #fff) 72%, transparent);
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
  font-size: 13px;
  font-weight: 600;
  line-height: 19px;
  color: var(--audit-directory-text);
}

.audit-item-directory__summary strong small {
  font-size: 12px;
  font-weight: 500;
  color: var(--audit-directory-muted);
  font-variant-numeric: tabular-nums;
}

.audit-item-directory__summary p {
  margin-top: 2px;
  overflow: hidden;
  font-size: 12px;
  font-weight: 400;
  line-height: 18px;
  color: var(--audit-directory-muted);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.audit-item-directory__summary time {
  flex: none;
  font-size: 12px;
  line-height: 18px;
  color: var(--audit-directory-muted);
  font-variant-numeric: tabular-nums;
}

.audit-item-directory.is-loading > * {
  pointer-events: none;
  opacity: 0.72;
}

@keyframes audit-item-ripple {
  from {
    opacity: 0.22;
    transform: scale(1);
  }

  to {
    opacity: 0;
    transform: scale(1.65);
  }
}

@media (width <= 900px) {
  .audit-item-directory__head {
    align-items: flex-start;
    flex-direction: column;
    gap: 8px;
    padding: 12px 14px 9px;
  }

  .audit-item-directory__legend {
    align-self: stretch;
    justify-content: space-between;
  }

  .audit-item-directory__summary {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .audit-item-directory__summary-content {
    grid-column: 1 / -1;
  }

  .audit-item-directory__summary time {
    grid-column: 2;
    justify-self: end;
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
