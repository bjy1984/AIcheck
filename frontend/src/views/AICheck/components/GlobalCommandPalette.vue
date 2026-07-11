<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ElDialog, ElEmpty, ElInput, ElTag } from 'element-plus'
import { useRouter } from 'vue-router'
import { searchApi } from '@/api/aicheck'
import type { OperationArea, SearchResult } from '@/types/aicheck'
import { getAicheckErrorMessage } from '@/utils/aicheckError'
import { Icon } from '@/components/Icon'

const props = defineProps<{
  scope: OperationArea
  projectId?: string
  placeholder?: string
}>()

const router = useRouter()
const visible = ref(false)
const keyword = ref('')
const loading = ref(false)
const errorMessage = ref('')
const results = ref<SearchResult[]>([])
const activeIndex = ref(0)
const searchInputRef = ref<InstanceType<typeof ElInput> | null>(null)
let searchTimer: ReturnType<typeof setTimeout> | undefined
let searchSequence = 0

const activeResult = computed(() => results.value[activeIndex.value])
const resultTypeLabels: Record<SearchResult['type'], string> = {
  project: '项目',
  node: '节点',
  document: '资料',
  report: '报告',
  standard: '标准',
  rule: '规则',
  user: '用户',
  organization: '组织',
  audit_event: '审计事件',
  knowledge_file: '知识文件',
  knowledge_task: '知识任务',
  review_run: 'ReviewRun',
  ocr_run: 'OCR Run',
  incident: '事故'
}

const runSearch = async () => {
  const query = keyword.value.trim()
  const currentSequence = ++searchSequence
  if (!query) {
    results.value = []
    errorMessage.value = ''
    loading.value = false
    return
  }
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await searchApi({
      keyword: query,
      scope: props.scope,
      projectId: props.projectId,
      pageSize: 30
    })
    if (currentSequence !== searchSequence) return
    results.value = response?.data?.items || []
    activeIndex.value = 0
  } catch (error) {
    if (currentSequence !== searchSequence) return
    results.value = []
    errorMessage.value = getAicheckErrorMessage(error, '搜索失败，请检查网络后重试。')
  } finally {
    if (currentSequence === searchSequence) loading.value = false
  }
}

watch(keyword, () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(runSearch, 250)
})

const open = () => {
  visible.value = true
  errorMessage.value = ''
  nextTick(() => searchInputRef.value?.focus())
}

const close = () => {
  visible.value = false
}

const navigateTo = async (result: SearchResult | undefined) => {
  if (!result?.route) return
  close()
  await router.push(result.route)
}

const handleKeydown = (event: KeyboardEvent) => {
  if (event.key === 'ArrowDown' && results.value.length) {
    event.preventDefault()
    activeIndex.value = (activeIndex.value + 1) % results.value.length
  } else if (event.key === 'ArrowUp' && results.value.length) {
    event.preventDefault()
    activeIndex.value = (activeIndex.value - 1 + results.value.length) % results.value.length
  } else if (event.key === 'Enter') {
    event.preventDefault()
    navigateTo(activeResult.value)
  }
}

onBeforeUnmount(() => {
  if (searchTimer) clearTimeout(searchTimer)
})

defineExpose({ open, close })
</script>

<template>
  <ElDialog
    v-model="visible"
    class="command-palette-dialog"
    width="min(720px, calc(100vw - 32px))"
    append-to-body
    destroy-on-close
    :show-close="false"
    aria-label="全局命令搜索"
    @opened="searchInputRef?.focus()"
  >
    <template #header>
      <div class="command-header">
        <Icon icon="vi-ep:search" :size="20" aria-hidden="true" />
        <ElInput
          ref="searchInputRef"
          v-model="keyword"
          class="command-input"
          :placeholder="placeholder || '搜索项目、资料、任务或配置'"
          clearable
          autocomplete="off"
          aria-label="输入搜索关键词"
          @keydown="handleKeydown"
        />
        <kbd>Esc</kbd>
      </div>
    </template>

    <div class="command-body" aria-live="polite">
      <div v-if="errorMessage" class="command-error" role="alert">
        <span>{{ errorMessage }}</span>
        <button type="button" @click="runSearch">重试</button>
      </div>
      <div v-else-if="loading" class="command-loading">正在搜索真实业务数据...</div>
      <ElEmpty
        v-else-if="!results.length"
        :description="keyword.trim() ? '没有符合当前权限和范围的结果' : '输入关键词开始搜索'"
        :image-size="72"
      />
      <div v-else class="command-results" role="listbox" aria-label="搜索结果">
        <button
          v-for="(result, index) in results"
          :id="`command-result-${index}`"
          :key="`${result.type}-${result.id}`"
          type="button"
          :class="['command-result', { active: index === activeIndex }]"
          role="option"
          :aria-selected="index === activeIndex"
          @mouseenter="activeIndex = index"
          @click="navigateTo(result)"
        >
          <span class="command-result-icon" aria-hidden="true">
            <Icon icon="vi-ep:document" :size="18" />
          </span>
          <span class="command-result-main">
            <span class="command-result-title">{{ result.title }}</span>
            <span class="command-result-description">{{ result.description || '--' }}</span>
            <small>{{ result.breadcrumb || result.route }}</small>
          </span>
          <span class="command-result-meta">
            <ElTag size="small" effect="plain">{{ resultTypeLabels[result.type] }}</ElTag>
            <small v-if="result.status">{{ result.status }}</small>
          </span>
        </button>
      </div>
    </div>

    <template #footer>
      <div class="command-footer">
        <span><kbd>↑</kbd><kbd>↓</kbd> 选择</span>
        <span><kbd>Enter</kbd> 打开</span>
        <span>结果已按当前角色和项目范围过滤</span>
      </div>
    </template>
  </ElDialog>
