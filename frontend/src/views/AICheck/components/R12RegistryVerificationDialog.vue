<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCheckbox,
  ElDialog,
  ElInput,
  ElOption,
  ElSelect,
  ElTag,
  ElMessage
} from 'element-plus'
import type {
  R12LicenseCandidate,
  R12RegistryVerificationInput,
  ReviewHumanInputTask
} from '@/api/aicheck'

const props = defineProps<{
  modelValue: boolean
  task?: ReviewHumanInputTask | null
  loading?: boolean
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
  (
    event: 'submit',
    payload: { verifications: R12RegistryVerificationInput[]; comment?: string }
  ): void
  (event: 'locate', candidate: R12LicenseCandidate): void
}>()

type VerificationDraft = R12RegistryVerificationInput & { attachmentText: string }

const drafts = reactive<Record<string, VerificationDraft>>({})
const generalComment = ref('')

const candidates = computed(() => props.task?.candidates || [])

const initializeDrafts = () => {
  const activeIds = new Set(candidates.value.map((item) => item.candidateId))
  for (const key of Object.keys(drafts)) {
    if (!activeIds.has(key)) delete drafts[key]
  }
  if (!props.modelValue) generalComment.value = ''
  for (const candidate of candidates.value) {
    drafts[candidate.candidateId] ||= {
      candidateId: candidate.candidateId,
      outcome: 'verified_match',
      registryLicenseNo: candidate.licenseNo || '',
      registryOrganizationName: candidate.organizationName || '',
      registryStatus: 'active',
      registryScopeRaw: candidate.licenseScopeRaw || '',
      registryValidFrom: candidate.validFrom || '',
      registryValidUntil: candidate.validUntil || '',
      sourceUrl: props.task?.officialRegistryUrl || '',
      attachmentIds: [],
      attachmentText: '',
      comment: '',
      correctionReason: '',
      attested: false
    }
  }
}

watch(
  () => [props.task?.taskId, props.modelValue],
  () => initializeDrafts(),
  { immediate: true }
)

const close = () => emit('update:modelValue', false)

const copyLicenseNo = async (candidate: R12LicenseCandidate) => {
  if (!candidate.licenseNo) return
  await navigator.clipboard.writeText(candidate.licenseNo)
  ElMessage.success('许可证号已复制')
}

const openRegistry = () => {
  const url = props.task?.officialRegistryUrl
  if (!url) {
    ElMessage.warning('后台尚未配置全国特种设备公示信息查询平台地址')
    return
  }
  window.open(url, '_blank', 'noopener,noreferrer')
}

const validate = () => {
  for (const candidate of candidates.value) {
    const item = drafts[candidate.candidateId]
    if (!item?.outcome) return `请填写 ${candidate.licenseNo || candidate.candidateId} 的核验结果`
    if (!item.attested) return `请确认已人工查询 ${candidate.licenseNo || candidate.candidateId}`
    if (['verified_match', 'verified_mismatch'].includes(item.outcome) && !item.sourceUrl?.trim()) {
      return `请填写 ${candidate.licenseNo || candidate.candidateId} 的官网查询地址`
    }
    if (
      item.outcome === 'verified_match' &&
      (!item.registryLicenseNo?.trim() ||
        !item.registryOrganizationName?.trim() ||
        !item.registryScopeRaw?.trim())
    ) {
      return `请完整填写 ${candidate.licenseNo || candidate.candidateId} 的官网证号、单位和许可范围`
    }
    const identityChanged =
      item.outcome === 'verified_match' &&
      (item.registryLicenseNo?.trim() !== (candidate.licenseNo || '').trim() ||
        item.registryOrganizationName?.trim() !== (candidate.organizationName || '').trim())
    if (identityChanged && !item.correctionReason?.trim()) {
      return `官网信息与 OCR 不一致，请填写 ${candidate.licenseNo || candidate.candidateId} 的更正原因`
    }
  }
  return ''
}

const submit = () => {
  const error = validate()
  if (error) {
    ElMessage.warning(error)
    return
  }
  emit('submit', {
    verifications: candidates.value.map((candidate) => {
      const { attachmentText, ...item } = drafts[candidate.candidateId]
      return {
        ...item,
        attachmentIds: attachmentText
          .split(/[,，\n]/)
          .map((value) => value.trim())
          .filter(Boolean)
      }
    }),
    comment: generalComment.value.trim() || undefined
  })
}
</script>

