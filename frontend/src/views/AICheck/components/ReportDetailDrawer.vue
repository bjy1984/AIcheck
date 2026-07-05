<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  ElAlert,
  ElButton,
  ElDescriptions,
  ElDescriptionsItem,
  ElDrawer,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElInput,
  ElSkeleton,
  ElTabPane,
  ElTabs,
  ElTable,
  ElTableColumn,
  ElTag
} from 'element-plus'
import type { ReportDetailPayload, ReportSection } from '@/api/aicheck'
import type { EvidenceLink } from '@/types/aicheck'
import { getStatusTagType } from './status'

type EditableReportSection = ReportSection & {
  evidenceText: string
}

const props = defineProps<{
  modelValue: boolean
  detail?: ReportDetailPayload
  loading: boolean
  saving?: boolean
  issue?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  locateEvidence: [evidence: EvidenceLink]
  retry: []
  save: [payload: { sections: ReportSection[]; remark?: string }]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})

const report = computed(() => props.detail?.report)
const evidenceMap = computed(
  () => new Map((props.detail?.evidenceLinks || []).map((evidence) => [evidence.id, evidence]))
)
const isEditing = ref(false)
const editableSections = ref<EditableReportSection[]>([])
const saveRemark = ref('')
const evidenceIdOptions = computed(() => (props.detail?.evidenceLinks || []).map((item) => item.id))
const canEdit = computed(
  () =>
    Boolean(report.value?.actions?.includes('report:review')) &&
    !['已签发', '已归档'].includes(report.value?.status || '')
)

const getEvidenceItems = (ids: string[]) =>
  ids.map((id) => evidenceMap.value.get(id)).filter(Boolean) as EvidenceLink[]

const toEditableSection = (section: ReportSection): EditableReportSection => ({
  ...section,
  evidenceLinkIds: [...section.evidenceLinkIds],
  evidenceText: section.evidenceLinkIds.join(', ')
})

const resetEditor = () => {
  editableSections.value = (props.detail?.sections || []).map(toEditableSection)
  saveRemark.value = ''
}

watch(
  () => props.detail?.report?.etag,
  () => {
    isEditing.value = false
    resetEditor()
  },
  { immediate: true }
)

const startEdit = () => {
  resetEditor()
  isEditing.value = true
}

const cancelEdit = () => {
  resetEditor()
  isEditing.value = false
}

const addSection = () => {
  editableSections.value.push({
    key: `section-${editableSections.value.length + 1}`,
    title: '',
    content: '',
    evidenceLinkIds: [],
    evidenceText: ''
  })
}

const removeSection = (index: number) => {
  if (editableSections.value.length <= 1) return
  editableSections.value.splice(index, 1)
}

const splitEvidenceIds = (value: string) =>
  value
    .split(/[,，\s]+/)
    .map((item) => item.trim())
    .filter(Boolean)

const saveEdit = () => {
  emit('save', {
    sections: editableSections.value.map((section, index) => ({
      key: section.key || `section-${index + 1}`,
      title: section.title,
      content: section.content,
      evidenceLinkIds: splitEvidenceIds(section.evidenceText)
    })),
    remark: saveRemark.value || '编辑报告章节'
  })
}
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
        <div class="report-head-actions">
          <ElTag :type="getStatusTagType(report.status)" effect="plain">
            {{ report.status }}
          </ElTag>
          <ElButton v-if="canEdit && !isEditing" type="primary" plain @click="startEdit">
            编辑报告
          </ElButton>
          <template v-else-if="isEditing">
            <ElButton :disabled="saving" @click="cancelEdit">取消</ElButton>
            <ElButton type="primary" :loading="saving" @click="saveEdit">保存</ElButton>
          </template>
        </div>
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
          <div v-if="isEditing" class="section-editor">
            <ElAlert
              type="info"
              :closable="false"
              show-icon
              title="编辑章节正文和证据引用，证据 ID 用逗号分隔。"
            />
            <div v-if="evidenceIdOptions.length" class="evidence-id-strip">
              <span>可用证据</span>
              <code v-for="id in evidenceIdOptions" :key="id">{{ id }}</code>
            </div>
            <ElForm label-position="top" class="report-section-form">
              <section
                v-for="(section, index) in editableSections"
                :key="section.key || index"
                class="section-edit-block"
              >
                <div class="section-edit-head">
                  <strong>章节 {{ index + 1 }}</strong>
                  <ElButton
                    v-if="editableSections.length > 1"
                    type="danger"
                    link
                    @click="removeSection(index)"
                  >
                    删除
                  </ElButton>
                </div>
                <ElFormItem label="标题">
                  <ElInput v-model="section.title" placeholder="例如：检验结论" />
                </ElFormItem>
                <ElFormItem label="正文">
                  <ElInput
                    v-model="section.content"
                    type="textarea"
                    :rows="5"
                    placeholder="填写报告正文"
                  />
                </ElFormItem>
                <ElFormItem label="证据 ID">
                  <ElInput
                    v-model="section.evidenceText"
                    placeholder="例如：EV-24-001, EV-24-002"
                  />
                </ElFormItem>
              </section>
              <div class="section-editor-actions">
                <ElButton plain @click="addSection">新增章节</ElButton>
              </div>
              <ElFormItem label="保存说明">
                <ElInput v-model="saveRemark" placeholder="例如：补充检验结论和证据引用" />
              </ElFormItem>
            </ElForm>
          </div>

          <div v-else class="section-list">
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

.report-head-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  justify-content: flex-end;
}

.report-head-actions :deep(.el-button) {
  margin-left: 0;
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

.section-editor {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.evidence-id-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  padding: 10px 12px;
  color: #667085;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.evidence-id-strip span {
  margin-right: 4px;
  font-size: 12px;
}

.evidence-id-strip code {
  padding: 2px 6px;
  font-size: 12px;
  color: #1f2937;
  background: #fff;
  border: 1px solid #d0d5dd;
  border-radius: 4px;
}

.report-section-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.section-edit-block {
  padding: 12px;
  background: #fff;
  border: 1px solid #dbeafe;
  border-radius: 8px;
}

.section-edit-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.section-edit-head strong {
  color: #1f2937;
}

.section-editor-actions {
  display: flex;
  justify-content: flex-start;
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
