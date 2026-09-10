<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElButton } from 'element-plus'
import type { DocumentPageRow } from './documentPagePresentation'
const props = defineProps<{ rows: DocumentPageRow[]; activePage?: number }>()
const emit = defineEmits<{ locate: [page: number] }>()
const expanded = ref(false)
watch(
  () => props.rows,
  () => {
    expanded.value = false
  }
)
const shown = computed(() => (expanded.value ? props.rows : props.rows.slice(0, 6)))
const pending = computed(() => props.rows.filter((row) => !row.identified).length)
</script>

<template>
  <section class="document-pages" aria-label="逐页资料辨识">
    <h4>这份文件里有哪些资料</h4>
    <p
      >已读到 {{ rows.length }} 页的文字，其中
      {{ pending }} 页还需确认类型。未列出的页不代表已核对。</p
    >
    <ul>
      <li v-for="row in shown" :key="row.pageNo">
        <ElButton
          text
          :aria-pressed="activePage === row.pageNo"
          @click="emit('locate', row.pageNo)"
        >
          <span>第 {{ row.pageNo }} 页 · {{ row.label }}</span>
          <span class="page-action">看原文</span>
        </ElButton>
      </li>
    </ul>
    <ElButton v-if="rows.length > 6" text @click="expanded = !expanded">
      {{ expanded ? '收起' : `查看全部 ${rows.length} 页` }}
    </ElButton>
    <p>这里只按标题辨识资料类型，还不是人工确认或审查结论。</p>
  </section>
</template>

<style scoped>
.document-pages {
  padding: 12px;
  margin-bottom: 16px;
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
}

h4 {
  margin: 0 0 8px;
}

p {
  margin: 8px 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}

ul {
  padding: 0;
  margin: 0;
  list-style: none;
}

li :deep(.el-button) {
  width: 100%;
  height: auto;
  min-height: 44px;
  text-align: left;
  white-space: normal;
}

li :deep(.el-button > span) {
  display: flex;
  width: 100%;
  justify-content: space-between;
  gap: 12px;
}

.page-action {
  flex-shrink: 0;
  color: var(--el-color-primary);
}

.document-pages > :deep(.el-button) {
  min-height: 44px;
}
</style>
