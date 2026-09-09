<script setup lang="ts">
import type { ReviewBRun } from '@/types/ai-review-b'
import { automationLimitationText } from '../automationLimitations'
defineProps<{ items: NonNullable<ReviewBRun['automationLimitations']> }>()
</script>

<template>
  <section v-if="items.length" class="automation-limitations" aria-label="尚需人工核验的系统能力">
    <h4>这些部分，系统还没核对完整</h4>
    <p>需要你或相应专业人员核验。这里说的是系统能力尚未完成，补文件不一定能解决。</p>
    <ul>
      <li v-for="item in items" :key="`${item.atomicCheckId}:${item.code}`">
        {{ automationLimitationText(item.code) }}
        <small v-if="item.atomicCheckId">（审查项 {{ item.atomicCheckId }}）</small>
      </li>
    </ul>
    <p>下面已有的问题和判断仍需处理；这份提示不会替代业务结论。</p>
  </section>
</template>

<style scoped>
.automation-limitations {
  padding: 16px;
  margin-bottom: 16px;
  color: var(--el-text-color-primary);
  background: var(--el-color-warning-light-9);
  border: 1px solid var(--el-color-warning);
  border-radius: 8px;
  overflow-wrap: anywhere;
}

h4,
p {
  margin: 0 0 8px;
}

li + li {
  margin-top: 8px;
}
</style>
