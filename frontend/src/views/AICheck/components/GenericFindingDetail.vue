<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElAlert, ElButton, ElEmpty, ElTag } from 'element-plus'
import { getEvidenceChainApi, getNodePackageApi } from '@/api/aicheck'
import type { ReviewFinding } from '@/api/aicheck'
import type { EvidenceLink, NodePackagePayload } from '@/types/aicheck'
import { useUserStore } from '@/store/modules/user'
import { getAicheckErrorMessage } from '@/utils/aicheckError'
import { findingReviewState } from '../workbenchTruth'

const props = defineProps<{
  finding: ReviewFinding
  nodeName: string
  showReviewDetails?: boolean
}>()
const router = useRouter()
const userStore = useUserStore()
const loading = ref(false)
const issue = ref('')
const evidence = ref<EvidenceLink[]>([])
const nodePackage = ref<NodePackagePayload>()
const requestGeneration = { value: 0 }
const linkedEvidence = computed(() =>
  props.finding.evidenceLinkIds.map((id) => ({
    id,
    detail: evidence.value.find((item) => item.id === id)
  }))
)
const canOpenReview = computed(
  () =>
    userStore.getUserInfo?.role === 'inspection' &&
    nodePackage.value?.actions.includes('review:save')
)
const loadDetail = async () => {
  const finding = props.finding
  const generation = ++requestGeneration.value
  loading.value = true
  issue.value = ''
  evidence.value = []
  nodePackage.value = undefined
  try {
    const [chain, node] = await Promise.all([
      getEvidenceChainApi(finding.projectId, finding.nodeId),
      getNodePackageApi(finding.projectId, finding.nodeId)
    ])
    if (generation !== requestGeneration.value) return
    if (!chain?.data || !node?.data) throw new Error('发现关联资料返回不完整')
    evidence.value = chain.data.links
    nodePackage.value = node.data
  } catch (error) {
    if (generation === requestGeneration.value)
      issue.value = getAicheckErrorMessage(error, '关联证据与人工意见加载失败，请重试。')
  } finally {
    if (generation === requestGeneration.value) loading.value = false
  }
}
const openNodeReview = () =>
  router.push({
    path: '/workbench/inspection',
    query: {
      projectId: props.finding.projectId,
      nodeId: String(props.finding.nodeId),
      view: 'list',
      auditItem: 'human_review'
    }
  })
watch(() => props.finding.id, loadDetail, { immediate: true })
</script>

<template>
  <section class="finding-detail" aria-label="发现详情与关联证据">
    <div class="finding-detail-heading">
      <div
        ><h3>{{ finding.title }}</h3
        ><p>{{ nodeName }}</p></div
      >
      <ElTag effect="plain">{{ findingReviewState(finding) }}</ElTag>
    </div>
    <p class="finding-description">{{ finding.description || '这条发现尚未提供详细说明。' }}</p>
    <p
      v-if="finding.suggestedAction && finding.suggestedAction !== 'human_confirm'"
      class="finding-description"
    >
      建议：{{ finding.suggestedAction }}
    </p>
    <details v-if="showReviewDetails && finding.ruleRefs.length" class="reference-details">
      <summary>规则引用</summary>
      <p>{{ finding.ruleRefs.map((rule) => rule.ruleCode || rule.ruleSetId).join('、') }}</p>
    </details>
    <p v-if="loading" role="status">正在读取这条发现的关联证据与节点人工意见…</p>
    <ElAlert v-else-if="issue" type="error" :closable="false" :title="issue">
      <ElButton @click="loadDetail">重试关联资料</ElButton>
    </ElAlert>
    <template v-else>
      <h4>这条发现引用的证据</h4>
      <ElEmpty
        v-if="!linkedEvidence.length"
        description="这条发现没有关联证据，不能据此形成正式结论"
        :image-size="56"
      />
      <ul v-else class="evidence-list">
        <li v-for="item in linkedEvidence" :key="item.id">
          <template v-if="item.detail">
            <strong>{{ item.detail.fileName || item.detail.fieldName || '证据记录' }}</strong>
            <span v-if="item.detail.pageNo"> · 第 {{ item.detail.pageNo }} 页</span>
            <p>{{ item.detail.quotedText || '此证据未提供原文摘录，请在节点资料中核对原文。' }}</p>
            <details v-if="showReviewDetails" class="reference-details">
              <summary>引用编号</summary>
              <small>{{ item.id }}</small>
            </details>
          </template>
          <template v-else>
            <strong>引用证据暂不可查看</strong>
            <p>暂时无法取得这条引用的原文，请由审查人员核对关联资料。</p>
            <details v-if="showReviewDetails" class="reference-details">
              <summary>引用编号</summary>
              <small>{{ item.id }}</small>
            </details>
          </template>
        </li>
      </ul>
      <h4>节点已保存的人工意见</h4>
      <p class="section-note">以下为同一节点的审查记录；本条发现是否已处理，以顶部状态为准。</p>
      <ul v-if="nodePackage?.reviewOpinions.length" class="evidence-list">
        <li v-for="opinion in nodePackage.reviewOpinions" :key="opinion.id">
          <strong>{{ opinion.result }}</strong> · {{ opinion.reviewerName }} ·
          {{ opinion.createdAt }}
          <p>{{ opinion.opinion }}</p>
        </li>
      </ul>
      <p v-else>当前没有可查看的人工意见。</p>
      <ElButton v-if="canOpenReview" type="primary" @click="openNodeReview"
        >到此节点核对并填写人工结论</ElButton
      >
    </template>
  </section>
</template>

<style scoped>
.finding-detail {
  padding: 20px;
  background: var(--el-fill-color-light);
}
.finding-detail-heading {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}
h3 {
  margin: 0;
  font-size: 18px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}
h4 {
  margin: 24px 0 12px;
  font-size: 15px;
}
p {
  margin: 8px 0;
  line-height: 1.65;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.finding-description {
  max-width: 75ch;
}
.section-note,
small {
  color: var(--el-text-color-regular);
}
.reference-details {
  margin-top: 12px;
  color: var(--el-text-color-regular);
}
.reference-details summary {
  width: fit-content;
  cursor: pointer;
}
.reference-details summary:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: 3px;
}
.evidence-list {
  padding: 0;
  list-style: none;
}
.evidence-list li {
  padding: 12px 0;
  border-bottom: 1px solid var(--el-border-color);
  overflow-wrap: anywhere;
}
</style>
