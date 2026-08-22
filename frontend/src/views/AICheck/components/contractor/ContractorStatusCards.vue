<script setup lang="ts">
import { ChatDotRound, DocumentChecked, Tickets } from '@element-plus/icons-vue'
import { computed } from 'vue'
import type {
  ContractorStatusCardKey,
  ContractorWorkbenchModel
} from './contractorWorkbenchViewModel'

const props = defineProps<{
  cards: ContractorWorkbenchModel['summaryCards']
  activeKey?: ContractorStatusCardKey | null
}>()

const emit = defineEmits<{
  select: [key: ContractorStatusCardKey]
}>()

const iconByKey = {
  feedback: ChatDotRound,
  pending: Tickets,
  reviewing: DocumentChecked
}

const cardsWithIcons = computed(() =>
  props.cards.map((card) => ({ ...card, icon: iconByKey[card.key] }))
)
</script>

<template>
  <section class="contractor-status-cards" aria-label="施工资料办理状态">
    <button
      v-for="card in cardsWithIcons"
      :key="card.key"
      type="button"
      :class="[
        'contractor-status-card',
        `is-${card.tone}`,
        { 'is-active': activeKey === card.key }
      ]"
      :aria-pressed="activeKey === card.key"
      :aria-label="`${card.label} ${card.count} 项`"
      @click="emit('select', card.key)"
    >
      <span class="contractor-status-icon" aria-hidden="true">
        <component :is="card.icon" />
      </span>
      <span class="contractor-status-label">{{ card.label }}</span>
      <strong>{{ card.count }}</strong>
    </button>
  </section>
</template>

<style scoped>
.contractor-status-cards {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 14px;
}

.contractor-status-card {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 12px;
  align-items: center;
  min-height: 72px;
  padding: 14px 18px;
  color: #1f2a44;
  text-align: left;
  cursor: pointer;
  background: #fff;
  border: 1px solid #dfe6f1;
  border-radius: 8px;
  box-shadow: 0 5px 14px rgb(15 23 42 / 4%);
  transition:
    border-color 0.15s ease,
    box-shadow 0.15s ease,
    transform 0.15s ease;
}

.contractor-status-card:hover {
  border-color: #9ebcff;
  transform: translateY(-1px);
  box-shadow: 0 8px 18px rgb(47 111 237 / 10%);
}

.contractor-status-card:focus-visible {
  outline: 3px solid rgb(47 111 237 / 24%);
  outline-offset: 2px;
}

.contractor-status-card.is-active {
  border-color: #2f6fed;
  box-shadow: 0 0 0 2px rgb(47 111 237 / 12%);
}

.contractor-status-icon {
  display: inline-grid;
  width: 38px;
  height: 38px;
  place-items: center;
  color: #2f6fed;
  background: #eef4ff;
  border-radius: 50%;
}

.contractor-status-icon :deep(svg) {
  width: 21px;
  height: 21px;
}

.contractor-status-card.is-orange .contractor-status-icon {
  color: #f79009;
  background: #fff5e7;
}

.contractor-status-card.is-green .contractor-status-icon {
  color: #12a66a;
  background: #eaf8f1;
}

.contractor-status-label {
  font-size: 15px;
  font-weight: 600;
}

.contractor-status-card strong {
  font-size: 26px;
  line-height: 1;
  color: #172b4d;
}

@media (width <= 767px) {
  .contractor-status-cards {
    grid-template-columns: 1fr;
  }

  .contractor-status-card {
    min-height: 64px;
  }
}
</style>
