<script setup lang="ts">
import { computed } from 'vue'
import { indexCountWidth, indexRecordCount } from '../knowledgeIndexCounts'

const props = defineProps<{ chunks?: number; vectors?: number; scale: number }>()
const rows = computed(() => [
  {
    key: 'chunks',
    label: '切片',
    count: indexRecordCount(props.chunks),
    width: indexCountWidth(props.chunks, props.scale)
  },
  {
    key: 'vectors',
    label: '向量',
    count: indexRecordCount(props.vectors),
    width: indexCountWidth(props.vectors, props.scale)
  }
])
</script>

<template>
  <div class="index-counts" aria-label="切片与向量记录数量，同尺度比较">
    <div v-for="row in rows" :key="row.key" class="index-count-row">
      <span>{{ row.label }}</span>
      <span class="index-count-track" aria-hidden="true">
        <span
          v-if="row.width !== null"
          :class="['index-count-fill', row.key]"
          :style="{ width: `${row.width}%` }"
        ></span>
      </span>
      <strong>{{ row.count === null ? '未取得' : row.count.toLocaleString('zh-CN') }}</strong>
    </div>
  </div>
</template>

<style scoped>
.index-counts {
  display: grid;
  min-width: 170px;
  gap: 5px;
}
.index-count-row {
  display: grid;
  grid-template-columns: 28px minmax(40px, 1fr) minmax(36px, auto);
  gap: 8px;
  align-items: center;
  font-size: 12px;
}
.index-count-row > span:first-child {
  color: var(--el-text-color-regular);
}
.index-count-row strong {
  text-align: right;
  font-size: 12px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.index-count-track {
  height: 6px;
  overflow: hidden;
  background: var(--el-fill-color-light);
  border-radius: 2px;
}
.index-count-fill {
  display: block;
  height: 100%;
  background: #64748b;
}
.index-count-fill.vectors {
  background: var(--el-color-primary);
}
</style>
