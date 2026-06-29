<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElCol,
  ElEmpty,
  ElRow,
  ElSelect,
  ElOption,
  ElSpace,
  ElTable,
  ElTableColumn,
  ElTag
} from 'element-plus'
import { getProjectReviewWorkbenchApi, listWorkbenchProjectsApi } from '@/api/aicheck'
import type { GenericReviewWorkbenchPayload } from '@/api/aicheck'
import type { Project } from '@/types/aicheck'

const loading = ref(false)
const error = ref('')
const projects = ref<Project[]>([])
const selectedProjectId = ref('')
const workbench = ref<GenericReviewWorkbenchPayload | null>(null)

const genericProjects = computed(() =>
  projects.value.filter((project) => project.businessPackId !== 'engineering_inspection_v1')
)

const selectedProject = computed(() =>
  projects.value.find((project) => project.id === selectedProjectId.value)
)

const severityType = (severity?: string) => {
  if (severity === 'high') return 'danger'
  if (severity === 'medium') return 'warning'
  return 'info'
}

const loadWorkbench = async () => {
  if (!selectedProjectId.value) return
  loading.value = true
  error.value = ''
  try {
    const res = await getProjectReviewWorkbenchApi(selectedProjectId.value)
    if (!res) {
      error.value = '通用资料审查工作台加载失败。'
      return
    }
    workbench.value = res.data
  } catch {
    error.value = '通用资料审查工作台加载失败。'
  } finally {
    loading.value = false
  }
}

const loadData = async () => {
  loading.value = true
  error.value = ''
  try {
    const res = await listWorkbenchProjectsApi('admin')
    if (!res) {
      error.value = '项目列表加载失败。'
      return
    }
    projects.value = res.data
    selectedProjectId.value = genericProjects.value[0]?.id || projects.value[0]?.id || ''
    await loadWorkbench()
  } catch {
    error.value = '通用资料审查工作台加载失败。'
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
</script>

<template>
  <div class="generic-workbench">
    <div class="page-title">
      <div>
        <h1>通用资料审查工作台</h1>
        <p>按业务包展示节点、资料要求、AI 发现和人工确认入口</p>
      </div>
      <ElTag :type="loading ? 'warning' : 'success'" effect="plain">
        {{ loading ? '加载中' : '已连接' }}
      </ElTag>
    </div>

    <ElAlert v-if="error" type="error" show-icon :closable="false" :title="error" class="mb-12px" />

    <ElRow :gutter="16">
      <ElCol :span="24">
        <ElCard shadow="never" class="panel">
          <template #header>
            <div class="panel-header">
              <span>业务包项目</span>
              <ElSpace>
                <ElSelect
                  v-model="selectedProjectId"
                  filterable
                  style="width: 320px"
                  @change="loadWorkbench"
                >
                  <ElOption
                    v-for="project in projects"
                    :key="project.id"
                    :label="`${project.name} / ${project.businessPackId || '默认业务包'}`"
                    :value="project.id"
                  />
                </ElSelect>
                <ElButton plain type="primary" :loading="loading" @click="loadWorkbench">
                  刷新
                </ElButton>
              </ElSpace>
            </div>
          </template>

          <div v-if="workbench" class="generic-summary">
            <div>
              <div class="summary-label">项目</div>
              <strong>{{ selectedProject?.name || workbench.project.name }}</strong>
            </div>
            <div>
              <div class="summary-label">业务包</div>
              <strong>{{ workbench.businessPack.name }}</strong>
            </div>
            <div>
              <div class="summary-label">节点</div>
              <strong>{{ workbench.nodes.length }}</strong>
            </div>
            <div>
              <div class="summary-label">AI 发现</div>
              <strong>{{ workbench.findings.length }}</strong>
            </div>
          </div>
          <ElEmpty v-else description="请选择业务包项目" />
        </ElCard>
      </ElCol>
    </ElRow>

    <ElRow v-if="workbench" :gutter="16" class="mt-16px">
      <ElCol :xl="13" :lg="13" :md="24" :sm="24" :xs="24">
        <ElCard shadow="never" class="panel">
          <template #header>
            <div class="panel-header">
              <span>节点与资料进度</span>
              <ElTag effect="plain">{{ workbench.businessPack.domainType }}</ElTag>
            </div>
          </template>
          <ElTable :data="workbench.nodes" border height="420">
            <ElTableColumn prop="code" label="编码" width="92" />
            <ElTableColumn prop="name" label="节点" min-width="190" show-overflow-tooltip />
            <ElTableColumn prop="groupName" label="分组" min-width="130" show-overflow-tooltip />
            <ElTableColumn label="资料进度" width="110">
              <template #default="{ row }">
                {{ row.requiredProgress.done }}/{{ row.requiredProgress.total }}
              </template>
            </ElTableColumn>
            <ElTableColumn prop="status" label="状态" width="120" />
          </ElTable>
        </ElCard>
      </ElCol>

      <ElCol :xl="11" :lg="11" :md="24" :sm="24" :xs="24">
        <ElCard shadow="never" class="panel">
          <template #header>
            <div class="panel-header">
              <span>证据化审查发现</span>
              <ElTag type="warning" effect="plain">待人工确认</ElTag>
            </div>
          </template>
          <ElTable :data="workbench.findings" border height="420">
            <ElTableColumn prop="title" label="发现" min-width="180" show-overflow-tooltip />
            <ElTableColumn label="等级" width="86">
              <template #default="{ row }">
                <ElTag :type="severityType(row.severity)" size="small" effect="plain">
                  {{ row.severity }}
                </ElTag>
              </template>
            </ElTableColumn>
            <ElTableColumn label="证据" width="80">
              <template #default="{ row }">{{ row.evidenceLinkIds.length }}</template>
            </ElTableColumn>
            <ElTableColumn label="规则" width="80">
              <template #default="{ row }">{{ row.ruleRefs.length }}</template>
            </ElTableColumn>
            <ElTableColumn label="置信度" width="88">
              <template #default="{ row }">{{ Math.round(row.confidence * 100) }}%</template>
            </ElTableColumn>
          </ElTable>
        </ElCard>
      </ElCol>
    </ElRow>
  </div>
</template>

<style scoped lang="less">
.generic-workbench {
  min-height: 100%;
  padding: 16px;
  background: #f5f7fb;
}

.page-title {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.page-title h1 {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}

.page-title p {
  margin: 6px 0 0;
  color: var(--el-text-color-secondary);
}

.panel {
  border-radius: 8px;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.generic-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.summary-label {
  margin-bottom: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

@media (width <= 768px) {
  .generic-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