<template>
  <ElDialog
    :model-value="modelValue"
    width="min(980px, 94vw)"
    title="R12 · 制造许可证官网人工核验"
    :close-on-click-modal="false"
    destroy-on-close
    @update:model-value="emit('update:modelValue', $event)"
  >
    <ElAlert
      type="warning"
      :closable="false"
      show-icon
      title="此步骤不能由模型代替人工完成"
      description="请在全国特种设备公示信息查询平台逐证查询。OCR 内容仅用于查找证号；最终登记状态、单位名称、许可范围和有效期以人工查询结果为准。"
    />

    <div class="dialog-actions">
      <span>{{ task?.description }}</span>
      <ElButton type="primary" plain @click="openRegistry">打开官方查询平台</ElButton>
    </div>

    <div v-if="!candidates.length" class="empty-candidates">未识别到待核验的制造许可证候选。</div>
    <article v-for="candidate in candidates" :key="candidate.candidateId" class="candidate-card">
      <header>
        <div>
          <strong>{{ candidate.licenseNo || '未识别许可证号' }}</strong>
          <span>{{ candidate.organizationName || '未识别单位名称' }}</span>
        </div>
        <div class="candidate-actions">
          <ElTag type="info"
            >{{ candidate.fileName || candidate.documentVersionId }} · 第
            {{ candidate.pageNo }} 页</ElTag
          >
          <ElButton text type="primary" @click="copyLicenseNo(candidate)">复制证号</ElButton>
          <ElButton text type="primary" @click="emit('locate', candidate)">查看证据页</ElButton>
        </div>
      </header>

      <div class="ocr-summary">
        <label>OCR 许可范围</label>
        <span>{{ candidate.licenseScopeRaw || '未识别' }}</span>
      </div>

      <div v-if="drafts[candidate.candidateId]" class="verification-grid">
        <label>
          <span>查询结果</span>
          <ElSelect v-model="drafts[candidate.candidateId].outcome">
            <ElOption label="官网登记一致" value="verified_match" />
            <ElOption label="官网登记不一致" value="verified_mismatch" />
            <ElOption label="官网未查到" value="not_found" />
            <ElOption label="本次无法核验" value="unable_to_verify" />
          </ElSelect>
        </label>
        <label>
          <span>证照状态</span>
          <ElSelect v-model="drafts[candidate.candidateId].registryStatus">
            <ElOption label="有效" value="active" />
            <ElOption label="过期" value="expired" />
            <ElOption label="吊销" value="revoked" />
            <ElOption label="暂停" value="suspended" />
            <ElOption label="未知" value="unknown" />
          </ElSelect>
        </label>
        <label>
          <span>官网许可证号</span>
          <ElInput v-model="drafts[candidate.candidateId].registryLicenseNo" />
        </label>
        <label>
          <span>官网单位名称</span>
          <ElInput v-model="drafts[candidate.candidateId].registryOrganizationName" />
        </label>
        <label class="wide">
          <span>官网许可范围</span>
          <ElInput
            v-model="drafts[candidate.candidateId].registryScopeRaw"
            type="textarea"
            :rows="3"
          />
        </label>
        <label>
          <span>官网有效期起</span>
          <ElInput
            v-model="drafts[candidate.candidateId].registryValidFrom"
            placeholder="YYYY-MM-DD"
          />
        </label>
        <label>
          <span>官网有效期止</span>
          <ElInput
            v-model="drafts[candidate.candidateId].registryValidUntil"
            placeholder="YYYY-MM-DD"
          />
        </label>
        <label class="wide">
          <span>查询结果地址</span>
          <ElInput v-model="drafts[candidate.candidateId].sourceUrl" />
        </label>
        <label class="wide">
          <span>更正原因（官网证号或单位与 OCR 不一致时必填）</span>
          <ElInput v-model="drafts[candidate.candidateId].correctionReason" />
        </label>
        <label class="wide">
          <span>核验截图/附件 ID（可选，逗号分隔）</span>
          <ElInput v-model="drafts[candidate.candidateId].attachmentText" />
        </label>
        <label class="wide">
          <span>核验说明</span>
          <ElInput v-model="drafts[candidate.candidateId].comment" type="textarea" :rows="2" />
        </label>
        <ElCheckbox v-model="drafts[candidate.candidateId].attested" class="wide">
          我确认已由本人访问官方查询平台并按页面结果填写以上信息
        </ElCheckbox>
      </div>
    </article>

    <label class="general-comment">
      <span>本次人工核验总说明（可选）</span>
      <ElInput v-model="generalComment" type="textarea" :rows="2" />
    </label>

    <template #footer>
      <ElButton @click="close">稍后处理</ElButton>
      <ElButton type="primary" :loading="loading" :disabled="!candidates.length" @click="submit">
        保存核验结果并继续 AI 复核
      </ElButton>
    </template>
  </ElDialog>
</template>

<style scoped>
.dialog-actions,
.candidate-card header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.dialog-actions {
  margin: 16px 0;
  color: var(--el-text-color-secondary);
}

.candidate-card {
  padding: 16px;
  margin-top: 14px;
  border: 1px solid var(--el-border-color);
  border-radius: 10px;
}

.candidate-card header > div:first-child {
  display: grid;
  gap: 4px;
}

.candidate-card header span,
.ocr-summary,
.empty-candidates {
  color: var(--el-text-color-secondary);
}

.candidate-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.ocr-summary {
  display: grid;
  grid-template-columns: 112px 1fr;
  padding: 10px 12px;
  margin: 14px 0;
  background: var(--el-fill-color-light);
  border-radius: 8px;
}

.verification-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.verification-grid label,
.general-comment {
  display: grid;
  gap: 6px;
  font-size: 13px;
}

.verification-grid .wide,
.general-comment {
  grid-column: 1 / -1;
}

.general-comment {
  margin-top: 16px;
}

@media (width <= 720px) {
  .dialog-actions,
  .candidate-card header {
    align-items: flex-start;
    flex-direction: column;
  }

  .verification-grid {
    grid-template-columns: 1fr;
  }
}
</style>
