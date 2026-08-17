<script setup lang="ts">
/**
 * 节点的合并时间线：AI 回复和人工回复排在同一条线上（0817 第 3 条）。
 *
 * ## 为什么要合并显示
 *
 * 原先 AI 运行和人工结论分在两个列表里，监检要自己按时间对一遍——
 * **而人一旦要自己对时间，就一定会对错**，尤其是 AI 跑了几轮、
 * 中间还夹着人工改判的时候。
 *
 * ## 显示上的两个决定
 *
 * - **来源要一眼看出来。** AI 和人工用不同的颜色和图标，
 *   而不是都写成一行「结论：满足要求」——那样看不出是谁判的。
 * - **改判要显示「推翻了哪一条」。** 只并排列两条结论的话，
 *   看不出后一条是在推翻前一条，会被当成两次独立的判断。
 */
import { ElEmpty, ElTag, ElTimeline, ElTimelineItem } from 'element-plus'

export type NodeReviewTimelineEvent = {
  type: 'aiRun' | 'humanOpinion' | 'rectification'
  actor: 'ai' | 'human'
  at: string
  title: string
  summary: string
  conclusion?: string
  operator?: string
  overrides?: string
  refId?: string
}

export type AutoReviewStatus = {
  status: string
  reason: string
  source: 'none' | 'auto' | 'human'
  overriddenAutoConclusion: string
}

defineProps<{ events: NodeReviewTimelineEvent[]; status?: AutoReviewStatus }>()

const toneOf = (event: NodeReviewTimelineEvent) => {
  if (event.actor === 'human') return 'warning'
  return event.conclusion === '需补正' ? 'danger' : 'primary'
}
</script>

<template>
  <div class="node-review-timeline">
    <!-- 状态和时间线是同一件事的两个粒度：一个说「现在到哪了」，
         一个说「怎么走到这的」。拆在两处会让人对不上。
         状态必须连理由一起显示——**说不出理由的状态标签，
         和没有标签一样没用**，它只是让人以为自己知道了。 -->
    <div v-if="status" class="auto-review-status">
      <ElTag size="small" effect="plain">{{ status.status }}</ElTag>
      <small>{{ status.reason }}</small>
      <small v-if="status.overriddenAutoConclusion" class="overridden">
        （已覆盖 AI 判定：{{ status.overriddenAutoConclusion }}）
      </small>
    </div>
    <ElEmpty v-if="!events.length" description="该节点还没有审查记录" :image-size="64" />
    <ElTimeline v-else>
      <ElTimelineItem
        v-for="(event, index) in events"
        :key="`${event.type}-${event.refId || index}`"
        :timestamp="event.at || '时间未记录'"
        :type="toneOf(event)"
        placement="top"
      >
        <div class="timeline-head">
          <!-- 来源要一眼看出来：都写成一行「结论：xxx」的话，
               看不出是机器判的还是人判的 -->
          <ElTag size="small" :type="event.actor === 'human' ? 'warning' : 'info'" effect="plain">
            {{ event.actor === 'human' ? '人工' : 'AI' }}
          </ElTag>
          <strong>{{ event.title }}</strong>
          <small v-if="event.operator">· {{ event.operator }}</small>
        </div>
        <p class="timeline-summary">{{ event.summary }}</p>
        <!-- 改判要说清楚推翻了哪一条，否则会被当成两次独立的判断 -->
        <small v-if="event.overrides" class="timeline-overrides">
          该结论覆盖了 AI 判定（{{ event.overrides }}）
        </small>
      </ElTimelineItem>
    </ElTimeline>
  </div>
</template>

<style scoped>
.auto-review-status {
  display: flex;
  gap: 8px;
  align-items: baseline;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.auto-review-status .overridden {
  color: var(--el-color-warning);
}

.timeline-head {
  display: flex;
  gap: 6px;
  align-items: center;
}

.timeline-summary {
  margin: 4px 0 0;
  line-height: 1.7;
}

.timeline-overrides {
  color: var(--el-color-warning);
}
</style>
