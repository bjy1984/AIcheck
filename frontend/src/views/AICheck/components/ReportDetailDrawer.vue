<script setup lang="ts">
import { computed } from 'vue'
import {
  ElAlert,
  ElButton,
  ElDescriptions,
  ElDescriptionsItem,
  ElDrawer,
  ElEmpty,
  ElSkeleton,
  ElTabPane,
  ElTabs,
  ElTable,
  ElTableColumn,
  ElTag
} from 'element-plus'
import type { ReportDetailPayload } from '@/api/aicheck'
import type { EvidenceLink } from '@/types/aicheck'
import { getStatusTagType } from './status'

const props = defineProps<{
  modelValue: boolean
  detail?: ReportDetailPayload
  loading: boolean
  issue?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  locateEvidence: [evidence: EvidenceLink]
  retry: []
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})

const report = computed(() => props.detail?.report)
const evidenceMap = computed(
  () => new Map((props.detail?.evidenceLinks || []).map((evidence) => [evidence.id, evidence]))
)

const getEvidenceItems = (ids: string[]) =>
  ids.map((id) => evidenceMap.value.get(id)).filter(Boolean) as EvidenceLink[]
</script>

<template>
  <ElDrawer v-model="visible" title="报告复核详情" size="680px" class="report-detail-drawer">
    <ElSkeleton v-if="loading" :rows="8" animated />

    <ElAlert
      v-else-if="issue"
      class="report-detail-error"
      type="error"
      title="报告详情加载失败"
      :closable="false"
      show-icon
    >
      <div class="drawer-error-content">
        <span>{{ issue }}</span>
        <ElButton link type="primary" @click="emit('retry')">重新加载报告详情</ElButton>
      </div>
    </ElAlert>

    <template v-else-if="detail && report">
      <div class="report-head">
        <div>
          <span>报告编号</span>
          <strong>{{ report.reportNo }} · {{ report.versionNo }}</strong>
        </div>
        <ElTag :type="getStatusTagType(report.status)" effect="plain">
          {{ report.status }}
        </ElTag>
      </div>

      <ElDescriptions :column="2" border class="report-descriptions">
        <ElDescriptionsItem label="报告名称">{{ report.title }}</ElDescriptionsItem>
        <ElDescriptionsItem label="生成范围">
          {{ report.scope === 'project' ? '项目范围' : '当前节点' }}
        </ElDescriptionsItem>
        <ElDescriptionsItem label="覆盖节点">{{ report.nodeIds.join('、') }}</ElDescriptionsItem>
        <ElDescriptionsItem label="复核人">{{ report.reviewerName || '-' }}</ElDescriptionsItem>
        <ElDescriptionsItem label="生成时间">{{ report.generatedAt }}</ElDescriptionsItem>
        <ElDescriptionsItem label="证据数量">{{ detail.evidenceLinks.length }}</ElDescriptionsItem>
      </ElDescriptions>

      <ElTabs class="detail-tabs">
        <ElTabPane label="报告章节" name="sections">
          <div class="section-list">
            <div v-for="section in detail.sections" :key="section.key" class="section-block">
              <div class="section-title">{{ section.title }}</div>
              <p>{{ section.content }}</p>
              <div v-if="section.evidenceLinkIds.length" class="evidence-chips">
                <ElButton
                  v-for="evidence in getEvidenceItems(section.evidenceLinkIds)"
                  :key="evidence.id"
                  size="small"
                  @click="emit('locateEvidence', evidence)"
                >
                  {{ evidence.fieldName || evidence.fileName || evidence.id }}
                </ElButton>
              </div>
            </div>
          </div>
        </ElTabPane>

        <ElTabPane label="证据引用" name="evidence">
          <ElTable :data="detail.evidenceLinks" border height="320">
            <ElTableColumn prop="objectType" label="类型" width="120" />
            <ElTableColumn prop="fileName" label="文件" min-width="180" show-overflow-tooltip />
            <ElTableColumn prop="pageNo" label="页码" width="72" />
            <ElTableColumn prop="quotedText" label="摘录" min-width="220" show-overflow-tooltip />
            <ElTableColumn label="操作" width="82" fixed="right">
              <template #default="{ row }">
                <ElButton link type="primary" @click="emit('locateEvidence', row)">定位</ElButton>
              </template>
            </ElTableColumn>
          </ElTable>
        </ElTabPane>

        <ElTabPane label="复核轨迹" name="trail">
          <ElTable :data="detail.reviewTrail" border height="300">
            <ElTableColumn prop="title" label="节点" min-width="150" show-overflow-tooltip />
            <ElTableColumn prop="actorName" label="处理人" width="90" />
            <ElTableColumn prop="result" label="结果" width="92">
              <template #default="{ row }">
                <ElTag :type="getStatusTagType(row.result)" size="small" effect="plain">
                  {{ row.result }}
                </ElTag>
              </template>
            </ElTableColumn>
            <ElTableColumn prop="createdAt" label="时间" width="150" />
            <ElTableColumn prop="comment" label="说明" min-width="220" show-overflow-tooltip />
          </ElTable>
        </ElTabPane>

        <ElTabPane label="版本历史" name="versions">
          <ElTable :data="detail.versionHistory" border height="260">
            <ElTableColumn prop="versionNo" label="版本" width="80" />
            <ElTableColumn prop="status" label="状态" width="96">
              <template #default="{ row }">
                <ElTag :type="getStatusTagType(row.status)" size="small" effect="plain">
                  {{ row.status }}
                </ElTag>
              </template>
            </ElTableColumn>
            <ElTableColumn prop="generatedAt" label="生成时间" width="150" />
            <ElTableColumn prop="summary" label="摘要" min-width="220" show-overflow-tooltip />
          </ElTable>
        </ElTabPane>
      </ElTabs>
    </template>

    <ElEmpty v-else description="暂无报告详情" />
  </ElDrawer>
</template>

<style scoped>
.report-head {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.report-head span {
  display: block;
  margin-bottom: 4px;
  font-size: 12px;
  color: #667085;
}

.report-head strong {
  color: #1f2937;
}

.report-descriptions {
  margin-bottom: 12px;
}

.detail-tabs {
  margin-top: 4px;
}

.section-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.section-block {
  padding: 12px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.section-title {
  margin-bottom: 6px;
  font-weight: 700;
  color: #1f2937;
}

.section-block p {
  margin: 0;
  line-height: 1.7;
  color: #344054;
}

.evidence-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.evidence-chips :deep(.el-button) {
  margin-left: 0;
}

.drawer-error-content {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  justify-content: space-between;
  line-height: 1.6;
}

.drawer-error-content span {
  overflow-wrap: anywhere;
}

@media (width <= 768px) {
  :global(.report-detail-drawer.el-drawer) {
    width: 100vw !important;
    max-width: 100vw;
  }

  .drawer-error-content {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
