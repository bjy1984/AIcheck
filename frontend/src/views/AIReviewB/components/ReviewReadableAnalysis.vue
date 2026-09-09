<script setup lang="ts">
import { computed } from 'vue'
import type { ReviewBReference } from '@/types/ai-review-b'
import ReviewMarkdownText from './ReviewMarkdownText.vue'
const props = defineProps<{ content: string; references?: ReviewBReference[]; compact?: boolean }>()
const emit = defineEmits<{ 'open-reference': [reference: ReviewBReference] }>()
const long = computed(() => props.compact && props.content.length > 800)
</script>

<template>
  <details v-if="long" class="readable-analysis">
    <summary
      >查看完整分析 <span>{{ content.length }} 字 · 含全部说明与引用</span></summary
    >
    <ReviewMarkdownText
      :content="content"
      :references="references"
      @open-reference="emit('open-reference', $event)"
    />
  </details>
  <ReviewMarkdownText
    v-else
    :content="content"
    :references="references"
    @open-reference="emit('open-reference', $event)"
  />
</template>

<style scoped>
.readable-analysis {
  margin: 12px 0;
  color: var(--el-text-color-primary);
}

summary {
  min-height: 44px;
  padding: 12px;
  font-size: 14px;
  line-height: 1.6;
  cursor: pointer;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  box-sizing: border-box;
}

summary span {
  margin-left: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

summary:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: 3px;
}

.readable-analysis[open] > summary {
  margin-bottom: 12px;
}
</style>
