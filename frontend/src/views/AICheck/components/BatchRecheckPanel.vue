<script setup lang="ts">
/**
 * 一键审查的按钮与结果（0817 第 3 条）。
 *
 * ## 为什么单独成组件
 *
 * Workbench.vue 有行数棘轮。棘轮的用意就是逼新功能不要再往那个大文件里堆
 * ——直接加进去会触发棘轮，而抬高上限等于把这条约束取消掉。
 *
 * ## 这块界面的要点只有一个
 *
 * **跳过的必须列出来。**
 *
 * 只显示「已发起 N 个」的话，剩下的去哪了没人知道，监检会以为全跑过了
 * ——而「漏掉一个也不会有人发现」正是这个功能要消灭的状态。
 * 报喜不报忧的批量操作，比不做批量更危险。
 */
import { ElButton, ElTag } from 'element-plus'
import type { BatchRecheckPayload } from '@/api/aicheck'

defineProps<{
  loading: boolean
  disabled: boolean
  result?: BatchRecheckPayload
}>()

defineEmits<{ run: [] }>()
</script>

<template>
  <div class="batch-recheck">
    <ElButton
      class="batch-recheck-button"
      :loading="loading"
      :disabled="disabled"
      title="对本项目所有有已提交资料的节点一次性发起审查"
      @click="$emit('run')"
    >
      一键审查全部节点
    </ElButton>

    <div v-if="result" class="batch-recheck-result" aria-live="polite">
      <div class="batch-recheck-head">
        <strong>一键审查结果</strong>
        <span>
          <ElTag size="small" type="success" effect="plain">
            已发起 {{ result.startedCount }}
          </ElTag>
          <ElTag size="small" type="info" effect="plain"> 跳过 {{ result.skippedCount }} </ElTag>
          <!-- 上限也要说：不说的话用户不知道为什么少了几个 -->
          <ElTag size="small" effect="plain">单次上限 {{ result.batchLimit }}</ElTag>
        </span>
      </div>
      <ul v-if="result.skipped.length" class="batch-recheck-skipped">
        <li v-for="item in result.skipped" :key="item.nodeId">
          节点 {{ item.nodeId }}：{{ item.message }}
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.batch-recheck-result {
  margin-top: 8px;
  padding: 8px 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-fill-color-lighter);
}

.batch-recheck-head {
  display: flex;
  gap: 8px;
  align-items: baseline;
  justify-content: space-between;
  flex-wrap: wrap;
}

.batch-recheck-head :deep(.el-tag) {
  margin-left: 4px;
}

.batch-recheck-skipped {
  margin: 6px 0 0;
  padding-left: 18px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--el-text-color-regular);
}
</style>