</template>

<style scoped>
.command-header {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr) auto;
  min-height: 52px;
  padding: 0 18px;
  color: #52647d;
  align-items: center;
  gap: 10px;
}

.command-input :deep(.el-input__wrapper) {
  padding: 0;
  font-size: 16px;
  background: transparent;
  box-shadow: none;
}

kbd {
  display: inline-flex;
  min-width: 26px;
  min-height: 24px;
  padding: 2px 7px;
  font:
    500 12px/1 system-ui,
    sans-serif;
  color: #52647d;
  background: #f4f7fb;
  border: 1px solid #d4deeb;
  border-radius: 4px;
  align-items: center;
  justify-content: center;
}

.command-body {
  max-height: min(58vh, 560px);
  min-height: 240px;
  overflow: auto;
  border-block: 1px solid #e3eaf3;
}

.command-loading,
.command-error {
  display: flex;
  min-height: 160px;
  padding: 24px;
  color: #52647d;
  align-items: center;
  justify-content: center;
}

.command-error {
  color: #b42318;
  background: #fef3f2;
  gap: 12px;
}

.command-error button {
  min-height: 36px;
  padding: 0 12px;
  font-weight: 600;
  color: #b42318;
  cursor: pointer;
  background: #fff;
  border: 1px solid #f0b4ae;
  border-radius: 5px;
}

.command-results {
  padding: 8px;
}

.command-result {
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr) auto;
  width: 100%;
  min-height: 68px;
  padding: 10px 12px;
  font: inherit;
  color: #26364e;
  text-align: left;
  cursor: pointer;
  background: #fff;
  border: 1px solid transparent;
  border-radius: 6px;
  align-items: center;
  gap: 10px;
}

.command-result:hover,
.command-result.active,
.command-result:focus-visible {
  background: #f1f6fd;
  border-color: #bcd2f0;
  outline: 0;
  box-shadow: 0 0 0 3px rgb(31 102 216 / 10%);
}

.command-result-icon {
  display: grid;
  width: 34px;
  height: 34px;
  color: #1f66d8;
  background: #eaf2ff;
  border-radius: 5px;
  place-items: center;
}

.command-result-main,
.command-result-meta {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.command-result-title {
  overflow: hidden;
  font-size: 14px;
  font-weight: 600;
  color: #172033;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.command-result-description,
.command-result-main small,
.command-result-meta small {
  overflow: hidden;
  font-size: 12px;
  font-weight: 400;
  color: #52647d;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.command-result-meta {
  justify-items: end;
}

.command-footer {
  display: flex;
  min-height: 34px;
  color: #6e7d92;
  align-items: center;
  justify-content: flex-start;
  gap: 16px;
  flex-wrap: wrap;
}

.command-footer span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

@media (width <= 640px) {
  .command-result {
    grid-template-columns: 36px minmax(0, 1fr);
    min-height: 76px;
  }

  .command-result-meta {
    display: none;
  }

  .command-footer span:last-child {
    display: none;
  }
}
</style>

<style>
.command-palette-dialog.el-dialog {
  max-width: 720px;
  padding: 0;
  overflow: hidden;
  border-radius: 8px;
}

.command-palette-dialog .el-dialog__header,
.command-palette-dialog .el-dialog__body,
.command-palette-dialog .el-dialog__footer {
  padding: 0;
  margin: 0;
}

.command-palette-dialog .el-dialog__footer {
  padding: 8px 18px;
}
</style>
