<script setup lang="ts">
import { computed } from 'vue'
import type {
  ContractorStatusCardKey,
  ContractorWorkbenchModel
} from './contractorWorkbenchViewModel'

const props = defineProps<{
  cards: ContractorWorkbenchModel['summaryCards']
  activeKey?: ContractorStatusCardKey | null
  feedbackUnavailable?: boolean
}>()

const emit = defineEmits<{
  select: [key: ContractorStatusCardKey]
}>()

/** 施工方看到的叫法：「待处理意见」就是被退回、要补正的事。 */
const LABELS: Record<string, string> = {
  feedback: '需补正',
  pending: '待提交',
  reviewing: '审核中'
}

const cardsWithIcons = computed(() =>
  props.cards.map((card) => ({
    ...card,
    tone:
      card.count === 0 || (card.key === 'feedback' && props.feedbackUnavailable)
        ? 'gray'
        : card.tone
  }))
)
</script>

<template>
  <!-- 2026-11-04 手机简化稿：一张卡三个大数字，点一下筛到对应资料 -->
  <section
    class="contractor-status-cards"
    aria-label="施工资料办理状态"
    data-guide="contractor-status"
  >
    <button
      v-for="card in cardsWithIcons"
      :key="card.key"
      type="button"
      :class="[
        'contractor-status-card',
        `is-${card.key}`,
        `is-${card.tone}`,
        { 'is-active': activeKey === card.key }
      ]"
      :aria-pressed="activeKey === card.key"
      :aria-label="
        card.key === 'feedback' && feedbackUnavailable
          ? '需补正数量暂不可用'
          : `${LABELS[card.key] || card.label} ${card.count} 项`
      "
      @click="emit('select', card.key)"
    >
      <span class="contractor-status-label">{{ LABELS[card.key] || card.label }}</span>
      <strong>{{ card.key === 'feedback' && feedbackUnavailable ? '—' : card.count }}</strong>
    </button>
  </section>
</template>

<style scoped>
.contractor-status-cards {
  display: grid;
  margin-bottom: 14px;
  overflow: hidden;
  background: #fff;
  border: 1px solid #e6ebf2;
  border-radius: 12px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.contractor-status-card {
  display: grid;
  min-height: 84px;
  padding: 12px 8px;
  font: inherit;
  color: #172033;
  cursor: pointer;
  background: transparent;
  border: 0;
  place-content: center;
  justify-items: center;
  gap: 4px;
}

.contractor-status-card + .contractor-status-card {
  border-left: 1px solid #eef1f6;
}

.contractor-status-card:hover,
.contractor-status-card:focus-visible {
  background: #f6f9ff;
  outline: 0;
}

.contractor-status-card.is-active {
  background: #eef4ff;
}

.contractor-status-label {
  font-size: 14px;
  color: #475467;
}

.contractor-status-card strong {
  font-size: 30px;
  line-height: 36px;
  font-variant-numeric: tabular-nums;
}

.contractor-status-card.is-feedback:not(.is-gray) strong {
  color: #d64545;
}

.contractor-status-card.is-reviewing:not(.is-gray) strong {
  color: #2f6bff;
}

.contractor-status-card.is-gray strong {
  color: #98a2b3;
}
</style>
