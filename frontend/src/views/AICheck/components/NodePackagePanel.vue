<script setup lang="ts">
import { computed } from 'vue'
import { ElAlert, ElButton, ElEmpty, ElTag } from 'element-plus'
import type { NodePackagePayload } from '@/types/aicheck'
import { getStatusTagType } from './status'
import { documentBindingSummary } from '@/utils/acceptanceFlows'
import { submittedFileCountLabel } from '../workbenchRolePresentation'

const props = defineProps<{
  packageData?: NodePackagePayload
  loading: boolean
  issue?: {
    type: 'error' | 'forbidden' | 'readonly' | 'empty'
    title: string
    message?: string
  }
  retryLoading?: boolean
  showTechnicalStatus?: boolean
}>()

const emit = defineEmits<{
  openFile: [documentId: string]
  retry: []
}>()

const selectedNode = computed(() => props.packageData?.node)
const requirements = computed(() => props.packageData?.requirements || [])
const bindings = computed(() => props.packageData?.bindings || [])
const projectFiles = computed(() => props.packageData?.projectFiles || [])
const projectFileStatus = (file: NodePackagePayload['projectFiles'][number]) =>
  documentBindingSummary(file)
const submittedFiles = computed(() => submittedFileCountLabel(bindings.value.length))
const alertType = computed(() => {
  if (props.issue?.type === 'error') return 'error'
  if (props.issue?.type === 'forbidden') return 'warning'
  return 'info'
})
</script>

<template>
  <!-- 2026-11-04 建设方手机版：三张表改成列表，手机上不横滑。只有建设方的节点抽屉用这个组件。 -->
  <section class="node-panel" v-loading="loading" aria-label="节点资料">
    <div class="panel-header">
      <span class="panel-subtitle">
        {{ selectedNode?.groupName || '-' }} · 节点 {{ selectedNode?.nodeId || '-' }}
        <template v-if="selectedNode?.inspectionType">
          · {{ selectedNode.inspectionType }} 类</template
        >
        · {{ submittedFiles }}
      </span>
      <ElTag :type="getStatusTagType(selectedNode?.status)" effect="light">
        {{ selectedNode?.status || '-' }}
      </ElTag>
    </div>

    <div v-if="issue" class="node-issue">
      <ElEmpty v-if="issue.type === 'empty'" :description="issue.title">
        <div v-if="issue.message" class="node-issue-message">{{ issue.message }}</div>
        <ElButton type="primary" :loading="retryLoading" @click="emit('retry')">
          重新加载节点
        </ElButton>
      </ElEmpty>
      <ElAlert v-else :title="issue.title" :type="alertType" :closable="false" show-icon>
        <template #default>
          <div class="node-issue-content">
            <span>{{ issue.message }}</span>
            <ElButton size="small" :loading="retryLoading" @click="emit('retry')">
              重新加载节点
            </ElButton>
          </div>
        </template>
      </ElAlert>
    </div>

    <template v-else-if="packageData">
      <div class="section-title">资料要求</div>
      <!-- 资料名在 note 里（焊工资格证、焊工名册…）；name 是审查点名，每行都一样，不再重复 -->
      <ul v-if="requirements.length" class="node-list">
        <li v-for="row in requirements" :key="row.id">
          <span class="node-list-main">{{ row.note || row.name }}</span>
          <ElTag :type="row.requiredType === '必传' ? 'danger' : 'info'" size="small">
            {{ row.requiredType }}
          </ElTag>
        </li>
      </ul>
      <p v-else class="node-empty">这个节点没有配置资料要求。</p>

      <div class="section-title">已挂载资料</div>
      <ul v-if="bindings.length" class="node-list">
        <li v-for="row in bindings" :key="row.id">
          <button type="button" class="node-file" @click="emit('openFile', row.documentId)">
            <span class="node-list-main">{{ row.fileName }}</span>
            <small>{{ [row.usage, row.sourceOrgName].filter(Boolean).join(' · ') }}</small>
          </button>
          <ElTag :type="getStatusTagType(row.bindingStatus)" size="small" effect="plain">
            {{ row.bindingStatus }}
          </ElTag>
        </li>
      </ul>
      <p v-else class="node-empty">还没有挂载资料。</p>

      <!-- 项目资料池是全项目的，不属于这个节点：收起来，要看再展开 -->
      <details v-if="projectFiles.length" class="node-pool">
        <summary>项目全部资料（{{ projectFiles.length }} 份）</summary>
        <ul class="node-list">
          <li v-for="row in projectFiles" :key="row.id">
            <button type="button" class="node-file" @click="emit('openFile', row.id)">
              <span class="node-list-main">{{ row.fileName }}</span>
              <small>
                {{
                  [
                    row.sourceOrgName,
                    showTechnicalStatus !== false ? row.currentOcrStatus : '',
                    row.updatedAt
                  ]
                    .filter(Boolean)
                    .join(' · ')
                }}
              </small>
            </button>
            <ElTag :type="getStatusTagType(projectFileStatus(row))" size="small" effect="plain">
              {{ projectFileStatus(row) }}
            </ElTag>
          </li>
        </ul>
      </details>

      <slot name="actions"></slot>
    </template>

    <ElEmpty v-else description="请选择节点" />
  </section>
</template>

<style scoped>
.node-panel {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 4px;
}

.panel-header {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 8px;
}

.panel-subtitle {
  min-width: 0;
  font-size: 13px;
  line-height: 20px;
  color: #667085;
}

.node-issue {
  min-height: 240px;
}

.node-issue-content {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  line-height: 22px;
}

.node-issue-content span,
.node-issue-message {
  overflow-wrap: anywhere;
}

.node-issue-message {
  margin-bottom: 12px;
  color: #667085;
}

.section-title {
  margin: 14px 0 4px;
  font-size: 15px;
  font-weight: 600;
  color: #172033;
}

.node-list {
  display: grid;
  padding: 0;
  margin: 0;
  list-style: none;
  grid-template-columns: minmax(0, 1fr);
}

.node-list li {
  display: flex;
  gap: 12px;
  align-items: center;
  min-height: 48px;
}

.node-list li + li {
  border-top: 1px solid #eef1f6;
}

.node-list-main {
  min-width: 0;
  overflow: hidden;
  font-size: 14px;
  line-height: 20px;
  color: #172033;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1 1 auto;
}

.node-file {
  display: grid;
  min-width: 0;
  padding: 6px 0;
  font: inherit;
  text-align: left;
  cursor: pointer;
  background: none;
  border: 0;
  flex: 1 1 auto;
  gap: 2px;
}

.node-file small {
  overflow: hidden;
  font-size: 12px;
  color: #667085;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.node-file:hover .node-list-main {
  color: var(--el-color-primary, #2f6bff);
}

.node-empty {
  margin: 4px 0;
  font-size: 13px;
  color: #667085;
}

.node-pool {
  margin-top: 14px;
  border-top: 1px solid #eef1f6;
}

.node-pool summary {
  min-height: 44px;
  padding: 12px 0;
  font-size: 14px;
  font-weight: 600;
  color: #172033;
  cursor: pointer;
}

@media (width <= 768px) {
  .node-issue-content {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
