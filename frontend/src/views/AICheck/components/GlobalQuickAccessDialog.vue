<script setup lang="ts">
import { computed } from 'vue'
import {
  ElButton,
  ElDialog,
  ElEmpty,
  ElInput,
  ElTable,
  ElTableColumn,
  ElTabPane,
  ElTabs,
  ElTag
} from 'element-plus'
import type { MessageItem, SearchResult, TodoItem } from '@/types/aicheck'
import { getStatusTagType } from './status'

const props = defineProps<{
  modelValue: boolean
  activeTab: 'search' | 'todos' | 'messages'
  keyword: string
  searchResults: SearchResult[]
  todos: TodoItem[]
  messages: MessageItem[]
  loading: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'update:activeTab': [value: 'search' | 'todos' | 'messages']
  'update:keyword': [value: string]
  search: []
  completeTodo: [todoId: string]
  readMessage: [messageId: string]
  readAllMessages: []
  locateResult: [result: SearchResult]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})

const tab = computed({
  get: () => props.activeTab,
  set: (value) => emit('update:activeTab', value as 'search' | 'todos' | 'messages')
})

const searchKeyword = computed({
  get: () => props.keyword,
  set: (value) => emit('update:keyword', value)
})

const unreadCount = computed(() => props.messages.filter((item) => !item.read).length)
</script>

<template>
  <ElDialog v-model="visible" title="全局入口" width="min(920px, 94vw)" append-to-body>
    <ElTabs v-model="tab" class="quick-tabs">
      <ElTabPane label="搜索" name="search">
        <div class="search-bar">
          <ElInput
            v-model="searchKeyword"
            clearable
            placeholder="输入项目、节点、资料、报告或规则关键词"
            @keyup.enter="emit('search')"
          />
          <ElButton type="primary" :loading="loading" @click="emit('search')">搜索</ElButton>
        </div>

        <ElTable v-if="searchResults.length" :data="searchResults" border height="360">
          <ElTableColumn label="类型" width="96">
            <template #default="{ row }">
              <ElTag size="small" effect="plain">{{ row.type }}</ElTag>
            </template>
          </ElTableColumn>
          <ElTableColumn prop="title" label="结果" min-width="210" show-overflow-tooltip />
          <ElTableColumn prop="description" label="说明" min-width="260" show-overflow-tooltip />
          <ElTableColumn label="命中" min-width="160" show-overflow-tooltip>
            <template #default="{ row }">
              {{ row.highlights.join(' / ') }}
            </template>
          </ElTableColumn>
          <ElTableColumn label="操作" width="90">
            <template #default="{ row }">
              <ElButton link type="primary" @click="emit('locateResult', row)">定位</ElButton>
            </template>
          </ElTableColumn>
        </ElTable>
        <ElEmpty v-else description="暂无搜索结果" />
      </ElTabPane>

      <ElTabPane :label="`待办 ${todos.length}`" name="todos">
        <ElTable v-if="todos.length" :data="todos" border height="420">
          <ElTableColumn prop="title" label="待办事项" min-width="240" show-overflow-tooltip />
          <ElTableColumn prop="assigneeName" label="责任人" width="92" />
          <ElTableColumn prop="deadline" label="期限" width="158" />
          <ElTableColumn label="优先级" width="88">
            <template #default="{ row }">
              <ElTag :type="row.priority === '高' ? 'danger' : 'warning'" size="small">
                {{ row.priority }}
              </ElTag>
            </template>
          </ElTableColumn>
          <ElTableColumn label="状态" width="96">
            <template #default="{ row }">
              <ElTag :type="getStatusTagType(row.status)" size="small" effect="plain">
                {{ row.status }}
              </ElTag>
            </template>
          </ElTableColumn>
          <ElTableColumn label="操作" width="90">
            <template #default="{ row }">
              <ElButton
                link
                type="primary"
                :disabled="row.status === '已完成'"
                :loading="loading"
                @click="emit('completeTodo', row.id)"
              >
                完成
              </ElButton>
            </template>
          </ElTableColumn>
        </ElTable>
        <ElEmpty v-else description="暂无待办" />
      </ElTabPane>

      <ElTabPane :label="`消息 ${unreadCount}`" name="messages">
        <div class="message-toolbar">
          <span>未读 {{ unreadCount }} 条</span>
          <ElButton
            type="primary"
            plain
            :disabled="!unreadCount"
            :loading="loading"
            @click="emit('readAllMessages')"
          >
            全部已读
          </ElButton>
        </div>
        <ElTable v-if="messages.length" :data="messages" border height="370">
          <ElTableColumn label="状态" width="78">
            <template #default="{ row }">
              <ElTag :type="row.read ? 'info' : 'warning'" size="small" effect="plain">
                {{ row.read ? '已读' : '未读' }}
              </ElTag>
            </template>
          </ElTableColumn>
          <ElTableColumn prop="title" label="标题" min-width="190" show-overflow-tooltip />
          <ElTableColumn prop="content" label="内容" min-width="260" show-overflow-tooltip />
          <ElTableColumn prop="createdAt" label="时间" width="158" />
          <ElTableColumn label="操作" width="90">
            <template #default="{ row }">
              <ElButton
                link
                type="primary"
                :disabled="row.read"
                :loading="loading"
                @click="emit('readMessage', row.id)"
              >
                已读
              </ElButton>
            </template>
          </ElTableColumn>
        </ElTable>
        <ElEmpty v-else description="暂无消息" />
      </ElTabPane>
    </ElTabs>
  </ElDialog>
</template>

<style scoped>
.quick-tabs {
  min-height: 460px;
}

.search-bar,
.message-toolbar {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 12px;
}

.message-toolbar {
  justify-content: space-between;
}

.message-toolbar span {
  color: #667085;
}

@media (width <= 768px) {
  .search-bar,
  .message-toolbar {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
