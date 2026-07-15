<script setup lang="ts">
import {
  ElDescriptions,
  ElDescriptionsItem,
  ElProgress,
  ElTag,
  ElTimeline,
  ElTimelineItem
} from 'element-plus'

type StaticShellTone = 'blue' | 'green' | 'orange' | 'red'

type StaticShellRightCard = {
  title: string
  rows?: ReadonlyArray<{
    label: string
    value?: string
    valueBadge?: string
    valueTone?: StaticShellTone
    progress?: number
    progressTone?: StaticShellTone
  }>
  timeline?: ReadonlyArray<{
    title: string
    description: string
    tone?: StaticShellTone
  }>
  note?: string
}

defineProps<{
  title: string
  subtitle?: string
  cards: ReadonlyArray<StaticShellRightCard>
}>()

const toneColor: Record<StaticShellTone, string> = {
  blue: 'var(--aicheck-primary, #1f66d8)',
  green: 'var(--aicheck-success, #087443)',
  orange: 'var(--aicheck-warning, #8a4b00)',
  red: 'var(--aicheck-danger, #b42318)'
}

const tagType = (tone?: StaticShellTone) => {
  if (tone === 'green') return 'success'
  if (tone === 'orange') return 'warning'
  if (tone === 'red') return 'danger'
  return 'primary'
}
</script>

<template>
  <div class="static-shell-right-panel">
    <h2 class="right-title">{{ title }}</h2>
    <div v-if="subtitle" class="preview-name">{{ subtitle }}</div>
    <section v-for="card in cards" :key="card.title" class="right-card">
      <h3>{{ card.title }}</h3>
      <div class="body">
        <ElDescriptions v-if="card.rows?.length" :column="1" border size="small">
          <ElDescriptionsItem v-for="row in card.rows" :key="row.label" :label="row.label">
            <ElProgress
              v-if="row.progress !== undefined"
              :percentage="row.progress"
              :color="toneColor[row.progressTone || 'blue']"
              :stroke-width="8"
            />
            <template v-else>
              <span v-if="row.value">{{ row.value }}</span>
              <ElTag
                v-if="row.valueBadge"
                class="right-value-tag"
                :type="tagType(row.valueTone)"
                effect="light"
                size="small"
              >
                {{ row.valueBadge }}
              </ElTag>
            </template>
          </ElDescriptionsItem>
        </ElDescriptions>
        <ElTimeline v-if="card.timeline?.length" class="right-timeline">
          <ElTimelineItem
            v-for="item in card.timeline"
            :key="item.title"
            :color="toneColor[item.tone || 'blue']"
          >
            <strong>{{ item.title }}</strong>
            <p>{{ item.description }}</p>
          </ElTimelineItem>
        </ElTimeline>
        <div v-if="card.note" class="readonly-mask">{{ card.note }}</div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.right-title {
  margin: 0 0 8px;
  font-size: 21px;
  line-height: 1.2;
}

.preview-name {
  margin-bottom: 12px;
  font-weight: 600;
  color: #26364e;
}

.right-card {
  margin-top: 12px;
  overflow: hidden;
  background: var(--aicheck-surface, #fff);
  border: 1px solid var(--aicheck-border, #d4deeb);
  border-radius: 8px;
  box-shadow: var(--aicheck-shadow-xs, 0 1px 2px rgb(20 34 56 / 5%));
}

.right-card h3 {
  padding: 13px 16px;
  margin: 0;
  font-size: 16px;
  line-height: 1.3;
  background: var(--aicheck-surface-soft, #f8fbff);
  border-bottom: 1px solid var(--aicheck-border-soft, #e5ecf6);
}

.right-card .body {
  padding: 14px 16px;
}

.right-value-tag {
  margin-left: 6px;
}

.right-timeline {
  padding: 4px 0 0 4px;
  margin: 0;
}

.right-timeline strong {
  font-size: 14px;
  color: var(--aicheck-text-strong, #172033);
}

.right-timeline p {
  margin: 3px 0 0;
  font-size: 13px;
  line-height: 1.55;
  color: var(--aicheck-text-muted, #52647d);
}

.readonly-mask {
  padding: 9px 10px;
  margin-top: 10px;
  font-size: 13px;
  line-height: 1.5;
  color: #52647d;
  background: #f8fbff;
  border-radius: 6px;
}
</style>
