<script setup lang="ts">
/**
 * 结构化表格：用列名 + 行字典自己画表，不碰引擎 html。
 *
 * OCR 详情页与知识条款共用。引擎 html 是 XSS 面，仓库约定不下发、不渲染。
 */
defineProps<{
  columnNames: string[]
  rows: Array<Record<string, string>>
  headerReliable?: boolean
  caption?: string
}>()
</script>

<template>
  <div class="structured-table">
    <div v-if="caption" class="structured-table-caption">{{ caption }}</div>
    <div v-if="rows.length" class="structured-table-scroll">
      <table>
        <thead v-if="headerReliable !== false">
          <tr>
            <th v-for="col in columnNames" :key="col">{{ col }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, index) in rows" :key="index">
            <td v-for="col in columnNames" :key="col">{{ row[col] || '' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-else class="structured-table-empty">（表格无可显示的行）</p>
  </div>
</template>

<style scoped>
.structured-table-caption {
  margin-bottom: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.structured-table-scroll {
  overflow: auto;
  max-width: 100%;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

th,
td {
  border: 1px solid var(--el-border-color);
  padding: 4px 8px;
  text-align: left;
  vertical-align: top;
  white-space: pre-wrap;
  word-break: break-word;
}

th {
  background: var(--el-fill-color-light);
  font-weight: 600;
}

.structured-table-empty {
  margin: 0;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
